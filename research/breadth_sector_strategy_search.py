#!/usr/bin/env python3
"""Research-only test for free breadth/sector leadership ideas.

This script does not read or write live bot state.

It uses the local ``backtest_data.json`` export so it can run without any paid
API. The immediate test uses XLK as a free technology-sector leadership proxy.
If a future data export includes real Nasdaq-100 breadth columns, this script
can be extended to test those directly.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "backtest_data.json"
OUT_DIR = ROOT / "research" / "out"


@dataclass(frozen=True)
class Variant:
    name: str
    stop_pct: float = 0.25
    profit_target: float = 0.20
    reentry_drop: float = 0.05
    timeout_days: int = 15
    reentry_rsi_max: float | None = 70
    parabolic_ret5: float | None = 0.25
    sector_exit: str | None = None
    sector_reentry_filter: str | None = None


def calculate_rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def load_data() -> pd.DataFrame:
    payload = json.loads(DATA_FILE.read_text())
    df = pd.DataFrame(
        {
            "Close": payload["tqqq_close"],
            "High": payload["tqqq_high"],
            "QQQ_Close": payload["qqq_close"],
            "VIX_Close": payload["vix_close"],
            "XLK_Close": payload["xlk_close"],
        },
        index=pd.to_datetime(payload["dates"]),
    )

    for prefix in ["", "QQQ_", "XLK_"]:
        close_col = f"{prefix}Close"
        for window in [20, 50, 200]:
            df[f"{prefix}SMA{window}"] = df[close_col].rolling(window).mean()
        df[f"{prefix}RET5"] = df[close_col].pct_change(5)
        df[f"{prefix}RET10"] = df[close_col].pct_change(10)

    df["RSI14"] = calculate_rsi(df["Close"])
    df["XLK_QQQ_RATIO"] = df["XLK_Close"] / df["QQQ_Close"]
    df["XLK_QQQ_RATIO_SMA20"] = df["XLK_QQQ_RATIO"].rolling(20).mean()
    df["XLK_QQQ_RATIO_SMA50"] = df["XLK_QQQ_RATIO"].rolling(50).mean()
    df["XLK_20D_HIGH"] = df["XLK_Close"].rolling(20).max()
    df["XLK_DD_FROM_20D_HIGH"] = df["XLK_Close"] / df["XLK_20D_HIGH"] - 1
    return df.dropna()


def max_drawdown(values: list[float]) -> float:
    series = pd.Series(values)
    return float((series / series.cummax() - 1).min())


def cagr(final_value: float, years: float) -> float:
    return final_value ** (1 / years) - 1


def sector_exit_hit(row: pd.Series, variant: Variant) -> bool:
    if variant.sector_exit is None:
        return False
    if variant.sector_exit == "xlk_below_sma20":
        return row["XLK_Close"] < row["XLK_SMA20"]
    if variant.sector_exit == "xlk_below_sma50":
        return row["XLK_Close"] < row["XLK_SMA50"]
    if variant.sector_exit == "qqq_below_sma20":
        return row["QQQ_Close"] < row["QQQ_SMA20"]
    if variant.sector_exit == "qqq_below_sma50":
        return row["QQQ_Close"] < row["QQQ_SMA50"]
    if variant.sector_exit == "xlk_ratio_below_sma20":
        return row["XLK_QQQ_RATIO"] < row["XLK_QQQ_RATIO_SMA20"]
    if variant.sector_exit == "xlk_ratio_below_sma50":
        return row["XLK_QQQ_RATIO"] < row["XLK_QQQ_RATIO_SMA50"]
    if variant.sector_exit == "xlk_5d_under_qqq_by_2pct":
        return row["XLK_RET5"] < row["QQQ_RET5"] - 0.02
    if variant.sector_exit == "xlk_20d_drawdown_5pct":
        return row["XLK_DD_FROM_20D_HIGH"] <= -0.05
    raise ValueError(f"Unknown sector_exit: {variant.sector_exit}")


def sector_reentry_ok(row: pd.Series, variant: Variant) -> bool:
    if variant.sector_reentry_filter is None:
        return True
    if variant.sector_reentry_filter == "xlk_above_sma20":
        return row["XLK_Close"] > row["XLK_SMA20"]
    if variant.sector_reentry_filter == "xlk_above_sma50":
        return row["XLK_Close"] > row["XLK_SMA50"]
    if variant.sector_reentry_filter == "qqq_above_sma20":
        return row["QQQ_Close"] > row["QQQ_SMA20"]
    if variant.sector_reentry_filter == "xlk_ratio_above_sma20":
        return row["XLK_QQQ_RATIO"] > row["XLK_QQQ_RATIO_SMA20"]
    raise ValueError(f"Unknown sector_reentry_filter: {variant.sector_reentry_filter}")


def run_variant(df: pd.DataFrame, variant: Variant) -> dict:
    cash = 1.0
    shares = 0.0
    avg_cost = None
    highest_high = None
    position_open = False
    waiting_for_pullback = False
    last_exit_price = None
    exit_i = None
    values: list[float] = []
    trades: list[tuple[pd.Timestamp, str, float, str]] = []

    rows = list(df.iterrows())
    for i, (date, row) in enumerate(rows):
        price = float(row["Close"])
        values.append(cash + shares * price)
        if i == 0:
            continue

        _, prev = rows[i - 1]
        crossed_up = prev["Close"] <= prev["SMA200"] and row["Close"] > row["SMA200"]
        crossed_down = prev["Close"] >= prev["SMA200"] and row["Close"] < row["SMA200"]
        above_sma200 = row["Close"] > row["SMA200"]
        rsi_ok = variant.reentry_rsi_max is None or row["RSI14"] <= variant.reentry_rsi_max
        market_ok = above_sma200 and sector_reentry_ok(row, variant)

        if position_open:
            highest_high = max(float(highest_high), float(row["High"]))
            stop_hit = price < highest_high * (1 - variant.stop_pct)
            profit_hit = avg_cost is not None and price >= avg_cost * (1 + variant.profit_target)
            parabolic_hit = (
                avg_cost is not None
                and price >= avg_cost
                and variant.parabolic_ret5 is not None
                and row["RET5"] >= variant.parabolic_ret5
            )
            sector_hit = sector_exit_hit(row, variant)

            if crossed_down or stop_hit or profit_hit or parabolic_hit or sector_hit:
                reason = (
                    "sma200"
                    if crossed_down
                    else "stop"
                    if stop_hit
                    else "profit"
                    if profit_hit
                    else "parabolic"
                    if parabolic_hit
                    else "sector"
                )
                cash = shares * price
                shares = 0.0
                avg_cost = None
                highest_high = None
                position_open = False
                trades.append((date, "sell", price, reason))
                if reason in {"profit", "parabolic", "sector"}:
                    waiting_for_pullback = True
                    last_exit_price = price
                    exit_i = i
                else:
                    waiting_for_pullback = False
                    last_exit_price = None
                    exit_i = None
                continue

        if not position_open:
            should_enter = False
            reason = None
            if waiting_for_pullback and last_exit_price is not None:
                pullback_ready = price <= last_exit_price * (1 - variant.reentry_drop) and market_ok
                timeout_ready = exit_i is not None and i - exit_i >= variant.timeout_days and market_ok
                should_enter = (pullback_ready or timeout_ready) and rsi_ok
                reason = "pullback" if pullback_ready else "timeout"
            elif (crossed_up or (not trades and market_ok)) and rsi_ok:
                should_enter = True
                reason = "sma200_cross_up" if crossed_up else "initial"

            if should_enter and cash > 0:
                shares = cash / price
                cash = 0.0
                avg_cost = price
                highest_high = float(row["High"])
                position_open = True
                waiting_for_pullback = False
                last_exit_price = None
                exit_i = None
                trades.append((date, "buy", price, reason or "entry"))

    final = values[-1]
    years = (rows[-1][0] - rows[0][0]).days / 365.25
    exits = [trade for trade in trades if trade[1] == "sell"]
    drawdown = max_drawdown(values)
    return {
        "name": variant.name,
        "final": final,
        "cagr": cagr(final, years),
        "maxdd": drawdown,
        "calmar": cagr(final, years) / abs(drawdown),
        "trades": len(trades),
        "exits": len(exits),
        "profit_exits": sum(1 for trade in exits if trade[3] == "profit"),
        "sector_exits": sum(1 for trade in exits if trade[3] == "sector"),
        "stop_exits": sum(1 for trade in exits if trade[3] == "stop"),
        "sma_exits": sum(1 for trade in exits if trade[3] == "sma200"),
    }


def variants() -> list[Variant]:
    out = [
        Variant("CURRENT: TQQQ-only, no sector leadership filter"),
    ]
    sector_exits = [
        "xlk_below_sma20",
        "xlk_below_sma50",
        "qqq_below_sma20",
        "qqq_below_sma50",
        "xlk_ratio_below_sma20",
        "xlk_ratio_below_sma50",
        "xlk_5d_under_qqq_by_2pct",
        "xlk_20d_drawdown_5pct",
    ]
    reentry_filters = [
        None,
        "xlk_above_sma20",
        "xlk_above_sma50",
        "qqq_above_sma20",
        "xlk_ratio_above_sma20",
    ]
    for sector_exit, reentry_filter in itertools.product(sector_exits, reentry_filters):
        filter_text = reentry_filter or "no sector re-entry filter"
        out.append(
            Variant(
                f"Sector exit {sector_exit}; re-entry {filter_text}",
                sector_exit=sector_exit,
                sector_reentry_filter=reentry_filter,
            )
        )
    return out


def main() -> None:
    df = load_data()
    results = pd.DataFrame(run_variant(df, variant) for variant in variants())
    results = results.sort_values(["final", "calmar"], ascending=False)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "breadth_sector_strategy_results.csv"
    results.to_csv(out_path, index=False)

    display = results.head(20).copy()
    display["final"] = display["final"].map(lambda value: f"{value:.1f}x")
    display["cagr"] = display["cagr"].map(lambda value: f"{value:.1%}")
    display["maxdd"] = display["maxdd"].map(lambda value: f"{value:.1%}")
    display["calmar"] = display["calmar"].map(lambda value: f"{value:.2f}")
    print(f"DATA {df.index[0].date()} -> {df.index[-1].date()} rows={len(df)} variants={len(results)}")
    print(display.to_string(index=False))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
