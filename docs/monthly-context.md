# TQQQ Bot Monthly Context

Last updated: 2026-06-10

## Current Decision

The live repo is now **TQQQ-only**.

- No waiting ETF is tracked by this repo.
- When out of TQQQ, the bot waits in cash.
- Telegram messages should show only TQQQ, cash, risk context, and the bot-only benchmark.
- Telegram messages include a "Read first" line: follow the `Action`; risk sections explain context unless they explicitly create that action.
- If broker cash changes manually, use `manual_cash_set` to update the tracked cash.

## Live Strategy

The selected live TQQQ rule set is now the **New Broad Max / max-revenue** profile. It was chosen after comparing the current recommended setup, the broader max-revenue setup, and walk-forward robustness periods. The user chose maximum return while accepting larger drawdown risk.

| Rule | Current Value |
|---|---:|
| TQQQ trailing stop | 25% from highest high since entry |
| Fresh-entry guard | 10% below average cost for first 2 trading days |
| Profit target | Sell all at +25% from average cost |
| Re-buy pullback | Buy after -7.5% from profit/manual exit price |
| Profit re-buy timeout | 10 trading days |
| Manual safety timeout | 3 trading days |
| Re-entry RSI guard | RSI14 <= 70 |
| SMA200 confirmation | 3 confirmed checks/days above for entry, 3 below for exit |
| Parabolic stretch | Advisory only; no automatic sell |
| Waiting asset | Cash only |
| Early-warning risk | Advisory only |

## Entry And Re-entry

The bot can buy/re-buy TQQQ when one of the re-entry triggers is active and all required filters pass:

- Profit pullback: price is at least 7.5% below the last profit-exit price.
- Profit timeout: 10 trading days passed since the profit exit, trend is still above SMA200.
- Manual pullback: price is at least 7.5% below the manual sell price.
- Manual timeout: 3 trading days passed since the manual sell, trend is still above SMA200.
- SMA reset after manual sell: price first confirms below SMA200, then confirms back above it.
- Fast-drop combo warning: `VIX 5d spike >= 25%` plus `RSI falling from 70+`. This is an important advisory warning; it does not sell automatically in the current rule set.

The re-entry RSI gate is currently `RSI14 <= 70`.

## Exit Rules

While holding TQQQ, the bot can tell the user to sell all when:

- TQQQ is within the first 2 trading days after entry and falls 10% below average cost.
- TQQQ falls below the 25% trailing stop.
- TQQQ confirms below SMA200 for 3 checks/days.
- TQQQ reaches +25% profit from average cost.

After any sell, the repo stays in cash and waits for the next TQQQ re-entry signal.

## Manual Modes

Available GitHub Actions `workflow_dispatch` modes:

- `check`: signal-only check.
- `daily`: full Telegram report.
- `auto`: normal scheduled behavior.
- `manual_sold`: record a manual TQQQ sell and enter manual safety mode. Requires `manual_price`.
- `manual_bought`: record a manual TQQQ buy. Requires `manual_price`; `manual_shares` is optional.
- `manual_cash_set`: set tracked cash after broker-side changes. Requires `manual_amount`.

## Current Real-World State

As of the latest local state inspection on 2026-06-08, the bot is in an open TQQQ position after a manual broker buy sync:

- Position open: `true`
- Shares: `35.3032`
- Average cost: `$83.84`
- Entry date: `2026-06-04`
- Highest high since entry: `$86.25`
- Cash: `$4.80`
- Last action: `manual_broker_buy_sync`
- Manual exit mode: `false`
- Manual exit price: `null`
- Manual exit date: `null`
- Last report key: `2026-06-08:open`

Current alignment for month-end testing:

- `tqqq-alert` remains the real master strategy.
- `real-stock-alert` should have `$0.00` deployable real-stock cash while this TQQQ position is open, but its bot-only stock benchmark can keep running for comparison.
- `real-stock-alert` now uses its selected max-revenue stock setup for the benchmark and future TQQQ-out stock bucket: RS63-heavy scoring, 8% ATR fresh-buy cap, two-week rank confirmation, and no fixed timeout.
- The real-stock bot-only benchmark was reset on 2026-06-09 to `$2,697.38` cash, matching the current tracked TQQQ-sized bucket estimate used for stock-benchmark comparison.
- `swing-stock-alert` remains paused and should be used only as optional historical paper-demo context.

If broker cash or shares differ from the repo's tracked state, run the relevant manual sync action:

1. GitHub Actions -> TQQQ Alert System -> Run workflow.
2. Use `manual_bought` to sync a broker TQQQ buy, `manual_sold` to sync a manual sell, or `manual_cash_set` to sync cash after broker changes.

Then run `daily` to confirm the Telegram message shows the current TQQQ position and cash.

## 2026-06-06 Fresh-Entry Improvement

The June 5 drop showed that the normal 25% trailing stop is intentionally wide and does not protect a brand-new entry from a sharp immediate reversal. A narrow guard was added:

- Active only during the first 2 trading days after a buy.
- Stop level is 10% below average cost.
- If hit, the bot sends a SELL action and resets to cash.
- After that sell, it waits in cash for the rest of the same trading day instead of immediately chasing back in. On the next trading day, normal fresh-entry logic can work again if trend and RSI allow it.
- Buy and manual-buy messages show the guard price so the user can also set a broker stop or TradingView price alert immediately after entering.

Recent intraday check: using the free March-June 2026 5-minute Yahoo window, the baseline 10-minute simulation re-bought 10 minutes after a June 5 fresh-entry guard sell. A same-day cooldown avoided that loop and improved that short recent window from `1.2638x` to `1.2780x`. The full daily backtest favored this cooldown approach over a longer pullback-wait after guard sells, because the longer wait hurt compounding.

