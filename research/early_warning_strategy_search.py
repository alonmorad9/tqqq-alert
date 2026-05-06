#!/usr/bin/env python3
"""Search early-warning TQQQ exits against the current swing strategy.

This is a research-only script. It does not read or write live bot state.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests


START_CASH = 1.0
CACHE_DIR = Path("/private/tmp/tqqq_early_warning_cache")
OUT_DIR = Path("research/out")


@dataclass(frozen=True)
class Strategy:
    name: str
    risk_threshold: int | None = None
    vix_level: float | None = None
    vix_spike: float | None = None
    qqq_ema: str | None = None
    tqqq_sma: str | None = None
    rsi_fall: float | None = None
    reentry_mode: str = "current"


def fetch_yahoo_chart(ticker: str) -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = ticker.lower().replace("^", "")
    cache_path = CACHE_DIR / f"{safe}_history.json"
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


def load_prices(ticker: str, prefix: str = "") -> pd.DataFrame:
    payload = fetch_yahoo_chart(ticker)
    result = payload["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    adjclose = result["indicators"].get("adjclose", [{}])[0].get("adjclose")
    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(result["timestamp"], unit="s")
            .tz_localize("UTC")
            .tz_convert("America/New_York")
            .date,
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

    df = df[["Date", "Open", "High", "Low", "Close", "Volume"]].set_index("Date")
    add_indicators(df)
    if prefix:
        df = df.add_prefix(prefix)
    return df


def add_indicators(df: pd.DataFrame) -> None:
    df["SMA20"] = df["Close"].rolling(20).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()
    df["EMA10"] = df["Close"].ewm(span=10, adjust=False).mean()
    df["EMA21"] = df["Close"].ewm(span=21, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["RSI14"] = calculate_rsi(df["Close"], 14)
    df["RET5"] = df["Close"].pct_change(5)
    df["RET10"] = df["Close"].pct_change(10)
    df["RET20"] = df["Close"].pct_change(20)


def calculate_rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def prepare_data() -> pd.DataFrame:
    tqqq = load_prices("TQQQ")
    qqq = load_prices("QQQ", "QQQ_")
    vix = load_prices("^VIX", "VIX_")
    df = tqqq.join(qqq, how="inner").join(vix, how="inner")
    df["VIX_RET5"] = df["VIX_Close"].pct_change(5)
    df["VIX_SMA20"] = df["VIX_Close"].rolling(20).mean()
    return df.dropna()


def max_drawdown(values: list[float]) -> float:
    series = pd.Series(values)
    peaks = series.cummax()
    return float((series / peaks - 1).min())


def cagr(final_value: float, years: float) -> float:
    return final_value ** (1 / years) - 1


def risk_score(row: pd.Series, prev: pd.Series, strategy: Strategy) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if strategy.vix_level and row["VIX_Close"] >= strategy.vix_level:
        score += 1
        reasons.append(f"VIX>={strategy.vix_level:g}")
    if strategy.vix_spike and row["VIX_RET5"] >= strategy.vix_spike:
        score += 1
        reasons.append(f"VIX 5d spike>={strategy.vix_spike:.0%}")
    if strategy.qqq_ema and row["QQQ_Close"] < row[f"QQQ_{strategy.qqq_ema}"]:
        score += 1
        reasons.append(f"QQQ<{strategy.qqq_ema}")
    if strategy.tqqq_sma and row["Close"] < row[strategy.tqqq_sma]:
        score += 1
        reasons.append(f"TQQQ<{strategy.tqqq_sma}")
    if strategy.rsi_fall and prev["RSI14"] >= strategy.rsi_fall and row["RSI14"] < prev["RSI14"]:
        score += 1
        reasons.append(f"RSI fell from >= {strategy.rsi_fall:g}")

    return score, reasons


def run_strategy(df: pd.DataFrame, strategy: Strategy) -> dict:
    cash = START_CASH
    shares = 0.0
    avg_cost = None
    open_pos = False
    highest_high = None
    waiting_for_pullback = False
    last_profit_sell_price = None
    profit_exit_i = None
    early_exit_i = None
    early_exit_price = None
    values = []
    trades = []

    rows = list(df.iterrows())
    for i, (date, row) in enumerate(rows):
        if i == 0:
            values.append(cash)
            continue

        prev_date, prev = rows[i - 1]
        price = float(row["Close"])
        value = cash + shares * price
        values.append(value)

        cross_up = prev["Close"] <= prev["SMA200"] and row["Close"] > row["SMA200"]
        cross_down = prev["Close"] >= prev["SMA200"] and row["Close"] < row["SMA200"]

        if open_pos:
            highest_high = max(float(highest_high), float(row["High"]))
            ratchet_stop = highest_high * 0.75
            profit_hit = avg_cost is not None and price >= avg_cost * 1.20
            stop_hit = price < ratchet_stop
            score, reasons = risk_score(row, prev, strategy)
            early_warning_hit = strategy.risk_threshold is not None and score >= strategy.risk_threshold

            if cross_down or stop_hit or profit_hit or early_warning_hit:
                reason = "sma200" if cross_down else "stop" if stop_hit else "profit20" if profit_hit else "early:" + ",".join(reasons)
                cash += shares * price
                trades.append((date, "sell_all", price, reason, value))
                shares = 0.0
                avg_cost = None
                open_pos = False
                highest_high = None
                if profit_hit:
                    waiting_for_pullback = True
                    last_profit_sell_price = price
                    profit_exit_i = i
                elif early_warning_hit:
                    early_exit_i = i
                    early_exit_price = price

        if not open_pos:
            should_enter = False
            reason = None

            if waiting_for_pullback and last_profit_sell_price is not None:
                pullback_ready = price <= last_profit_sell_price * 0.925
                timeout_ready = profit_exit_i is not None and i - profit_exit_i >= 20 and price > row["SMA200"]
                if pullback_ready or timeout_ready:
                    should_enter = True
                    reason = "profit_reentry_pullback" if pullback_ready else "profit_reentry_timeout"
                    waiting_for_pullback = False
                    last_profit_sell_price = None
                    profit_exit_i = None
            elif early_exit_i is not None:
                if strategy.reentry_mode == "current":
                    should_enter = price > row["SMA200"] and row["Close"] > row["SMA20"]
                    reason = "early_reentry_sma20"
                elif strategy.reentry_mode == "pullback":
                    should_enter = early_exit_price is not None and price <= early_exit_price * 0.925 and price > row["SMA200"]
                    reason = "early_reentry_pullback"
                elif strategy.reentry_mode == "timeout":
                    should_enter = price > row["SMA200"] and i - early_exit_i >= 10
                    reason = "early_reentry_timeout"
                else:
                    raise ValueError(strategy.reentry_mode)

                if should_enter:
                    early_exit_i = None
                    early_exit_price = None
            elif cross_up or (not trades and price > row["SMA200"]):
                should_enter = True
                reason = "sma200_cross_up" if cross_up else "initial_above_sma200"

            if should_enter and cash > 0:
                shares = cash / price
                cash = 0.0
                avg_cost = price
                open_pos = True
                highest_high = float(row["High"])
                trades.append((date, "buy", price, reason, value))

    final = values[-1]
    years = (pd.to_datetime(df.index[-1]) - pd.to_datetime(df.index[0])).days / 365.25
    exits = sum(1 for trade in trades if trade[1] == "sell_all")
    early_exits = sum(1 for trade in trades if str(trade[3]).startswith("early:"))
    return {
        "name": strategy.name,
        "final": final,
        "cagr": cagr(final, years),
        "maxdd": max_drawdown(values),
        "trades": len(trades),
        "exits": exits,
        "early_exits": early_exits,
    }


def strategy_grid() -> list[Strategy]:
    strategies = [Strategy("Current swing strategy")]
    configs = itertools.product(
        [2, 3],
        [25, 30, 35, None],
        [0.25, 0.50, None],
        ["EMA21", "EMA50", None],
        ["SMA20", "SMA50", None],
        [70, 75, 80, None],
        ["current", "pullback", "timeout"],
    )
    for threshold, vix_level, vix_spike, qqq_ema, tqqq_sma, rsi_fall, reentry_mode in configs:
        active = [vix_level, vix_spike, qqq_ema, tqqq_sma, rsi_fall]
        if sum(x is not None for x in active) < threshold:
            continue
        name = (
            f"Early risk >= {threshold}: "
            f"VIX {vix_level or '-'}, spike {vix_spike or '-'}, "
            f"QQQ {qqq_ema or '-'}, TQQQ {tqqq_sma or '-'}, "
            f"RSI {rsi_fall or '-'}, reentry {reentry_mode}"
        )
        strategies.append(
            Strategy(
                name=name,
                risk_threshold=threshold,
                vix_level=vix_level,
                vix_spike=vix_spike,
                qqq_ema=qqq_ema,
                tqqq_sma=tqqq_sma,
                rsi_fall=rsi_fall,
                reentry_mode=reentry_mode,
            )
        )
    return strategies


def main() -> None:
    try:
        df = prepare_data()
    except requests.RequestException as exc:
        print("Could not download historical market data.")
        print("Needed tickers: TQQQ, QQQ, ^VIX from Yahoo Finance chart API.")
        print(f"Reason: {exc}")
        print("\nTry again from a network that can reach query2.finance.yahoo.com.")
        print("No live bot files or position state were changed.")
        raise SystemExit(2) from exc

    results = pd.DataFrame(run_strategy(df, strategy) for strategy in strategy_grid())
    results["calmar"] = results["cagr"] / results["maxdd"].abs()
    results = results.sort_values(["final", "calmar"], ascending=False)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results.to_csv(OUT_DIR / "early_warning_strategy_results.csv", index=False)

    display = results.head(20).copy()
    for col in ["cagr", "maxdd"]:
        display[col] = display[col].map(lambda x: f"{x:.1%}")
    display["final"] = display["final"].map(lambda x: f"{x:.1f}x")
    display["calmar"] = display["calmar"].map(lambda x: f"{x:.2f}")
    print(f"DATA {df.index[0]} -> {df.index[-1]} rows={len(df)}")
    print(display.to_string(index=False))
    print(f"\nWrote {OUT_DIR / 'early_warning_strategy_results.csv'}")


if __name__ == "__main__":
    main()
