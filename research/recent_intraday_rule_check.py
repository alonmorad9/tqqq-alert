#!/usr/bin/env python3
"""Recent intraday sanity check for the live TQQQ rules.

Free Yahoo intraday history is short, so this is not a full strategy optimizer.
It compares the same rule family on recent 5-minute bars against daily-close
evaluation to show whether the live 10-minute bot would trigger materially
earlier than a daily backtest.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yfinance as yf


TICKER = "TQQQ"
TRAILING_STOP_PCT = 0.25
FRESH_ENTRY_GUARD_PCT = 0.10
FRESH_ENTRY_GUARD_DAYS = 2
SWING_PROFIT_TARGET_PCT = 0.20
SWING_REBUY_DROP_PCT = 0.05
SWING_REBUY_TIMEOUT_DAYS = 15
REENTRY_RSI_MAX = 70
PARABOLIC_RET5_WARNING_PCT = 0.25

OUT_DIR = Path("research/out")


@dataclass
class State:
    cash: float = 1.0
    shares: float = 0.0
    avg_cost: float | None = None
    entry_day: pd.Timestamp | None = None
    highest_high: float | None = None
    waiting_for_pullback: bool = False
    last_sell_price: float | None = None
    sell_day: pd.Timestamp | None = None
    cooldown_until: pd.Timestamp | None = None


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    return df.dropna(subset=["Close"]).copy()


def download(symbol: str, period: str, interval: str) -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False)
    df = normalize(df)
    if df.empty:
        raise RuntimeError(f"No data for {symbol} {period}/{interval}")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df


def rsi_from_closes(closes: list[float], window: int = 14) -> float:
    series = pd.Series(closes)
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=window).mean()
    loss = (-delta.clip(upper=0)).rolling(window=window).mean()
    rs = gain / loss
    return float((100 - (100 / (1 + rs))).iloc[-1])


def trading_days_between(start: pd.Timestamp | None, end: pd.Timestamp, days: list[pd.Timestamp]) -> int:
    if start is None:
        return 0
    start_day = pd.Timestamp(start.date())
    end_day = pd.Timestamp(end.date())
    return sum(1 for day in days if start_day < day <= end_day)


def build_rows() -> pd.DataFrame:
    daily = download(TICKER, "2y", "1d")
    qqq_daily = download("QQQ", "2y", "1d")
    vix_daily = download("^VIX", "2y", "1d")
    intra = download(TICKER, "60d", "5m")
    qqq_intra = download("QQQ", "60d", "5m")
    vix_intra = download("^VIX", "60d", "5m")

    daily.index = pd.to_datetime(daily.index.date)
    qqq_daily.index = pd.to_datetime(qqq_daily.index.date)
    vix_daily.index = pd.to_datetime(vix_daily.index.date)

    qqq_daily["EMA21"] = qqq_daily["Close"].ewm(span=21, adjust=False).mean()
    vix_daily["RET5"] = vix_daily["Close"].pct_change(5)

    qqq_close = qqq_intra["Close"].rename("QQQ_Close")
    vix_close = vix_intra["Close"].rename("VIX_Close")
    bars = intra.join(qqq_close, how="left").join(vix_close, how="left").ffill()
    bars = bars.dropna(subset=["Close", "QQQ_Close", "VIX_Close"])

    rows = []
    day_high = {}
    day_low = {}
    daily_days = sorted(pd.Timestamp(day) for day in daily.index)

    for ts, bar in bars.iterrows():
        day = pd.Timestamp(ts.date())
        previous = daily[daily.index < day]
        if len(previous) < 220:
            continue

        day_high[day] = max(float(day_high.get(day, bar["High"])), float(bar["High"]))
        day_low[day] = min(float(day_low.get(day, bar["Low"])), float(bar["Low"]))

        closes = previous["Close"].tolist() + [float(bar["Close"])]
        qqq_previous = qqq_daily[qqq_daily.index < day]
        vix_previous = vix_daily[vix_daily.index < day]
        if len(qqq_previous) < 21 or len(vix_previous) < 6:
            continue

        qqq_alpha = 2 / (21 + 1)
        qqq_ema21 = float(bar["QQQ_Close"]) * qqq_alpha + float(qqq_previous["EMA21"].iloc[-1]) * (1 - qqq_alpha)
        vix_ret5 = float(bar["VIX_Close"]) / float(vix_previous["Close"].iloc[-5]) - 1

        rows.append({
            "time": ts,
            "day": day,
            "Close": float(bar["Close"]),
            "High": float(day_high[day]),
            "Low": float(day_low[day]),
            "SMA200": float(pd.Series(closes[-200:]).mean()),
            "SMA20": float(pd.Series(closes[-20:]).mean()),
            "RSI14": rsi_from_closes(closes[-15:]),
            "RET5": float(bar["Close"]) / float(previous["Close"].iloc[-5]) - 1,
            "RET10": float(bar["Close"]) / float(previous["Close"].iloc[-10]) - 1,
            "QQQ_Close": float(bar["QQQ_Close"]),
            "QQQ_EMA21": qqq_ema21,
            "VIX_Close": float(bar["VIX_Close"]),
            "VIX_RET5": vix_ret5,
        })

    out = pd.DataFrame(rows)
    out.attrs["daily_days"] = daily_days
    return out


def should_check(ts: pd.Timestamp, mode: str, last_bar_by_day: dict[pd.Timestamp, pd.Timestamp]) -> bool:
    if mode == "daily_close":
        return ts == last_bar_by_day[pd.Timestamp(ts.date())]
    minute = ts.minute
    return minute % 10 == 0


def run_engine(rows: pd.DataFrame, mode: str, guard_exit_policy: str = "baseline") -> tuple[pd.DataFrame, float, State]:
    state = State()
    trades = []
    daily_days = rows.attrs["daily_days"]
    last_bar_by_day = rows.groupby("day")["time"].max().to_dict()

    for _, row in rows.iterrows():
        ts = row["time"]
        day = row["day"]
        if not should_check(ts, mode, last_bar_by_day):
            continue

        price = float(row["Close"])
        high = float(row["High"])
        above_sma = price > float(row["SMA200"])
        rsi_ok = float(row["RSI14"]) <= REENTRY_RSI_MAX
        value = state.cash + state.shares * price

        if state.shares > 0:
            state.highest_high = max(float(state.highest_high or high), high)
            days_in_trade = trading_days_between(state.entry_day, day, daily_days)
            fresh_guard_hit = days_in_trade <= FRESH_ENTRY_GUARD_DAYS and price < float(state.avg_cost) * (1 - FRESH_ENTRY_GUARD_PCT)
            trailing_stop_hit = price < float(state.highest_high) * (1 - TRAILING_STOP_PCT)
            profit_hit = price >= float(state.avg_cost) * (1 + SWING_PROFIT_TARGET_PCT)
            parabolic_hit = price >= float(state.avg_cost) and float(row["RET5"]) >= PARABOLIC_RET5_WARNING_PCT
            sma_exit = price < float(row["SMA200"])

            reason = None
            wait_for_reentry = False
            if fresh_guard_hit:
                reason = "fresh_entry_guard"
            elif trailing_stop_hit:
                reason = "trailing_stop"
            elif sma_exit:
                reason = "sma200_exit"
            elif profit_hit:
                reason = "profit_20"
                wait_for_reentry = True
            elif parabolic_hit:
                reason = "parabolic_5d"
                wait_for_reentry = True

            if reason:
                state.cash = state.shares * price
                state.shares = 0
                state.avg_cost = None
                state.entry_day = None
                state.highest_high = None
                state.waiting_for_pullback = wait_for_reentry
                state.last_sell_price = price if wait_for_reentry else None
                state.sell_day = day if wait_for_reentry else None
                state.cooldown_until = None
                if reason == "fresh_entry_guard":
                    if guard_exit_policy == "pullback_wait":
                        state.waiting_for_pullback = True
                        state.last_sell_price = price
                        state.sell_day = day
                    elif guard_exit_policy == "next_day_cooldown":
                        state.cooldown_until = day
                trades.append({"time": ts, "action": "SELL", "reason": reason, "price": price, "value": state.cash})
                continue

        if state.shares == 0:
            if state.cooldown_until is not None and day <= state.cooldown_until:
                continue

            wait_days = trading_days_between(state.sell_day, day, daily_days)
            pullback_hit = state.waiting_for_pullback and state.last_sell_price and price <= state.last_sell_price * (1 - SWING_REBUY_DROP_PCT)
            timeout_hit = state.waiting_for_pullback and wait_days >= SWING_REBUY_TIMEOUT_DAYS
            fresh_buy = not state.waiting_for_pullback and above_sma and rsi_ok
            rebuy = state.waiting_for_pullback and (pullback_hit or timeout_hit) and above_sma and rsi_ok
            if fresh_buy or rebuy:
                state.shares = state.cash / price
                state.cash = 0.0
                state.avg_cost = price
                state.entry_day = day
                state.highest_high = high
                state.waiting_for_pullback = False
                state.last_sell_price = None
                state.sell_day = None
                trades.append({"time": ts, "action": "BUY", "reason": "rebuy" if rebuy else "fresh_buy", "price": price, "value": value})

    final_price = float(rows["Close"].iloc[-1])
    final_value = state.cash + state.shares * final_price
    return pd.DataFrame(trades), final_value, state


def main() -> None:
    cached_rows = OUT_DIR / "recent_intraday_rule_rows.csv"
    if cached_rows.exists():
        rows = pd.read_csv(cached_rows, parse_dates=["time", "day"])
        rows.attrs["daily_days"] = sorted(pd.Timestamp(day) for day in rows["day"].dt.normalize().unique())
    else:
        rows = build_rows()
    if rows.empty:
        raise RuntimeError("No intraday rows built")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows.to_csv(OUT_DIR / "recent_intraday_rule_rows.csv", index=False)

    daily_trades, daily_final, daily_state = run_engine(rows, "daily_close")
    intra_trades, intra_final, intra_state = run_engine(rows, "10min")
    pullback_trades, pullback_final, pullback_state = run_engine(rows, "10min", "pullback_wait")
    cooldown_trades, cooldown_final, cooldown_state = run_engine(rows, "10min", "next_day_cooldown")
    daily_trades.to_csv(OUT_DIR / "recent_intraday_daily_close_trades.csv", index=False)
    intra_trades.to_csv(OUT_DIR / "recent_intraday_10min_trades.csv", index=False)
    pullback_trades.to_csv(OUT_DIR / "recent_intraday_10min_guard_pullback_trades.csv", index=False)
    cooldown_trades.to_csv(OUT_DIR / "recent_intraday_10min_guard_cooldown_trades.csv", index=False)

    summary = pd.DataFrame([
        {
            "mode": "daily_close",
            "final": daily_final,
            "trades": len(daily_trades),
            "sells": int((daily_trades["action"] == "SELL").sum()) if not daily_trades.empty else 0,
            "state": "in_position" if daily_state.shares > 0 else "cash",
        },
        {
            "mode": "10min_checks",
            "final": intra_final,
            "trades": len(intra_trades),
            "sells": int((intra_trades["action"] == "SELL").sum()) if not intra_trades.empty else 0,
            "state": "in_position" if intra_state.shares > 0 else "cash",
        },
        {
            "mode": "10min_guard_pullback_wait",
            "final": pullback_final,
            "trades": len(pullback_trades),
            "sells": int((pullback_trades["action"] == "SELL").sum()) if not pullback_trades.empty else 0,
            "state": "in_position" if pullback_state.shares > 0 else "cash",
        },
        {
            "mode": "10min_guard_next_day_cooldown",
            "final": cooldown_final,
            "trades": len(cooldown_trades),
            "sells": int((cooldown_trades["action"] == "SELL").sum()) if not cooldown_trades.empty else 0,
            "state": "in_position" if cooldown_state.shares > 0 else "cash",
        },
    ])
    summary.to_csv(OUT_DIR / "recent_intraday_rule_summary.csv", index=False)

    print(f"DATA {rows['time'].iloc[0]} -> {rows['time'].iloc[-1]} rows={len(rows)}")
    print(summary.to_string(index=False))
    print("\nDaily-close trades:")
    print(daily_trades.tail(12).to_string(index=False) if not daily_trades.empty else "none")
    print("\n10-minute trades:")
    print(intra_trades.tail(12).to_string(index=False) if not intra_trades.empty else "none")
    print("\n10-minute fresh-guard pullback-wait trades:")
    print(pullback_trades.tail(12).to_string(index=False) if not pullback_trades.empty else "none")
    print("\n10-minute fresh-guard next-day-cooldown trades:")
    print(cooldown_trades.tail(12).to_string(index=False) if not cooldown_trades.empty else "none")
    print(f"\nWrote {OUT_DIR / 'recent_intraday_rule_summary.csv'}")


if __name__ == "__main__":
    main()
