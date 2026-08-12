"""Recent 10-minute TQQQ swing strategy review.

This focuses on the practical question: over the recent free intraday window,
does the live swing strategy still look best, and do VIX/macro filters help?
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "research" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

START_CAPITAL = 1000.0
ENTRY_OPEN_DELAY_BARS = 6  # 6 * 5m = 30 minutes
SMA_CONFIRM_DAYS = 3


@dataclass(frozen=True)
class Variant:
    name: str
    profit: float = 0.08
    hard_stop: float = 0.075
    trail: float = 0.12
    reentry_drop: float = 0.03
    timeout_days: int = 3
    rsi_max: float | None = 60
    vix_max: float | None = None
    vix_ret5_max: float | None = None
    require_qqq_ema21: bool = False
    max_early_score: int | None = None
    avoid_parabolic_10d: float | None = None
    avoid_parabolic_5d: float | None = None
    qqq_adx_min: float | None = None
    require_sma20_above_sma50: bool = False
    qqq_ema21_slope5_min: float | None = None


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    return df


def download(symbol: str, period: str, interval: str) -> pd.DataFrame:
    df = normalize(yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False))
    if df.empty:
        raise RuntimeError(f"No data for {symbol} {period}/{interval}")
    return df.dropna(subset=["Close"])


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def true_range_atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window).mean()


def adx(data: pd.DataFrame, window: int = 14) -> pd.Series:
    high = data["High"]
    low = data["Low"]
    close = data["Close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(window).mean()
    plus_di = 100 * plus_dm.rolling(window).mean() / atr
    minus_di = 100 * minus_dm.rolling(window).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.rolling(window).mean()


def day(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("America/New_York")
    return pd.Timestamp(ts.date())


def trailing_true_count(values: list[bool]) -> int:
    count = 0
    for value in reversed(values):
        if value:
            count += 1
        else:
            break
    return count


def prepare() -> pd.DataFrame:
    t_daily = download("TQQQ", "2y", "1d")
    q_daily = download("QQQ", "2y", "1d")
    v_daily = download("^VIX", "2y", "1d")
    t_intra = download("TQQQ", "60d", "5m")
    q_intra = download("QQQ", "60d", "5m")
    v_intra = download("^VIX", "60d", "5m")

    # Align all intraday bars and sample on the same 10-minute cadence the bot uses.
    bars = t_intra[["Open", "High", "Low", "Close", "Volume"]].copy()
    bars = bars.join(q_intra[["Close"]].rename(columns={"Close": "QQQ_Close"}), how="inner")
    bars = bars.join(v_intra[["Close"]].rename(columns={"Close": "VIX_Close"}), how="inner")
    bars = bars.iloc[::2].copy()
    bars["Day"] = [day(i) for i in bars.index]

    records = []
    for bar_time, bar in bars.iterrows():
        current_day = bar["Day"]

        t_hist = t_daily[t_daily.index.map(day) < current_day].copy()
        q_hist = q_daily[q_daily.index.map(day) < current_day].copy()
        v_hist = v_daily[v_daily.index.map(day) < current_day].copy()
        if len(t_hist) < 220 or len(q_hist) < 220 or len(v_hist) < 10:
            continue

        todays = bars.loc[bars["Day"] == current_day]
        todays = todays.loc[todays.index <= bar_time]
        t_current = {
            "Open": float(todays["Open"].iloc[0]),
            "High": float(todays["High"].max()),
            "Low": float(todays["Low"].min()),
            "Close": float(bar["Close"]),
            "Volume": float(todays["Volume"].sum()),
        }
        q_current = {
            "Open": float(bar["QQQ_Close"]),
            "High": float(todays["QQQ_Close"].max()),
            "Low": float(todays["QQQ_Close"].min()),
            "Close": float(bar["QQQ_Close"]),
            "Volume": 0.0,
        }
        v_current = {
            "Open": float(bar["VIX_Close"]),
            "High": float(todays["VIX_Close"].max()),
            "Low": float(todays["VIX_Close"].min()),
            "Close": float(bar["VIX_Close"]),
            "Volume": 0.0,
        }
        t = pd.concat([t_hist, pd.DataFrame([t_current], index=[current_day])])
        q = pd.concat([q_hist, pd.DataFrame([q_current], index=[current_day])])
        v = pd.concat([v_hist, pd.DataFrame([v_current], index=[current_day])])

        t_close = t["Close"]
        q_close = q["Close"]
        v_close = v["Close"]
        t_sma200 = t_close.rolling(200).mean()
        q_sma200 = q_close.rolling(200).mean()
        q_ema21 = q_close.ewm(span=21, adjust=False).mean()
        combined_above = ((t_close > t_sma200) & (q_close > q_sma200)).dropna().tolist()
        combined_below = ((t_close < t_sma200) | (q_close < q_sma200)).dropna().tolist()
        rec = {
            "Time": bar_time,
            "Day": current_day,
            "Open": t_current["Open"],
            "High": t_current["High"],
            "Low": t_current["Low"],
            "Close": t_current["Close"],
            "SMA20": float(t_close.rolling(20).mean().iloc[-1]),
            "SMA50": float(t_close.rolling(50).mean().iloc[-1]),
            "SMA200": float(t_sma200.iloc[-1]),
            "SMA20_ABOVE_SMA50": bool(t_close.rolling(20).mean().iloc[-1] > t_close.rolling(50).mean().iloc[-1]),
            "RSI14": float(rsi(t_close).iloc[-1]),
            "RET5": float(t_close.pct_change(5).iloc[-1]),
            "RET10": float(t_close.pct_change(10).iloc[-1]),
            "ATR14": float(true_range_atr(t).iloc[-1]),
            "QQQ_Close": q_current["Close"],
            "QQQ_SMA200": float(q_sma200.iloc[-1]),
            "QQQ_EMA21": float(q_ema21.iloc[-1]),
            "QQQ_EMA21_SLOPE5": float(q_ema21.iloc[-1] / q_ema21.iloc[-6] - 1),
            "QQQ_ADX14": float(adx(q).iloc[-1]),
            "VIX_Close": v_current["Close"],
            "VIX_RET5": float(v_close.pct_change(5).iloc[-1]),
            "ABOVE_CONFIRM_DAYS": trailing_true_count(combined_above),
            "BELOW_CONFIRM_DAYS": trailing_true_count(combined_below),
            "BarsToday": len(todays),
        }
        records.append(rec)

    df = pd.DataFrame(records).dropna()
    return df.reset_index(drop=True)

def early_score(row: pd.Series, prev: pd.Series) -> int:
    checks = [
        row["VIX_Close"] >= 25,
        row["VIX_RET5"] >= 0.25,
        row["QQQ_Close"] < row["QQQ_EMA21"],
        row["Close"] < row["SMA50"],
        prev["RSI14"] >= 70 and row["RSI14"] < prev["RSI14"],
    ]
    return sum(bool(x) for x in checks)


def macro_entry_ok(row: pd.Series, prev: pd.Series, variant: Variant) -> bool:
    if variant.vix_max is not None and row["VIX_Close"] > variant.vix_max:
        return False
    if variant.vix_ret5_max is not None and row["VIX_RET5"] > variant.vix_ret5_max:
        return False
    if variant.require_qqq_ema21 and row["QQQ_Close"] < row["QQQ_EMA21"]:
        return False
    if variant.max_early_score is not None and early_score(row, prev) > variant.max_early_score:
        return False
    if variant.avoid_parabolic_10d is not None and row["RET10"] > variant.avoid_parabolic_10d:
        return False
    if variant.avoid_parabolic_5d is not None and row["RET5"] > variant.avoid_parabolic_5d:
        return False
    if variant.qqq_adx_min is not None and row["QQQ_ADX14"] < variant.qqq_adx_min:
        return False
    if variant.require_sma20_above_sma50 and not bool(row["SMA20_ABOVE_SMA50"]):
        return False
    if variant.qqq_ema21_slope5_min is not None and row["QQQ_EMA21_SLOPE5"] < variant.qqq_ema21_slope5_min:
        return False
    return True


def run(df: pd.DataFrame, variant: Variant) -> tuple[dict, pd.DataFrame]:
    cash = START_CAPITAL
    shares = 0.0
    avg_cost = None
    highest_high = None
    position_open = False
    waiting = False
    last_sell_price = None
    sell_day = None
    trades = []
    equity = []

    for i, row in df.iterrows():
        prev = df.iloc[max(i - 1, 0)]
        price = float(row["Close"])
        d = row["Day"]
        above_confirmed = int(row["ABOVE_CONFIRM_DAYS"]) >= SMA_CONFIRM_DAYS
        below_confirmed = int(row["BELOW_CONFIRM_DAYS"]) >= SMA_CONFIRM_DAYS
        rsi_ok = variant.rsi_max is None or row["RSI14"] <= variant.rsi_max
        entry_delay_ok = int(row["BarsToday"]) > ENTRY_OPEN_DELAY_BARS
        macro_ok = macro_entry_ok(row, prev, variant)

        if position_open:
            highest_high = max(float(highest_high), float(row["High"]))
            value = shares * price
            profit_hit = price >= float(avg_cost) * (1 + variant.profit)
            hard_hit = price <= float(avg_cost) * (1 - variant.hard_stop)
            trail_hit = price <= float(highest_high) * (1 - variant.trail)
            sma_hit = below_confirmed
            if profit_hit or hard_hit or trail_hit or sma_hit:
                reason = "profit" if profit_hit else "hard_stop" if hard_hit else "trail_stop" if trail_hit else "sma200"
                cash = shares * price
                trades.append({"time": row["Time"], "action": "SELL", "reason": reason, "price": price, "value": cash})
                position_open = False
                shares = 0.0
                avg_cost = None
                highest_high = None
                waiting = True
                last_sell_price = price
                sell_day = d
        else:
            wait_days = 0
            if waiting and sell_day is not None:
                wait_days = len(set(df.loc[(df["Day"] > sell_day) & (df["Day"] <= d), "Day"]))
            pullback = waiting and last_sell_price is not None and price <= float(last_sell_price) * (1 - variant.reentry_drop)
            timeout = waiting and wait_days >= variant.timeout_days
            fresh = not waiting and above_confirmed and price > row["SMA20"]
            rebuy = waiting and (pullback or timeout) and above_confirmed
            if (fresh or rebuy) and rsi_ok and entry_delay_ok and macro_ok and cash > 0:
                shares = cash / price
                avg_cost = price
                highest_high = float(row["High"])
                trades.append({"time": row["Time"], "action": "BUY", "reason": "fresh" if fresh else "rebuy", "price": price, "value": cash})
                cash = 0.0
                position_open = True
                waiting = False
                last_sell_price = None
                sell_day = None

        total = cash + shares * price
        equity.append(total)

    eq = pd.Series(equity)
    peak = eq.cummax()
    dd = eq / peak - 1
    trades_df = pd.DataFrame(trades)
    exits = trades_df[trades_df["action"] == "SELL"] if not trades_df.empty else pd.DataFrame()
    wins = 0
    losses = 0
    if not trades_df.empty:
        entries = trades_df[trades_df["action"] == "BUY"].reset_index(drop=True)
        sells = trades_df[trades_df["action"] == "SELL"].reset_index(drop=True)
        for j in range(min(len(entries), len(sells))):
            if sells.loc[j, "price"] > entries.loc[j, "price"]:
                wins += 1
            else:
                losses += 1
    summary = {
        "name": variant.name,
        "final": float(eq.iloc[-1]),
        "return_pct": float(eq.iloc[-1] / START_CAPITAL - 1),
        "maxdd": float(dd.min()),
        "trades": int(len(trades_df)),
        "exits": int(len(exits)),
        "win_rate": wins / (wins + losses) if wins + losses else 0.0,
        "profit_exits": int((exits["reason"] == "profit").sum()) if not exits.empty else 0,
        "hard_stops": int((exits["reason"] == "hard_stop").sum()) if not exits.empty else 0,
        "trail_stops": int((exits["reason"] == "trail_stop").sum()) if not exits.empty else 0,
        "sma_exits": int((exits["reason"] == "sma200").sum()) if not exits.empty else 0,
        "in_position_end": bool(position_open),
    }
    return summary, trades_df


def variants() -> list[Variant]:
    out = [Variant("LIVE current swing")]
    # Focused alternatives around the live strategy.
    for profit in [0.06, 0.08, 0.10, 0.12]:
        for hard in [0.05, 0.075, 0.10]:
            for trail in [0.08, 0.10, 0.12, 0.15]:
                for rsi_cap in [55, 60, 65, 70, None]:
                    out.append(Variant(f"p{profit:.0%} hard{hard:.1%} trail{trail:.0%} rsi{rsi_cap}", profit, hard, trail, 0.03, 3, rsi_cap))

    # Macro/VIX entry blockers, including the user's concern.
    out.extend(
        [
            Variant("LIVE + VIX <= 20 entry", vix_max=20),
            Variant("LIVE + VIX <= 25 entry", vix_max=25),
            Variant("LIVE + VIX 5d spike <= 15%", vix_ret5_max=0.15),
            Variant("LIVE + VIX 5d spike <= 25%", vix_ret5_max=0.25),
            Variant("LIVE + QQQ above EMA21 entry", require_qqq_ema21=True),
            Variant("LIVE + early score <= 1 entry", max_early_score=1),
            Variant("LIVE + early score <= 2 entry", max_early_score=2),
            Variant("LIVE + avoid 10d parabolic >25%", avoid_parabolic_10d=0.25),
            Variant("LIVE + avoid 10d parabolic >30%", avoid_parabolic_10d=0.30),
            Variant("LIVE + macro strict", vix_max=20, vix_ret5_max=0.15, require_qqq_ema21=True, max_early_score=1),
            Variant("LIVE + macro balanced", vix_max=25, vix_ret5_max=0.25, require_qqq_ema21=True, max_early_score=2),
            Variant("LIVE + QQQ ADX >= 15", qqq_adx_min=15),
            Variant("LIVE + QQQ ADX >= 18", qqq_adx_min=18),
            Variant("LIVE + QQQ ADX >= 20", qqq_adx_min=20),
            Variant("LIVE + QQQ ADX >= 25", qqq_adx_min=25),
            Variant("LIVE + SMA20 above SMA50", require_sma20_above_sma50=True),
            Variant("LIVE + ADX18 and SMA20 above SMA50", qqq_adx_min=18, require_sma20_above_sma50=True),
            Variant("LIVE + ADX18 and EMA21 slope", qqq_adx_min=18, qqq_ema21_slope5_min=0),
        ]
    )

    # Re-entry timing alternatives.
    for drop in [0.02, 0.03, 0.05]:
        for timeout in [1, 3, 5, 10]:
            out.append(Variant(f"reentry drop{drop:.0%} timeout{timeout}", reentry_drop=drop, timeout_days=timeout))
    return out


def main() -> None:
    df = prepare()
    print(f"DATA {df['Time'].iloc[0]} -> {df['Time'].iloc[-1]} rows={len(df)} days={df['Day'].nunique()}")
    rows = []
    trade_logs = {}
    for variant in variants():
        summary, trades = run(df, variant)
        rows.append(summary)
        if variant.name in {"LIVE current swing", "LIVE + macro balanced", "LIVE + VIX <= 20 entry", "LIVE + early score <= 1 entry"}:
            trade_logs[variant.name] = trades

    results = pd.DataFrame(rows).drop_duplicates(subset=["name"])
    results = results.sort_values(["final", "maxdd"], ascending=[False, False])
    out_path = OUT_DIR / "two_month_swing_strategy_results.csv"
    results.to_csv(out_path, index=False)
    for name, trades in trade_logs.items():
        safe = name.lower().replace(" ", "_").replace("+", "plus").replace("<=", "lte").replace("%", "pct")
        trades.to_csv(OUT_DIR / f"two_month_{safe}_trades.csv", index=False)

    display = results.head(25).copy()
    display["final"] = display["final"].map(lambda x: f"${x:,.2f}")
    display["return_pct"] = display["return_pct"].map(lambda x: f"{x:+.1%}")
    display["maxdd"] = display["maxdd"].map(lambda x: f"{x:.1%}")
    display["win_rate"] = display["win_rate"].map(lambda x: f"{x:.1%}")
    print(display.to_string(index=False))
    print(f"\nWrote {out_path}")

    current = results[results["name"] == "LIVE current swing"].iloc[0]
    print("\nCURRENT")
    print(current.to_string())


if __name__ == "__main__":
    main()
