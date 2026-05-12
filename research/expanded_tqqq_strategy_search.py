#!/usr/bin/env python3
"""Research-only search for TQQQ strategy ideas beyond the live bot.

This script does not read or write live bot state. It compares the current
selected strategy with practical variations:

- stretched re-entry guards
- different profit/re-entry settings
- tighter/looser ratchet stops
- RSI cooling profit exits
- QQQ/TQQQ momentum exits
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

import early_warning_strategy_search as base


OUT_DIR = Path("research/out")


@dataclass(frozen=True)
class Variant:
    name: str
    profit_target: float = 0.20
    reentry_drop: float = 0.075
    timeout_days: int = 20
    ratchet_pct: float = 0.25
    use_early_warning: bool = True
    early_threshold: int = 3
    entry_rsi_max: float | None = None
    early_reentry_rsi_max: float | None = None
    rsi_take_profit: float | None = None
    min_profit_for_rsi_exit: float = 0.0
    qqq_ema_exit: str | None = None
    tqqq_sma_exit: str | None = None
    require_sma20_on_pullback_reentry: bool = False


def early_score(row: pd.Series, prev: pd.Series) -> int:
    score = 0
    if row["VIX_Close"] >= 25:
        score += 1
    if row["VIX_RET5"] >= 0.25:
        score += 1
    if row["QQQ_Close"] < row["QQQ_EMA21"]:
        score += 1
    if row["Close"] < row["SMA50"]:
        score += 1
    if prev["RSI14"] >= 70 and row["RSI14"] < prev["RSI14"]:
        score += 1
    return score


def max_drawdown(values: list[float]) -> float:
    series = pd.Series(values)
    return float((series / series.cummax() - 1).min())


def cagr(final_value: float, years: float) -> float:
    return final_value ** (1 / years) - 1


def run_variant(df: pd.DataFrame, variant: Variant) -> dict:
    cash = 1.0
    shares = 0.0
    avg_cost = None
    open_pos = False
    highest_high = None
    waiting_for_profit_reentry = False
    last_profit_sell_price = None
    profit_exit_i = None
    early_exit_i = None
    values = []
    trades = []

    rows = list(df.iterrows())
    for i, (date, row) in enumerate(rows):
        if i == 0:
            values.append(cash)
            continue

        _, prev = rows[i - 1]
        price = float(row["Close"])
        values.append(cash + shares * price)

        cross_up = prev["Close"] <= prev["SMA200"] and row["Close"] > row["SMA200"]
        cross_down = prev["Close"] >= prev["SMA200"] and row["Close"] < row["SMA200"]

        if open_pos:
            highest_high = max(float(highest_high), float(row["High"]))
            ratchet_stop = highest_high * (1 - variant.ratchet_pct)
            profit_hit = avg_cost is not None and price >= avg_cost * (1 + variant.profit_target)
            stop_hit = price < ratchet_stop
            early_hit = variant.use_early_warning and early_score(row, prev) >= variant.early_threshold

            rsi_profit_hit = False
            if variant.rsi_take_profit is not None and avg_cost is not None:
                rsi_profit_hit = (
                    price >= avg_cost * (1 + variant.min_profit_for_rsi_exit)
                    and row["RSI14"] >= variant.rsi_take_profit
                    and row["RSI14"] < prev["RSI14"]
                )

            qqq_ema_hit = variant.qqq_ema_exit is not None and row["QQQ_Close"] < row[f"QQQ_{variant.qqq_ema_exit}"]
            tqqq_sma_hit = variant.tqqq_sma_exit is not None and row["Close"] < row[variant.tqqq_sma_exit]

            if cross_down or stop_hit or profit_hit or early_hit or rsi_profit_hit or qqq_ema_hit or tqqq_sma_hit:
                if cross_down:
                    reason = "sma200"
                elif stop_hit:
                    reason = "ratchet_stop"
                elif profit_hit:
                    reason = "profit_target"
                elif early_hit:
                    reason = "early_warning"
                elif rsi_profit_hit:
                    reason = "rsi_profit"
                elif qqq_ema_hit:
                    reason = f"qqq_below_{variant.qqq_ema_exit}"
                else:
                    reason = f"tqqq_below_{variant.tqqq_sma_exit}"

                cash += shares * price
                shares = 0.0
                avg_cost = None
                open_pos = False
                highest_high = None
                trades.append((date, "sell", price, reason))

                if profit_hit or rsi_profit_hit:
                    waiting_for_profit_reentry = True
                    last_profit_sell_price = price
                    profit_exit_i = i
                elif early_hit or qqq_ema_hit or tqqq_sma_hit:
                    early_exit_i = i

        if not open_pos:
            should_enter = False
            reason = None

            if waiting_for_profit_reentry and last_profit_sell_price is not None:
                pullback_ready = price <= last_profit_sell_price * (1 - variant.reentry_drop) and price > row["SMA200"]
                if variant.require_sma20_on_pullback_reentry:
                    pullback_ready = pullback_ready and price > row["SMA20"]
                timeout_ready = profit_exit_i is not None and i - profit_exit_i >= variant.timeout_days and price > row["SMA200"]
                if pullback_ready or timeout_ready:
                    should_enter = True
                    reason = "profit_pullback" if pullback_ready else "profit_timeout"
                    waiting_for_profit_reentry = False
                    last_profit_sell_price = None
                    profit_exit_i = None
            elif early_exit_i is not None:
                should_enter = price > row["SMA200"] and price > row["SMA20"]
                if variant.early_reentry_rsi_max is not None:
                    should_enter = should_enter and row["RSI14"] <= variant.early_reentry_rsi_max
                reason = "early_reentry"
                if should_enter:
                    early_exit_i = None
            elif cross_up or (not trades and price > row["SMA200"]):
                should_enter = True
                reason = "sma200_cross_up" if cross_up else "initial_above_sma200"

            if should_enter and cash > 0:
                if variant.entry_rsi_max is not None and row["RSI14"] > variant.entry_rsi_max:
                    continue
                shares = cash / price
                cash = 0.0
                avg_cost = price
                open_pos = True
                highest_high = float(row["High"])
                trades.append((date, "buy", price, reason))

    final = values[-1]
    years = (pd.to_datetime(df.index[-1]) - pd.to_datetime(df.index[0])).days / 365.25
    exits = sum(1 for trade in trades if trade[1] == "sell")
    return {
        "name": variant.name,
        "final": final,
        "cagr": cagr(final, years),
        "maxdd": max_drawdown(values),
        "trades": len(trades),
        "exits": exits,
        "calmar": cagr(final, years) / abs(max_drawdown(values)),
    }


def variant_grid() -> list[Variant]:
    variants = [Variant("LIVE selected: +20% profit, -7.5% re-entry, 25% ratchet, early 3/5")]

    for profit_target, reentry_drop, timeout_days in itertools.product(
        [0.10, 0.15, 0.20, 0.25, 0.30, 0.40],
        [0.05, 0.075, 0.10, 0.125, 0.15],
        [10, 20, 30, 40],
    ):
        variants.append(
            Variant(
                f"Profit {profit_target:.0%}, re-buy -{reentry_drop:.1%}, timeout {timeout_days}d",
                profit_target=profit_target,
                reentry_drop=reentry_drop,
                timeout_days=timeout_days,
            )
        )

    for ratchet_pct in [0.15, 0.20, 0.25, 0.30, 0.35]:
        variants.append(Variant(f"Ratchet {ratchet_pct:.0%} with live early-warning", ratchet_pct=ratchet_pct))

    for rsi, min_profit, reentry_drop in itertools.product([75, 80, 85, 90], [0.0, 0.05, 0.10], [0.05, 0.075, 0.10]):
        variants.append(
            Variant(
                f"RSI {rsi} cooling profit exit, min profit {min_profit:.0%}, re-buy -{reentry_drop:.1%}",
                rsi_take_profit=rsi,
                min_profit_for_rsi_exit=min_profit,
                reentry_drop=reentry_drop,
            )
        )

    for qqq_ema_exit in ["EMA10", "EMA21", "EMA50"]:
        variants.append(Variant(f"Exit when QQQ below {qqq_ema_exit}", qqq_ema_exit=qqq_ema_exit))
    for tqqq_sma_exit in ["SMA20", "SMA50"]:
        variants.append(Variant(f"Exit when TQQQ below {tqqq_sma_exit}", tqqq_sma_exit=tqqq_sma_exit))

    for rsi_cap in [60, 65, 70, 75, 80]:
        variants.append(
            Variant(
                f"Stretched re-entry guard: no entry/re-entry if RSI > {rsi_cap}",
                entry_rsi_max=rsi_cap,
                early_reentry_rsi_max=rsi_cap,
            )
        )

    for profit_target, reentry_drop, ratchet_pct in itertools.product(
        [0.15, 0.20, 0.25, 0.30],
        [0.075, 0.10, 0.125],
        [0.20, 0.25, 0.30],
    ):
        variants.append(
            Variant(
                f"Combo profit {profit_target:.0%}, re-buy -{reentry_drop:.1%}, ratchet {ratchet_pct:.0%}",
                profit_target=profit_target,
                reentry_drop=reentry_drop,
                ratchet_pct=ratchet_pct,
            )
        )

    return variants


def main() -> None:
    try:
        df = base.prepare_data()
    except requests.RequestException as exc:
        print("Could not download historical market data.")
        print("Needed tickers: TQQQ, QQQ, ^VIX from Yahoo Finance chart API.")
        print(f"Reason: {exc}")
        print("No live bot files or position state were changed.")
        raise SystemExit(2) from exc

    results = pd.DataFrame(run_variant(df, variant) for variant in variant_grid())
    results = results.sort_values(["final", "calmar"], ascending=False)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "expanded_tqqq_strategy_results.csv"
    results.to_csv(out_path, index=False)

    display = results.head(25).copy()
    display["final"] = display["final"].map(lambda value: f"{value:.1f}x")
    display["cagr"] = display["cagr"].map(lambda value: f"{value:.1%}")
    display["maxdd"] = display["maxdd"].map(lambda value: f"{value:.1%}")
    display["calmar"] = display["calmar"].map(lambda value: f"{value:.2f}")

    print(f"DATA {df.index[0]} -> {df.index[-1]} rows={len(df)} variants={len(results)}")
    print(display.to_string(index=False))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
