# TQQQ Strategy Research Handoff

Last updated: 2026-05-14

## Purpose

This file is a compact context handoff for a new research chat. The goal is to continue strategy research without rereading the whole prior conversation.

The live repo is an automated TQQQ alert bot. It sends Telegram instructions, but the human executes real trades manually.

## Current Live Bot Strategy

Asset:

- Execution asset: `TQQQ`
- Waiting asset while out of TQQQ: `XLK`
- Long only

Entry:

- Normal trend entry is a TQQQ cross above its 200-day simple moving average (`SMA200`).
- After an early-warning exit, re-enter when TQQQ is back above both `SMA200` and `SMA20`.
- Every fresh buy or re-buy also requires TQQQ `RSI14 <= 60` to avoid chasing stretched rallies.

Full exit:

- Sell all if TQQQ crosses below `SMA200`.
- Sell all if the true ratcheting trailing stop is hit.

Trailing stop:

- Stop is 16% below the highest high since entry.
- Formula: `highest_high_since_entry * 0.84`
- It only moves upward while a position is open.
- It resets after a full exit and starts again after the next entry.

Swing profit cycle:

- Sell all shares at +20% from the current entry price.
- After a +20% profit exit, wait to re-buy after a 7.5% pullback from the profit-exit price.
- If the pullback does not happen within 20 trading days, re-buy anyway as long as TQQQ is still above SMA200.
- Every swing re-buy also requires `RSI14 <= 60`.
- After a stop/SMA200 exit, do not use the pullback rule; wait for the next SMA200 cross-up.
- After every re-entry, the cycle starts again with a new entry price, new trailing stop, and new +20% target.

Early-warning exit layer:

- Sell all if at least 3 of these 5 warning signs are active:
  - VIX >= 25.
  - VIX 5-day increase >= 25%.
  - QQQ below EMA21.
  - TQQQ below SMA50.
  - TQQQ RSI14 falling after being at or above 70.
- This layer was added on 2026-05-06 after a local historical search showed better return and drawdown than the local swing baseline.

Manual safety mode:

- Optional GitHub Actions manual mode: `manual_sold`.
- Requires `manual_price`, the actual price where the human sold.
- This mode marks the position closed and records `manual_exit_price`.
- It intentionally does not allow immediate re-buy just because TQQQ is above SMA200.
- Re-buy after manual safety mode only when:
  - current price is at least 7.5% below the manual sell price and still above SMA200, or
  - price went below SMA200 after the manual exit and later crosses back above SMA200, or
  - 20 trading days passed and TQQQ is still above SMA200.
- The `RSI14 <= 60` re-entry guard still applies to all manual safety re-entry paths.

Waiting asset:

- On 2026-05-14, temporary out-of-TQQQ parking options were tested.
- `SGOV`/`BIL` were rejected because the expected holding period is short and tax/broker friction can be larger than the benefit.
- Corrected full-history result from 2010-11-24 through 2026-05-13:

| Waiting Asset | Final | CAGR | Max DD | Note |
| --- | ---: | ---: | ---: | --- |
| Cash | 38.2x | 26.6% | -47.7% | Missed upside |
| QQQ | 134.8x | 37.3% | -45.7% | Good simple option |
| XLK | 151.3x | 38.3% | -44.2% | Selected default |
| VGT | 148.1x | 38.1% | -44.9% | Similar to XLK |
| SMH | 216.7x | 41.6% | -54.6% | Higher risk |
| QLD | 218.9x | 41.7% | -66.5% | Too leveraged |
| USD | 308.2x | 44.9% | -79.0% | Too dangerous |

- Real account behavior: XLK is manual only. The bot shows XLK guidance and tracks it only if the user records it.
- Manual modes:
  - `manual_parking_bought` with `manual_price=<XLK buy price>` and optional `manual_shares=<XLK shares>`.
  - `manual_parking_sold` with `manual_price=<XLK sell price>`.
- XLK sell rules:
  - Sell XLK and move back to TQQQ when the normal TQQQ re-entry signal triggers.
  - Sell XLK and wait in cash if TQQQ falls below SMA200.
  - Sell XLK and wait in cash if the early-drop risk model reaches 3 active warning signs.
  - Sell XLK and wait in cash if XLK hits its own 5% ratcheting trailing stop from the highest XLK high since the waiting-asset entry.
