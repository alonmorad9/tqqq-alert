#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests


TICKER = "TQQQ"
START_CASH = 1.0
PROFIT_STEP = 1.25
PROFIT_SELL_FRACTION = 0.90


def fetch_yahoo_chart(ticker):
    cache_path = Path(f"/private/tmp/{ticker.lower()}_history.json")
    if cache_path.exists():
        return json.loads(cache_path.read_text())

    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {
        "period1": 1262304000,
        "period2": 4102444800,
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    }
    response = requests.get(url, params=params, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    payload = response.json()
    cache_path.write_text(json.dumps(payload))
    return payload


def load_prices(ticker):
    payload = fetch_yahoo_chart(ticker)
    result = payload["chart"]["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    adjclose = result["indicators"].get("adjclose", [{}])[0].get("adjclose")

    df = pd.DataFrame({
        "Date": pd.to_datetime(timestamps, unit="s").tz_localize("UTC").tz_convert("America/New_York").date,
        "Open": quote["open"],
        "High": quote["high"],
        "Low": quote["low"],
        "Close": quote["close"],
        "AdjClose": adjclose or quote["close"],
        "Volume": quote["volume"],
    }).dropna()

    factor = df["AdjClose"] / df["Close"]
    for col in ["Open", "High", "Low", "Close"]:
        df[col] = df[col] * factor

    df = df[["Date", "Open", "High", "Low", "Close", "Volume"]].set_index("Date")
    df["SMA20"] = df["Close"].rolling(20).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA100"] = df["Close"].rolling(100).mean()
    df["SMA150"] = df["Close"].rolling(150).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()
    df["EMA9"] = df["Close"].ewm(span=9, adjust=False).mean()
    df["EMA21"] = df["Close"].ewm(span=21, adjust=False).mean()
    df["EMA100"] = df["Close"].ewm(span=100, adjust=False).mean()
    df["EMA150"] = df["Close"].ewm(span=150, adjust=False).mean()
    df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()

    prev_close = df["Close"].shift(1)
    true_range = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["ATR14"] = true_range.rolling(14).mean()
    df["RSI14"] = calculate_rsi(df["Close"], 14)
    return df.dropna()


def calculate_rsi(close, window):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def max_drawdown(values):
    series = pd.Series(values)
    peaks = series.cummax()
    return float((series / peaks - 1).min())


def cagr(final_value, years):
    return final_value ** (1 / years) - 1


def stop_value(strategy, row, state, prev_stop=None):
    if strategy["kind"] == "none":
        return None

    if strategy["kind"] == "rolling_pct":
        lookback = strategy["lookback"]
        pct = strategy["pct"]
        recent_high = state["data_until_now"]["High"].tail(lookback).max()
        return recent_high * (1 - pct)

    if strategy["kind"] == "ratchet_pct":
        pct = strategy["pct"]
        candidate = state["highest_high_since_entry"] * (1 - pct)
        return max(prev_stop or candidate, candidate)

    if strategy["kind"] == "atr_low":
        mult = strategy["mult"]
        candidate = row["Low"] - mult * row["ATR14"]
        return max(prev_stop or candidate, candidate)

    if strategy["kind"] == "atr_close":
        mult = strategy["mult"]
        candidate = row["Close"] - mult * row["ATR14"]
        return max(prev_stop or candidate, candidate)

    if strategy["kind"] == "atr_low_raw":
        mult = strategy["mult"]
        return row["Low"] - mult * row["ATR14"]

    if strategy["kind"] == "atr_high":
        mult = strategy["mult"]
        candidate = state["highest_high_since_entry"] - mult * row["ATR14"]
        return max(prev_stop or candidate, candidate)

    if strategy["kind"] == "hybrid":
        pct_candidate = state["highest_high_since_entry"] * (1 - strategy["pct"])
        atr_candidate = state["highest_high_since_entry"] - strategy["mult"] * row["ATR14"]
        candidate = max(pct_candidate, atr_candidate)
        return max(prev_stop or candidate, candidate)

    raise ValueError(strategy["kind"])


def run_strategy(df, strategy):
    cash = START_CASH
    shares = 0.0
    avg_cost = None
    open_pos = False
    stop = None
    highest_high_since_entry = None
    values = []
    trades = []
    profit_step = strategy.get("profit_step", PROFIT_STEP)
    profit_sell_fraction = strategy.get("profit_sell_fraction", PROFIT_SELL_FRACTION)
    next_profit_multiple = 1.0 + profit_step if profit_step else 2.0
    entry_mode = strategy.get("entry_mode", "cross_only")
    trend_col = strategy.get("trend_col", "SMA200")
    vix_exit = strategy.get("vix_exit")
    vix_entry = strategy.get("vix_entry", vix_exit)
    stop_trigger = strategy.get("stop_trigger", "cross")

    rows = list(df.iterrows())
    for i, (date, row) in enumerate(rows):
        if i == 0:
            values.append(cash)
            continue

        prev = rows[i - 1][1]
        price = row["Close"]
        value = cash + shares * price
        values.append(value)

        crossed_above_trend = prev["Close"] <= prev[trend_col] and row["Close"] > row[trend_col]
        crossed_below_trend = prev["Close"] >= prev[trend_col] and row["Close"] < row[trend_col]
        vix_risk = vix_exit is not None and row.get("VIX", 0) > vix_exit
        vix_allows_entry = vix_entry is None or row.get("VIX", 0) <= vix_entry

        if open_pos:
            highest_high_since_entry = max(highest_high_since_entry, row["High"])
            state = {
                "highest_high_since_entry": highest_high_since_entry,
                "data_until_now": df.iloc[: i + 1],
            }
            stop = stop_value(strategy, row, state, stop)
            if stop is None:
                hit_stop = False
            elif stop_trigger == "below":
                hit_stop = row["Close"] < stop
            elif stop_trigger == "cross":
                hit_stop = prev["Close"] >= stop and row["Close"] < stop
            else:
                raise ValueError(stop_trigger)
            hit_profit = (
                profit_step
                and profit_sell_fraction
                and avg_cost
                and row["Close"] >= avg_cost * next_profit_multiple
            )

            if crossed_below_trend or hit_stop or vix_risk:
                reason = "trend" if crossed_below_trend else "vix" if vix_risk else "stop"
                cash += shares * price
                trades.append((date, reason, "sell_all", price, shares, value))
                shares = 0.0
                avg_cost = None
                open_pos = False
                next_profit_multiple = 1.0 + profit_step if profit_step else 2.0
                stop = None
                highest_high_since_entry = None
            elif hit_profit:
                sell_shares = shares * profit_sell_fraction
                cash += sell_shares * price
                shares -= sell_shares
                trades.append((date, "profit", "trim", price, sell_shares, value))
                next_profit_multiple += profit_step

        should_enter = crossed_above_trend
        if entry_mode == "above_sma":
            should_enter = row["Close"] > row[trend_col]
        elif entry_mode != "cross_only":
            raise ValueError(entry_mode)

        if not open_pos and should_enter and vix_allows_entry:
            shares = cash / price
            avg_cost = price
            cash = 0.0
            open_pos = True
            next_profit_multiple = 1.0 + profit_step if profit_step else 2.0
            highest_high_since_entry = row["High"]
            state = {
                "highest_high_since_entry": highest_high_since_entry,
                "data_until_now": df.iloc[: i + 1],
            }
            stop = stop_value(strategy, row, state, None)
            trades.append((date, "entry", "buy", price, shares, value))

    final_value = cash + shares * df["Close"].iloc[-1]
    years = (pd.Timestamp(df.index[-1]) - pd.Timestamp(df.index[0])).days / 365.25
    sell_all_count = sum(1 for t in trades if t[2] == "sell_all")
    trim_count = sum(1 for t in trades if t[2] == "trim")
    return {
        "name": strategy["name"],
        "group": strategy.get("group", "stop"),
        "final": final_value,
        "cagr": cagr(final_value, years),
        "maxdd": max_drawdown(values),
        "calmar": cagr(final_value, years) / abs(max_drawdown(values)),
        "trades": len(trades),
        "exits": sell_all_count,
        "trims": trim_count,
    }


def run_sniper_strategy(df, strategy):
    cash = START_CASH
    shares = 0.0
    avg_cost = None
    open_pos = False
    stop = None
    highest_high_since_entry = None
    values = []
    trades = []
    trim_mode = strategy.get("trim_mode", "daily")
    trim_armed = True
    atr_mult = strategy.get("atr_mult", 3.0)
    trim_rsi = strategy.get("trim_rsi", 80)
    entry_rsi_max = strategy.get("entry_rsi_max", 70)
    trim_fraction = strategy.get("trim_fraction", 0.20)

    rows = list(df.iterrows())
    for i, (date, row) in enumerate(rows):
        if i == 0:
            values.append(cash)
            continue

        prev = rows[i - 1][1]
        price = row["Close"]
        value = cash + shares * price
        values.append(value)

        long_trend = row["QQQ_Close"] > row["QQQ_SMA200"]
        momentum_up = row["QQQ_EMA9"] > row["QQQ_EMA21"]
        momentum_cross_down = prev["QQQ_EMA9"] >= prev["QQQ_EMA21"] and row["QQQ_EMA9"] < row["QQQ_EMA21"]
        qqq_overbought = row["QQQ_RSI14"] > trim_rsi
        qqq_crossed_overbought = prev["QQQ_RSI14"] <= trim_rsi and row["QQQ_RSI14"] > trim_rsi

        if open_pos:
            highest_high_since_entry = max(highest_high_since_entry, row["High"])
            candidate_stop = highest_high_since_entry - atr_mult * row["ATR14"]
            stop = max(stop or candidate_stop, candidate_stop)
            hit_stop = row["Close"] < stop

            if momentum_cross_down or not long_trend or hit_stop:
                reason = "momentum" if momentum_cross_down else "trend" if not long_trend else "stop"
                cash += shares * price
                trades.append((date, reason, "sell_all", price, shares, value))
                shares = 0.0
                avg_cost = None
                open_pos = False
                stop = None
                highest_high_since_entry = None
                trim_armed = True
            else:
                in_profit = avg_cost is not None and price > avg_cost
                should_trim = qqq_overbought if trim_mode == "daily" else qqq_crossed_overbought and trim_armed
                if qqq_overbought is False:
                    trim_armed = True
                if in_profit and should_trim:
                    sell_shares = shares * trim_fraction
                    cash += sell_shares * price
                    shares -= sell_shares
                    trades.append((date, "rsi", "trim", price, sell_shares, value))
                    if trim_mode != "daily":
                        trim_armed = False

        if not open_pos and long_trend and momentum_up and row["QQQ_RSI14"] < entry_rsi_max:
            shares = cash / price
            avg_cost = price
            cash = 0.0
            open_pos = True
            highest_high_since_entry = row["High"]
            stop = highest_high_since_entry - atr_mult * row["ATR14"]
            trim_armed = row["QQQ_RSI14"] <= trim_rsi
            trades.append((date, "entry", "buy", price, shares, value))

    final_value = cash + shares * df["Close"].iloc[-1]
    years = (pd.Timestamp(df.index[-1]) - pd.Timestamp(df.index[0])).days / 365.25
    sell_all_count = sum(1 for t in trades if t[2] == "sell_all")
    trim_count = sum(1 for t in trades if t[2] == "trim")
    return {
        "name": strategy["name"],
        "group": strategy.get("group", "sniper"),
        "final": final_value,
        "cagr": cagr(final_value, years),
        "maxdd": max_drawdown(values),
        "calmar": cagr(final_value, years) / abs(max_drawdown(values)),
        "trades": len(trades),
        "exits": sell_all_count,
        "trims": trim_count,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", default=TICKER)
    args = parser.parse_args()

    df = load_prices(args.ticker)
    qqq = load_prices("QQQ")[["Close", "SMA200", "EMA9", "EMA21", "RSI14"]].add_prefix("QQQ_")
    vix = load_prices("^VIX")[["Close"]].rename(columns={"Close": "VIX"})
    df = df.join(qqq, how="left").join(vix, how="left").ffill().dropna()
    old_stop = {"kind": "rolling_pct", "lookback": 30, "pct": 0.35}
    live_stop = {"kind": "ratchet_pct", "pct": 0.25, "stop_trigger": "below"}
    stop_tests = [
        {"name": "SMA200 only, no stop", "kind": "none"},
        {"name": "Old rolling 30d high -35%", **old_stop},
        {"name": "Live ratchet high since entry -25%", **live_stop},
        {"name": "Ratchet high since entry -35%", "kind": "ratchet_pct", "pct": 0.35},
        {"name": "Ratchet high since entry -30%", "kind": "ratchet_pct", "pct": 0.30},
        {"name": "Ratchet high since entry -25%", "kind": "ratchet_pct", "pct": 0.25},
        {"name": "Ratchet high since entry -20%", "kind": "ratchet_pct", "pct": 0.20},
        {"name": "Raw daily low -1x ATR14", "kind": "atr_low_raw", "mult": 1.0},
        {"name": "Raw daily low -2x ATR14", "kind": "atr_low_raw", "mult": 2.0},
        {"name": "Ratchet daily low -1x ATR14", "kind": "atr_low", "mult": 1.0},
        {"name": "Ratchet daily low -2x ATR14", "kind": "atr_low", "mult": 2.0},
        {"name": "Ratchet daily low -3x ATR14", "kind": "atr_low", "mult": 3.0},
        {"name": "Ratchet daily low -4x ATR14", "kind": "atr_low", "mult": 4.0},
        {"name": "Ratchet daily low -5x ATR14", "kind": "atr_low", "mult": 5.0},
        {"name": "Ratchet high since entry -2x ATR14", "kind": "atr_high", "mult": 2.0},
        {"name": "Ratchet high since entry -3x ATR14", "kind": "atr_high", "mult": 3.0},
        {"name": "Ratchet high since entry -4x ATR14", "kind": "atr_high", "mult": 4.0},
        {"name": "Ratchet high since entry -5x ATR14", "kind": "atr_high", "mult": 5.0},
        {"name": "Hybrid max(-35%, high-4xATR)", "kind": "hybrid", "pct": 0.35, "mult": 4.0},
        {"name": "Hybrid max(-30%, high-4xATR)", "kind": "hybrid", "pct": 0.30, "mult": 4.0},
        {"name": "Hybrid max(-25%, high-4xATR)", "kind": "hybrid", "pct": 0.25, "mult": 4.0},
    ]

    profit_tests = [
        {"name": "Live stop, no profit taking", **live_stop, "profit_step": None, "profit_sell_fraction": 0.0, "group": "profit"},
        {"name": "Live stop, +25% sell 25%", **live_stop, "profit_step": 0.25, "profit_sell_fraction": 0.25, "group": "profit"},
        {"name": "Live stop, +25% sell 33%", **live_stop, "profit_step": 0.25, "profit_sell_fraction": 0.33, "group": "profit"},
        {"name": "Live stop, +50% sell 25%", **live_stop, "profit_step": 0.5, "profit_sell_fraction": 0.25, "group": "profit"},
        {"name": "Live stop, +75% sell 25%", **live_stop, "profit_step": 0.75, "profit_sell_fraction": 0.25, "group": "profit"},
        {"name": "Live stop, +100% sell 25%", **live_stop, "profit_step": 1.0, "profit_sell_fraction": 0.25, "group": "profit"},
        {"name": "Live stop, +100% sell 50%", **live_stop, "profit_step": 1.0, "profit_sell_fraction": 0.5, "group": "profit"},
        {"name": "Live stop, +150% sell 50%", **live_stop, "profit_step": 1.5, "profit_sell_fraction": 0.5, "group": "profit"},
        {"name": "Live stop, +200% sell 50%", **live_stop, "profit_step": 2.0, "profit_sell_fraction": 0.5, "group": "profit"},
    ]

    entry_tests = [
        {"name": "Live re-entry: fresh SMA200 cross only", **live_stop, "entry_mode": "cross_only", "group": "entry"},
        {"name": "Aggressive re-entry: any close above SMA200", **live_stop, "entry_mode": "above_sma", "group": "entry"},
    ]

    trend_tests = [
        {"name": "SMA200 trend, live stop", **live_stop, "trend_col": "SMA200", "group": "trend"},
        {"name": "SMA150 trend, live stop", **live_stop, "trend_col": "SMA150", "group": "trend"},
        {"name": "SMA100 trend, live stop", **live_stop, "trend_col": "SMA100", "group": "trend"},
        {"name": "EMA200 trend, live stop", **live_stop, "trend_col": "EMA200", "group": "trend"},
        {"name": "EMA150 trend, live stop", **live_stop, "trend_col": "EMA150", "group": "trend"},
        {"name": "EMA100 trend, live stop", **live_stop, "trend_col": "EMA100", "group": "trend"},
    ]

    vix_tests = [
        {"name": "SMA200 + VIX exit>30 re-enter<=25", **live_stop, "entry_mode": "above_sma", "vix_exit": 30, "vix_entry": 25, "group": "vix"},
        {"name": "SMA200 + VIX exit>35 re-enter<=30", **live_stop, "entry_mode": "above_sma", "vix_exit": 35, "vix_entry": 30, "group": "vix"},
        {"name": "SMA200 + VIX exit>40 re-enter<=30", **live_stop, "entry_mode": "above_sma", "vix_exit": 40, "vix_entry": 30, "group": "vix"},
        {"name": "SMA200 + VIX exit>30 re-enter<=30", **live_stop, "entry_mode": "above_sma", "vix_exit": 30, "vix_entry": 30, "group": "vix"},
    ]

    sniper_tests = [
        {"name": "Sniper as proposed: ATR3, RSI80 daily trims", "atr_mult": 3.0, "trim_mode": "daily", "group": "sniper"},
        {"name": "Sniper ATR3, RSI80 one trim per RSI wave", "atr_mult": 3.0, "trim_mode": "cross", "group": "sniper"},
        {"name": "Sniper ATR8, RSI80 one trim per RSI wave", "atr_mult": 8.0, "trim_mode": "cross", "group": "sniper"},
    ] + [
        {
            "name": f"Sniper optimized ATR{mult:g}, RSI80 wave trim",
            "atr_mult": mult,
            "trim_mode": "cross",
            "group": "sniper",
        }
        for mult in np.arange(2.0, 10.5, 0.5)
    ]

    optimized_tests = [
        {
            "name": f"Exact low -{mult:g}x ATR14, close below stop",
            "kind": "atr_low",
            "mult": mult,
            "stop_trigger": "below",
            "group": "optimized",
        }
        for mult in np.arange(1.0, 8.5, 0.5)
    ] + [
        {
            "name": f"Close -{mult:g}x ATR14, close below stop",
            "kind": "atr_close",
            "mult": mult,
            "stop_trigger": "below",
            "group": "optimized",
        }
        for mult in np.arange(1.0, 8.5, 0.5)
    ] + [
        {
            "name": f"Highest high -{mult:g}x ATR14, close below stop",
            "kind": "atr_high",
            "mult": mult,
            "stop_trigger": "below",
            "group": "optimized",
        }
        for mult in np.arange(1.0, 8.5, 0.5)
    ] + [
        {
            "name": f"Highest high -{pct:.0%}, close below stop",
            "kind": "ratchet_pct",
            "pct": pct,
            "stop_trigger": "below",
            "group": "optimized",
        }
        for pct in np.arange(0.15, 0.405, 0.025)
    ]

    strategies = (
        [{**s, "group": "stop"} for s in stop_tests]
        + profit_tests
        + entry_tests
        + trend_tests
        + vix_tests
        + optimized_tests
    )

    results = [run_strategy(df, s) for s in strategies]
    results.extend(run_sniper_strategy(df, s) for s in sniper_tests)
    out = pd.DataFrame(results).sort_values(["final", "calmar"], ascending=False)
    display = out.copy()
    display["final"] = display["final"].map(lambda x: f"{x:.1f}x")
    display["cagr"] = display["cagr"].map(lambda x: f"{x:.1%}")
    display["maxdd"] = display["maxdd"].map(lambda x: f"{x:.1%}")
    display["calmar"] = display["calmar"].map(lambda x: f"{x:.2f}")

    print(f"DATA {df.index[0]} -> {df.index[-1]} rows={len(df)}")
    for group, title in [
        ("entry", "Re-entry rule comparison"),
        ("trend", "Trend-filter comparison"),
        ("vix", "VIX safety-switch comparison"),
        ("profit", "Profit-taking comparison"),
        ("stop", "Trailing-stop comparison"),
        ("sniper", "Adaptive Nasdaq-100 Leveraged Sniper comparison"),
        ("optimized", "Expanded stop optimization"),
    ]:
        group_display = display[display["group"] == group].drop(columns=["group"])
        if group == "optimized":
            group_display = group_display.head(20)
        print(f"\n{title} - sorted by ending value:")
        print(group_display.to_string(index=False))

    risk = out.sort_values(["calmar", "final"], ascending=False).head(10).copy()
    risk["final"] = risk["final"].map(lambda x: f"{x:.1f}x")
    risk["cagr"] = risk["cagr"].map(lambda x: f"{x:.1%}")
    risk["maxdd"] = risk["maxdd"].map(lambda x: f"{x:.1%}")
    risk["calmar"] = risk["calmar"].map(lambda x: f"{x:.2f}")
    print("\nTop overall risk-adjusted options:")
    print(risk.drop(columns=["group"]).to_string(index=False))


if __name__ == "__main__":
    main()
