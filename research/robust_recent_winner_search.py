#!/usr/bin/env python3
"""Find strategies that improve the recent 10-minute window without obvious overfit.

Compares each candidate on:
- recent free intraday 5m data sampled every 10 minutes
- full-history daily data as a robustness sanity check
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
import two_month_swing_strategy_review as recent
import full_history_swing_strategy_review as full

OUT = ROOT / "research" / "out" / "robust_recent_winner_results.csv"


def make_name(profit, hard, trail, drop, timeout, rsi, adx, qqq_ema, early, vix, ema_slope, sma20_50):
    parts = [f"p{profit:.0%}", f"h{hard:.1%}", f"tr{trail:.0%}", f"drop{drop:.0%}", f"to{timeout}", f"rsi{rsi}"]
    if adx is not None:
        parts.append(f"adx{adx}")
    if qqq_ema:
        parts.append("qqqEMA21")
    if early is not None:
        parts.append(f"early<={early}")
    if vix is not None:
        parts.append(f"vix<={vix}")
    if ema_slope:
        parts.append("emaSlope")
    if sma20_50:
        parts.append("sma20>50")
    return " ".join(parts)


def candidates():
    out = []
    # Baseline and known families.
    out.append(dict(name="CURRENT", profit=0.08, hard_stop=0.075, trail=0.12, reentry_drop=0.03, timeout_days=3, rsi_max=60))
    # Broad but practical grid. ADX tests choppy-market protection.
    for profit, hard, trail, drop, timeout, rsi, adx in itertools.product(
        [0.08, 0.10, 0.12, 0.15],
        [0.05, 0.075, 0.10],
        [0.08, 0.10, 0.12, 0.15],
        [0.03, 0.05],
        [3, 5, 10],
        [60, 65, 70, None],
        [None, 18, 20, 22, 25, 28],
    ):
        out.append(dict(
            name=make_name(profit, hard, trail, drop, timeout, rsi, adx, False, None, None, False, False),
            profit=profit,
            hard_stop=hard,
            trail=trail,
            reentry_drop=drop,
            timeout_days=timeout,
            rsi_max=rsi,
            qqq_adx_min=adx,
        ))
    # Add constrained macro/chop combinations around current and promising ADX.
    for adx, early, vix, qqq_ema, ema_slope, sma20_50 in itertools.product(
        [None, 18, 20, 22, 25],
        [None, 1, 2],
        [None, 20, 25],
        [False, True],
        [False, True],
        [False, True],
    ):
        if sum(x is not None or bool(x) for x in [adx, early, vix, qqq_ema, ema_slope, sma20_50]) == 0:
            continue
        out.append(dict(
            name=make_name(0.08, 0.075, 0.12, 0.03, 3, 60, adx, qqq_ema, early, vix, ema_slope, sma20_50),
            profit=0.08,
            hard_stop=0.075,
            trail=0.12,
            reentry_drop=0.03,
            timeout_days=3,
            rsi_max=60,
            qqq_adx_min=adx,
            max_early_score=early,
            vix_max=vix,
            require_qqq_ema21=qqq_ema,
            qqq_ema21_slope5_min=0 if ema_slope else None,
            require_sma20_above_sma50=sma20_50,
        ))
    # Remove duplicates by name.
    seen = set()
    unique = []
    for item in out:
        if item["name"] not in seen:
            unique.append(item)
            seen.add(item["name"])
    return unique


def to_recent_variant(c):
    return recent.Variant(**c)


def to_full_variant(c):
    allowed = full.Variant.__dataclass_fields__.keys()
    return full.Variant(**{k: v for k, v in c.items() if k in allowed})


def main():
    f_df = full.prepare()
    all_candidates = candidates()
    print(f"Full-history prefilter candidates={len(all_candidates)} full_rows={len(f_df)}")

    full_rows = []
    for idx, c in enumerate(all_candidates, start=1):
        f_sum = full.run(f_df, to_full_variant(c))
        full_rows.append({
            "name": c["name"],
            "full_multiple": f_sum["final_multiple"],
            "full_cagr": f_sum["cagr"],
            "full_maxdd": f_sum["maxdd"],
            "full_win_rate": f_sum["win_rate"],
            "full_trades": f_sum["trades"],
        })
        if idx % 1000 == 0:
            print(f"...full {idx}/{len(all_candidates)}")

    full_df = pd.DataFrame(full_rows)
    current_full = full_df[full_df["name"] == "CURRENT"].iloc[0]
    robust_names = set(
        full_df[
            (full_df["full_multiple"] >= current_full["full_multiple"] * 0.70)
            & (full_df["full_maxdd"] >= -0.50)
        ]["name"]
    )
    # Also keep the best full-history and best drawdown candidates, so we do not
    # discard an interesting tradeoff too early.
    robust_names.update(full_df.sort_values("full_multiple", ascending=False).head(300)["name"])
    robust_names.update(full_df[full_df["full_maxdd"] >= -0.40].sort_values("full_multiple", ascending=False).head(300)["name"])
    survivor_candidates = [c for c in all_candidates if c["name"] in robust_names]

    r_df = recent.prepare()
    rows = []
    print(f"Recent test survivors={len(survivor_candidates)} recent_rows={len(r_df)}")
    full_by_name = full_df.set_index("name")
    for idx, c in enumerate(survivor_candidates, start=1):
        r_sum, _ = recent.run(r_df, to_recent_variant(c))
        f_sum = full_by_name.loc[c["name"]]
        rows.append({
            "name": c["name"],
            "recent_final": r_sum["final"],
            "recent_return": r_sum["return_pct"],
            "recent_maxdd": r_sum["maxdd"],
            "recent_win_rate": r_sum["win_rate"],
            "recent_trades": r_sum["trades"],
            "full_multiple": f_sum["full_multiple"],
            "full_cagr": f_sum["full_cagr"],
            "full_maxdd": f_sum["full_maxdd"],
            "full_win_rate": f_sum["full_win_rate"],
            "full_trades": f_sum["full_trades"],
            "profit": c["profit"],
            "hard_stop": c["hard_stop"],
            "trail": c["trail"],
            "reentry_drop": c["reentry_drop"],
            "timeout_days": c["timeout_days"],
            "rsi_max": c["rsi_max"],
            "qqq_adx_min": c.get("qqq_adx_min"),
            "max_early_score": c.get("max_early_score"),
            "vix_max": c.get("vix_max"),
            "require_qqq_ema21": c.get("require_qqq_ema21", False),
            "qqq_ema21_slope5_min": c.get("qqq_ema21_slope5_min"),
            "require_sma20_above_sma50": c.get("require_sma20_above_sma50", False),
        })
        if idx % 500 == 0:
            print(f"...recent {idx}/{len(survivor_candidates)}")
    df = pd.DataFrame(rows)
    current = df[df["name"] == "CURRENT"].iloc[0]
    df["robust_score"] = (
        (df["recent_return"] - current["recent_return"]) * 2.0
        + (df["full_cagr"] - current["full_cagr"]) * 1.2
        + (df["full_maxdd"] - current["full_maxdd"]) * 0.8
        + (df["recent_maxdd"] - current["recent_maxdd"]) * 1.0
    )
    df.to_csv(OUT, index=False)
    print(f"Wrote {OUT}")
    print("\nCURRENT")
    print(current.to_string())
    robust = df[(df["recent_return"] > 0) & (df["full_multiple"] >= current["full_multiple"] * 0.75) & (df["full_maxdd"] >= -0.45)].copy()
    print("\nROBUST RECENT WINNERS: recent > 0, full >= 75% current, full DD <= 45%")
    print(robust.sort_values(["robust_score", "full_multiple"], ascending=[False, False]).head(25).to_string(index=False))
    print("\nMAX RECENT WITH FULL_MULTIPLE >= CURRENT AND FULL_DD <= 45%")
    strict = df[(df["full_multiple"] >= current["full_multiple"]) & (df["full_maxdd"] >= -0.45)].copy()
    print(strict.sort_values(["recent_return", "full_multiple"], ascending=[False, False]).head(25).to_string(index=False))
    print("\nMAX FULL WITH RECENT >= CURRENT")
    recent_ok = df[df["recent_return"] >= current["recent_return"]].copy()
    print(recent_ok.sort_values(["full_multiple", "recent_return"], ascending=[False, False]).head(25).to_string(index=False))

if __name__ == "__main__":
    main()