- Bot-only benchmark behavior: automatically simulates XLK parking after bot exits TQQQ only if TQQQ is still above SMA200 and early-drop risk is not high. It returns to TQQQ on bot re-entry and moves XLK to cash if TQQQ becomes defensive or XLK hits its 5% trailing stop. This keeps the benchmark as a pure "follow the bot" path, not a manual path.

Current tracked real position state:

```json
{
  "avg_cost": null,
  "cash": 2726.11,
  "early_exit_date": null,
  "early_exit_price": null,
  "entry_date": null,
  "highest_high_since_entry": null,
  "last_profit_sell_price": null,
  "last_action": "manual_sold",
  "manual_exit_mode": true,
  "manual_exit_price": 67.37,
  "parking_avg_cost": null,
  "parking_shares": 0.0,
  "parking_ticker": "XLK",
  "position_open": false,
  "profit_exit_date": null,
  "shares": 0.0,
  "ticker": "TQQQ",
  "waiting_for_early_reentry": false,
  "waiting_for_pullback": false
}
```

Current implied levels:

- Manual safety mode is active.
- Re-buy condition from the current cash state: manual pullback target or SMA200 reset, plus `RSI14 <= 60`.
- If the human buys XLK while waiting, it should be recorded with `manual_parking_bought`.
- No active trailing stop while out of position.
- No active profit target while out of position.

## Bot-Only Benchmark

A separate file, `bot_strategy_state.json`, tracks the paper benchmark for the original bot-only behavior:

- It starts from the same original TQQQ position.
- It ignores manual/panic sells.
- It follows only deterministic bot strategy rules.
- It now also follows the selected bot waiting-asset rule by simulating XLK while out of TQQQ.
- It is updated during normal bot checks.

Use this at month-end to compare:

- Real/manual path: `position_state.json`
- Bot-only path: `bot_strategy_state.json`

The daily Telegram report includes a `Bot-Only Benchmark` section with total value and the gap versus the real path.

## Scheduling And Data

Scheduler:

- Cloudflare Worker triggers GitHub Actions.
- Intraday checks run every 10 minutes during NASDAQ trading hours.
- Daily reports run 15 minutes after market open and 15 minutes before market close.

Price handling:

- The bot uses Yahoo/yfinance.
- Daily data is used for SMA/RSI/ATR calculations.
- During market hours, the bot overlays Yahoo's latest 1-minute TQQQ bar on top of the daily history.
- If the latest 1-minute price is stale by more than 30 minutes while the market is open, the run fails instead of trading on stale data.
- Telegram reports include a price source line, such as `1m bar ...`.

Important caveat:

- Yahoo/yfinance can be flaky. A second price source fallback is a future improvement.

## Backtest Tooling

Research file:

- `research/backtest_trailing_stops.py`

It can fetch historical Yahoo chart data and compare strategy variants.

Important correction:

- A previous quick sweep mislabeled some profit rules. The corrected model starts the first profit target at `1 + profit_step`.
- Example: `profit_step = 1.25` means first target is `2.25x`, not `2.0x`.

Latest swing test:

- Current prior strategy: about `77.8x`, `32.6%` CAGR, `-42.7%` max drawdown.
- Swing +10%, re-buy after -3%, 20-day timeout: about `36.6x`, `26.3%` CAGR, `-44.6%` max drawdown.
- Swing +25%, re-buy after -5%, 20-day timeout: about `52.2x`, `29.2%` CAGR, `-42.7%` max drawdown.
- Swing +20%, re-buy after -7.5%, 20-day timeout: about `97.4x`, `34.5%` CAGR, `-42.4%` max drawdown.
- Decision: implement the +20% / -7.5% / 20-day version.

## Strategies Already Tested

Trailing stops:

- Old rolling 30-day high minus 35%.
- True ratchet stops at 15%, 20%, 22.5%, 25%, 27.5%, 30%, 35%, 40%.
- ATR stops based on daily low, close, and highest high.
- ATR multipliers from roughly 1x to 8x.

