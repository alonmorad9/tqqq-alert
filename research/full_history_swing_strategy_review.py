"""Full-history daily cross-check for the revived TQQQ swing strategy.

The live bot uses intraday 10-minute checks, but free intraday history is short.
This script uses daily adjusted data back to TQQQ inception to sanity-check
whether recent 10-minute winners are also reasonable over a longer history.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "research" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

START_CAPITAL = 1000.0
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
    sma50_slope10_min: float | None = None
    qqq_ema21_slope5_min: float | None = None
    trend_efficiency20_min: float | None = None


def fetch_yahoo_chart(symbol: str) -> dict:
    cache_path = Path(f"/private/tmp/{symbol.lower().replace('^', '')}_daily_history.json")
    if cache_path.exists():
        return json.loads(cache_path.read_text())

    response = requests.get(
        f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={
            "period1": 1262304000,
            "period2": 4102444800,
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    cache_path.write_text(json.dumps(payload))
    return payload


def load_prices(symbol: str) -> pd.DataFrame:
    payload = fetch_yahoo_chart(symbol)
    result = payload["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    adjclose = result["indicators"].get("adjclose", [{}])[0].get("adjclose")
    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(result["timestamp"], unit="s").tz_localize("UTC").tz_convert("America/New_York").date,
            "Open": quote["open"],
            "High": quote["high"],
            "Low": quote["low"],
            "Close": quote["close"],
            "AdjClose": adjclose or quote["close"],
            "Volume": quote["volume"],
        }
    ).dropna()
    factor = df["AdjClose"] / df["Close"]
    for col in ["Open", "High", "Low", "Close"]:
        df[col] = df[col] * factor
    return df[["Date", "Open", "High", "Low", "Close", "Volume"]].set_index("Date")


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def adx(data: pd.DataFrame, window: int = 14) -> pd.Series:
    high = data["High"]
    low = data["Low"]
    close = data["Close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.rolling(window).mean()
    plus_di = 100 * plus_dm.rolling(window).mean() / atr
    minus_di = 100 * minus_dm.rolling(window).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.rolling(window).mean()


def prepare() -> pd.DataFrame:
    t = load_prices("TQQQ")
    q = load_prices("QQQ")
    v = load_prices("^VIX")

    t["SMA20"] = t["Close"].rolling(20).mean()
    t["SMA50"] = t["Close"].rolling(50).mean()
    t["SMA200"] = t["Close"].rolling(200).mean()
    t["RSI14"] = rsi(t["Close"])
    t["RET5"] = t["Close"].pct_change(5)
    t["RET10"] = t["Close"].pct_change(10)
    t["SMA20_ABOVE_SMA50"] = t["SMA20"] > t["SMA50"]
    t["SMA50_SLOPE10"] = t["SMA50"] / t["SMA50"].shift(10) - 1
    t["TREND_EFFICIENCY20"] = (t["Close"] - t["Close"].shift(20)).abs() / t["Close"].diff().abs().rolling(20).sum()

    q["QQQ_SMA200"] = q["Close"].rolling(200).mean()
    q["QQQ_EMA21"] = q["Close"].ewm(span=21, adjust=False).mean()
    q["QQQ_EMA21_SLOPE5"] = q["QQQ_EMA21"] / q["QQQ_EMA21"].shift(5) - 1
    q["QQQ_ADX14"] = adx(q)
    q = q[["Close", "QQQ_SMA200", "QQQ_EMA21", "QQQ_EMA21_SLOPE5", "QQQ_ADX14"]].rename(columns={"Close": "QQQ_Close"})

    v["VIX_RET5"] = v["Close"].pct_change(5)
    v = v[["Close", "VIX_RET5"]].rename(columns={"Close": "VIX_Close"})

    df = t.join(q, how="inner").join(v, how="inner").dropna()
    above = (df["Close"] > df["SMA200"]) & (df["QQQ_Close"] > df["QQQ_SMA200"])
    below = (df["Close"] < df["SMA200"]) | (df["QQQ_Close"] < df["QQQ_SMA200"])
    groups_above = above.ne(above.shift()).cumsum()
    groups_below = below.ne(below.shift()).cumsum()
    df["ABOVE_CONFIRM_DAYS"] = above.groupby(groups_above).cumcount().add(1).where(above, 0)
    df["BELOW_CONFIRM_DAYS"] = below.groupby(groups_below).cumcount().add(1).where(below, 0)
    return df


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
    if variant.sma50_slope10_min is not None and row["SMA50_SLOPE10"] < variant.sma50_slope10_min:
        return False
    if variant.qqq_ema21_slope5_min is not None and row["QQQ_EMA21_SLOPE5"] < variant.qqq_ema21_slope5_min:
        return False
    if variant.trend_efficiency20_min is not None and row["TREND_EFFICIENCY20"] < variant.trend_efficiency20_min:
        return False
    return True


def run(df: pd.DataFrame, variant: Variant) -> dict:
    cash = START_CAPITAL
    shares = 0.0
    avg_cost = None
    highest_high = None
    position_open = False
    waiting = False
    last_sell_price = None
    sell_i = None
    trades = []
    equity = []

    rows = list(df.iterrows())
    for i, (date, row) in enumerate(rows):
        prev = rows[max(i - 1, 0)][1]
        price = float(row["Close"])
        above_confirmed = int(row["ABOVE_CONFIRM_DAYS"]) >= SMA_CONFIRM_DAYS
        below_confirmed = int(row["BELOW_CONFIRM_DAYS"]) >= SMA_CONFIRM_DAYS
        rsi_ok = variant.rsi_max is None or row["RSI14"] <= variant.rsi_max
        macro_ok = macro_entry_ok(row, prev, variant)

        if position_open:
            highest_high = max(float(highest_high), float(row["High"]))
            profit_hit = price >= float(avg_cost) * (1 + variant.profit)
            hard_hit = price <= float(avg_cost) * (1 - variant.hard_stop)
            trail_hit = price <= float(highest_high) * (1 - variant.trail)
            sma_hit = below_confirmed
            if profit_hit or hard_hit or trail_hit or sma_hit:
                reason = "profit" if profit_hit else "hard_stop" if hard_hit else "trail_stop" if trail_hit else "sma200"
                cash = shares * price
                trades.append({"date": date, "action": "SELL", "reason": reason, "price": price, "value": cash})
                position_open = False
                shares = 0.0
                avg_cost = None
                highest_high = None
                waiting = True
                last_sell_price = price
                sell_i = i
        else:
            wait_days = 0 if sell_i is None else i - sell_i
            pullback = waiting and last_sell_price is not None and price <= float(last_sell_price) * (1 - variant.reentry_drop)
            timeout = waiting and wait_days >= variant.timeout_days
            fresh = not waiting and above_confirmed and price > row["SMA20"]
            rebuy = waiting and (pullback or timeout) and above_confirmed
            if (fresh or rebuy) and rsi_ok and macro_ok and cash > 0:
                shares = cash / price
                avg_cost = price
                highest_high = float(row["High"])
                trades.append({"date": date, "action": "BUY", "reason": "fresh" if fresh else "rebuy", "price": price, "value": cash})
                cash = 0.0
                position_open = True
                waiting = False
                last_sell_price = None
                sell_i = None

        equity.append(cash + shares * price)

    eq = pd.Series(equity)
    dd = eq / eq.cummax() - 1
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
    years = (pd.Timestamp(df.index[-1]) - pd.Timestamp(df.index[0])).days / 365.25
    final = float(eq.iloc[-1])
    return {
        "name": variant.name,
        "final_multiple": final / START_CAPITAL,
        "cagr": (final / START_CAPITAL) ** (1 / years) - 1,
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


def variants() -> list[Variant]:
    out = [Variant("LIVE current swing")]
    for profit in [0.06, 0.08, 0.10, 0.12, 0.15]:
        for hard in [0.05, 0.075, 0.10]:
            for trail in [0.08, 0.10, 0.12, 0.15]:
                for rsi_cap in [55, 60, 65, 70, None]:
                    out.append(Variant(f"p{profit:.0%} hard{hard:.1%} trail{trail:.0%} rsi{rsi_cap}", profit, hard, trail, 0.03, 3, rsi_cap))
    out.extend(
        [
            Variant("LIVE + VIX <= 20 entry", vix_max=20),
            Variant("LIVE + VIX <= 25 entry", vix_max=25),
            Variant("LIVE + VIX 5d spike <= 15%", vix_ret5_max=0.15),
            Variant("LIVE + VIX 5d spike <= 25%", vix_ret5_max=0.25),
            Variant("LIVE + QQQ above EMA21 entry", require_qqq_ema21=True),
            Variant("LIVE + early score <= 1 entry", max_early_score=1),
            Variant("LIVE + early score <= 2 entry", max_early_score=2),
            Variant("LIVE + macro strict", vix_max=20, vix_ret5_max=0.15, require_qqq_ema21=True, max_early_score=1),
            Variant("LIVE + macro balanced", vix_max=25, vix_ret5_max=0.25, require_qqq_ema21=True, max_early_score=2),
            Variant("LIVE + QQQ ADX >= 15", qqq_adx_min=15),
            Variant("LIVE + QQQ ADX >= 18", qqq_adx_min=18),
            Variant("LIVE + QQQ ADX >= 20", qqq_adx_min=20),
            Variant("LIVE + QQQ ADX >= 25", qqq_adx_min=25),
            Variant("LIVE + SMA20 above SMA50", require_sma20_above_sma50=True),
            Variant("LIVE + SMA50 slope10 > 0", sma50_slope10_min=0),
            Variant("LIVE + QQQ EMA21 slope5 > 0", qqq_ema21_slope5_min=0),
            Variant("LIVE + trend efficiency20 >= 0.20", trend_efficiency20_min=0.20),
            Variant("LIVE + trend efficiency20 >= 0.30", trend_efficiency20_min=0.30),
            Variant("LIVE + ADX18 and SMA20 above SMA50", qqq_adx_min=18, require_sma20_above_sma50=True),
            Variant("LIVE + ADX18 and EMA21 slope", qqq_adx_min=18, qqq_ema21_slope5_min=0),
        ]
    )
    return out


def main() -> None:
    df = prepare()
    print(f"DATA {df.index[0]} -> {df.index[-1]} rows={len(df)}")
    rows = [run(df, variant) for variant in variants()]
    results = pd.DataFrame(rows).drop_duplicates(subset=["name"])
    results = results.sort_values(["final_multiple", "maxdd"], ascending=[False, False])
    out_path = OUT_DIR / "full_history_swing_strategy_results.csv"
    results.to_csv(out_path, index=False)
    display = results.head(25).copy()
    display["final_multiple"] = display["final_multiple"].map(lambda x: f"{x:.1f}x")
    display["cagr"] = display["cagr"].map(lambda x: f"{x:.1%}")
    display["maxdd"] = display["maxdd"].map(lambda x: f"{x:.1%}")
    display["win_rate"] = display["win_rate"].map(lambda x: f"{x:.1%}")
    print(display.to_string(index=False))
    print(f"\nWrote {out_path}")
    print("\nKEY")
    key = results[results["name"].isin(["LIVE current swing", "p12% hard5.0% trail8% rsi70", "LIVE + early score <= 1 entry", "LIVE + macro balanced"])]
    print(key.to_string(index=False))


if __name__ == "__main__":
    main()