This is meant to catch failed new entries without replacing the main 25% trend stop.

## 2026-06-10 New Broad Max Strategy Switch

After deeper robustness testing, the user decided to move from the Best Calmar high-return profile to the New Broad Max profile for maximum revenue.

Selected rules:

- 25% trailing stop.
- +25% profit target.
- -7.5% pullback re-entry from the actual sell price.
- 10 trading-day profit re-entry timeout.
- 3 trading-day manual safety timeout.
- RSI re-entry cap: RSI14 <= 70.
- 3-check/day SMA200 confirmation for entries and exits.
- Parabolic 5-day/10-day stretch remains visible in Telegram but is advisory only.
- Early-warning section remains advisory only.

Historical robustness summary:

- New Broad Max: `420.4x`, `-42.5% max drawdown`, `68.6% win rate`.
- Current recommended / Best Calmar before switch: `309.3x`, `-37.3% max drawdown`, `61.3% win rate`.
- Walk-forward comparison: New Broad Max won 4 of 5 tested periods, losing only in 2015-2018.

This is the aggressive choice. It is not the lowest-drawdown choice, but it was selected because the user explicitly wants maximum revenue.

## 2026-06-08 Best Calmar Strategy Switch

After reviewing the one-month behavior from the first TQQQ buy through the June 5 drop, the repo first tested a practical-protection profile, then compared all combined rule families again. The selected production profile is now the Best Calmar high-return setup:

- 25% trailing stop.
- +20% profit target.
- -7.5% pullback re-entry from the actual sell price.
- 10 trading-day profit re-entry timeout.
- RSI re-entry gate off.
- Parabolic profit exit on 5-day >= 25% or 10-day >= 30%.
- Early-warning section remains advisory only.

Combined-rule historical comparison:

- Raw max-revenue winner: `374.8x`, `46.6% CAGR`, `-43.6% max drawdown`; likely too optimized and dependent on a tight 12% stop.
- Best Calmar selected profile: `309.3x`, `44.8% CAGR`, `-37.3% max drawdown`, `61.3% win rate`.
- Best <=35% drawdown profile: `166.3x`, `39.1% CAGR`, `-33.5% max drawdown`.
- Current practical-protection profile before this switch: `20.4x`, `21.5% CAGR`, `-32.8% max drawdown`.

Recent one-month simulation from the April 29 position through the June 5 close:

- Best Calmar selected profile: `$2,811.41`, `+12.9%`, `-16.4% max drawdown`.
- Practical-protection profile: `$2,791.96`, `+12.1%`, `-10.5% max drawdown`.
- Raw max-revenue winner: `$2,821.45`, `+13.3%`, `-11.7% max drawdown`.

This profile was later replaced on 2026-06-10 by the New Broad Max profile after the user chose maximum revenue over the lower-drawdown compromise.

## 2026-06-06 Intraday Entry Open Delay

The June 5 move also showed a second issue: the bot can re-buy at the market open as soon as a pullback target is hit, before the first 30 minutes reveal whether the open is stable or collapsing. A recent 5-minute intraday sanity check showed:

- Baseline 10-minute behavior with same-day guard cooldown: `1.2780x`.
- No re-buys before 10:00 New York time: `1.3063x`.
- No bot buys at all before 10:00 New York time: `1.3136x`.

Production choice: delay all bot-generated buy signals for the first 30 market minutes. This is an execution-quality guard based on limited recent intraday data; the long full-history daily backtest cannot validate intraday timing.

## Bot-Only Benchmark

The bot-only benchmark models what would happen if the user followed only the bot's TQQQ instructions.

- It uses the same live New Broad Max TQQQ-only rule set.
- It stays in cash while out of TQQQ.
- It does not include manual moves unless they are part of the modeled bot rules.

## Hebrew Summary

הבוט עכשיו מוגדר כ-**TQQQ בלבד**.

- אין נכס המתנה אחר בתוך הריפו.
- כשהבוט מחוץ ל-TQQQ, הוא מחכה במזומן.
- הודעות טלגרם צריכות להציג רק TQQQ, מזומן, מצב סיכון, ובנצ'מרק של הבוט.
- אם המזומן בברוקר השתנה ידנית, משתמשים ב-`manual_cash_set`.

הכללים הפעילים:

- טריילינג סטופ של 25% מהשיא מאז הכניסה.
- הגנת כניסה חדשה: ביומיים הראשונים אחרי קנייה, אם TQQQ יורדת 10% מתחת למחיר הקנייה הממוצע, הבוט נותן הוראת מכירה.
- מכירה מלאה ברווח של 25%.
- כניסה מחדש אחרי ירידה של 7.5% ממחיר היציאה. אחרי מכירת רווח רגילה הטיימאאוט הוא 10 ימי מסחר; אחרי מכירה ידנית הטיימאאוט הוא 3 ימי מסחר.
- חסימת RSI לכניסה מחדש: RSI14 <= 70.
- אישור SMA200 דורש 3 בדיקות/ימים מעל לכניסה ו-3 מתחת ליציאה.
- Parabolic הוא מידע בלבד ולא מוכר אוטומטית.
- אזהרות סיכון הן מידע בלבד ולא מוכרות אוטומטית.
- אם מופיע שילוב מהיר של קפיצה ב-VIX ו-RSI יורד, זו אזהרה חשובה לשקול הגנה ידנית.
- בזמן המתנה: מזומן בלבד.

מצב ידני:

- `manual_sold`: מתעד מכירת TQQQ ידנית ומפעיל מצב בטיחות.
- `manual_bought`: מתעד קניית TQQQ ידנית.
- `manual_cash_set`: מעדכן את סכום המזומן שהבוט עוקב אחריו.