Conclusion:

- 2026-05-15 retest after adding XLK waiting-asset behavior and the RSI <= 60 re-entry guard:
  - No TQQQ trailing stop: `43.1x`, `27.6%` CAGR, `-47.7%` max drawdown.
  - 25% true ratchet: `44.5x`, `27.8%` CAGR, `-47.7%` max drawdown.
  - 18% true ratchet: `47.0x`, `28.3%` CAGR, `-47.7%` max drawdown.
  - 16% true ratchet: `55.6x`, `29.7%` CAGR, `-47.7%` max drawdown.
  - 10% true ratchet: `22.4x`, `22.3%` CAGR, `-56.6%` max drawdown.
- Current selected TQQQ stop is now true 16% ratchet from highest high since entry.
- Very tight 5-10% TQQQ stops were rejected because they caused too many noisy exits.

Trend filters:

- SMA100, SMA150, SMA200.
- EMA100, EMA150, EMA200.
- QQQ signal filters.

Conclusion:

- SMA200 was the best simple trend backbone.
- Faster trend filters caused too much churn.

VIX filters:

- VIX exits at 30, 35, 40 with different re-entry thresholds.

Conclusion:

- VIX added complexity without enough improvement.

QQQ/TQQQ "Sniper" strategy:

- Signal asset: QQQ.
- Execution asset: TQQQ.
- QQQ above SMA200.
- EMA9 above EMA21.
- RSI filters.
- ATR3 stop.
- RSI>80 trims.

Conclusion:

- Performed much worse than the simpler SMA200 TQQQ strategy.

RSI sell and re-buy strategy:

- Tested RSI full exits at 70, 75, 80, 85, 90.
- Tested re-buy levels from 45 to 70.
- Tested several re-entry modes.

Best RSI variant:

- Sell all when RSI >= 80.
- Re-buy when RSI <= 70 and price is still above SMA200.

Result:

| Strategy | Final | CAGR | Max DD | Trades | Exits |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current baseline | 77.8x | 32.6% | -42.7% | 92 | 43 |
| Best RSI sell/re-buy | 78.1x | 32.6% | -49.7% | 214 | 107 |

Conclusion:

- RSI sell/re-buy produced almost no extra final return.
- It caused much more trading and worse drawdown.
- Keep RSI as report context only, not as a trading trigger.

Profit-taking:

Tested:

- No profit taking.
- Frequent small trims at +10%, +20%, +25%, +50%.
- Larger trims at +100%, +125%, +200%, +250%.
- Trim fractions from 5% to 90%.

Key findings:

- Small frequent profit grabs feel good emotionally but reduced long-term compounding.
- Best practical profit rule was `+125%, sell 90%`.

Current live strategy result:

| Strategy | Final | CAGR | Max DD | Trades | Exits | Trims |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SMA200 + 25% ratchet + +125% sell 90% | 77.8x | 32.6% | -42.7% | 92 | 43 | 5 |

## Individual Stock Research

Question tested:

- Could applying the same strategy to individual stocks beat TQQQ?

Stocks tested:

- `NVDA`, `AAPL`, `MSFT`, `AMZN`, `GOOGL`, `META`, `TSLA`, `AVGO`, `AMD`, `NFLX`, `COST`, `ORCL`, `ADBE`, `CRM`

Same strategy on single stocks:

| Asset | Strategy Final | CAGR | Max DD |
| --- | ---: | ---: | ---: |
| TQQQ | 77.8x | 32.6% | -42.7% |
| NVDA | 29.0x | 24.2% | -44.7% |
| AAPL | 15.1x | 19.1% | -35.3% |
| NFLX | 13.2x | 18.0% | -45.9% |
| META | 11.7x | 20.5% | -28.0% |

Conclusion:

- Applying the same trend strategy to one individual stock did not beat TQQQ.

## Momentum Rotation Research

Question tested:

- Could rotating between strong individual Nasdaq/AI/mega-cap stocks beat TQQQ?

Simple test:

- Universe: today's known mega-cap/AI winners.
- Rank stocks by 6-month momentum.
- Rotate monthly or weekly into top 1, 2, 3, or 5 names.
- Optional SMA200 filter.

Best results since 2013-03-07:

| Strategy | Final | CAGR | Max DD |
| --- | ---: | ---: | ---: |
| Monthly rotate top 2 by 6-month momentum | 426.9x | 58.5% | -51.9% |
| Monthly rotate top 1 by 6-month momentum | 372.3x | 56.8% | -60.6% |
| Monthly rotate top 3 by 6-month momentum | 191.9x | 49.1% | -44.9% |
| TQQQ buy and hold since 2013-03-07 | 109.6x | 42.9% | -81.7% |
| TQQQ current strategy since 2013-03-07 | 39.2x | 32.2% | -42.7% |

Important warning:

- This has serious survivorship bias.
- The test used today's known winners, such as NVDA, AVGO, TSLA, META.
- A proper test must use a historically valid universe, such as Nasdaq-100 constituents at each point in time, or at least a broader fixed universe with delisted/underperforming names included.

Preliminary conclusion:

- Single-stock trend strategy: not better than TQQQ.
- Stock momentum rotation: historically much better in the biased test, but riskier and not yet trustworthy enough for live automation.

## Recommended Next Research

Research goal:

- Decide whether a separate monthly momentum rotation bot is worth building.

Questions to answer:

1. Can a less biased universe be obtained?
   - Historical Nasdaq-100 constituents by date would be ideal.
   - If unavailable, use a broad fixed universe and explicitly label survivorship bias.

2. Which rotation rule is robust?
   - Monthly top 2 by 6-month momentum.
   - Monthly top 3 by 6-month momentum.
   - Weekly top 2 or top 3.
   - With and without SMA200 filter.

3. What is the tax/trading impact?
   - Rotation may create many taxable events.
   - It may be harder to follow manually than the TQQQ bot.

4. What drawdown is acceptable?
   - Top 2 rotation had much higher returns but about -52% max drawdown.
   - Top 3 had lower return but better drawdown around -45%.

5. Should it be separate from the TQQQ bot?
   - Recommendation: yes.
   - Keep stock rotation separate from the TQQQ bot.
   - Research rotation separately before touching live stock-picking automation.

## Current Recommendation

The live TQQQ bot has been changed to the +20% swing profit cycle plus an optimized early-warning exit layer, with an RSI14 <= 60 guard on all fresh buys and re-buys.

On 2026-05-06, an early-warning search tested TQQQ, QQQ, and VIX signals from 2010-11-24 through 2026-05-06. The selected live rule sells all when at least 3 of these 5 conditions are active:

- VIX >= 25.
- VIX 5-day increase >= 25%.
- QQQ below EMA21.
- TQQQ below SMA50.
- TQQQ RSI14 falling after being at or above 70.

Historical comparison in that local test:

| Strategy | Final | CAGR | Max DD | Trades | Early Exits |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current swing baseline in this test | 36.7x | 26.3% | -49.5% | 164 | 0 |
| Selected early-warning strategy | 85.8x | 33.4% | -46.1% | 240 | 49 |

The real account is currently in cash after the 2026-05-05 manual sell. Manual safety mode is active, so the real path waits for the manual pullback target, SMA200 reset, or 20-trading-day timeout, plus RSI14 <= 60.

On 2026-05-12, extra variants were tested from 2010-11-24 through 2026-05-12. The RSI14 <= 60 re-entry guard reduced historical max drawdown from -46.1% to -26.0% while keeping the final multiple close to the previous winner: 82.1x vs 85.8x. This guard was added because the real account is currently in cash and TQQQ is stretched.

Parabolic stretch exits were also checked. TQQQ 5-day return >= 25% and 10-day return >= 30% improved the backtest when used as sell rules, but each fired only once in more than 15 years. They were added to the Telegram report as advisory-only warnings, not automatic sell rules.

Manual safety re-entry was updated after checking strict manual, RSI-only, and hybrid timeout policies. The practical rule is strict first, then after 20 trading days allow re-entry above SMA200 if RSI14 <= 60. This is meant to avoid months in cash after a manual sell without allowing immediate chase-buying.

The current TQQQ strategy is more active than the previous versions. Watch the next month for whether the early-warning layer creates too many false exits during strong trends.
