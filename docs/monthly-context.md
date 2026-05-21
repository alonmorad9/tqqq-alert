# TQQQ Bot Monthly Context

Last updated: 2026-05-21

## Current Decision

The live repo is now **TQQQ-only**.

- No waiting ETF is tracked by this repo.
- When out of TQQQ, the bot waits in cash.
- Telegram messages should show only TQQQ, cash, risk context, and the bot-only benchmark.
- If broker cash changes manually, use `manual_cash_set` to update the tracked cash.

## Live Strategy

The selected high-risk/high-reward TQQQ rule set is:

| Rule | Current Value |
|---|---:|
| TQQQ trailing stop | 16% from highest high since entry |
| Profit target | Sell all at +20% from average cost |
| Re-buy pullback | Buy after -5% from profit/manual exit price |
| Profit re-buy timeout | 15 trading days |
| Manual safety timeout | 3 trading days |
| Re-entry RSI guard | RSI14 <= 80 |
| Parabolic profit exit | 5-day return >= 25% OR 10-day return >= 30% |
| Waiting asset | Cash only |
| Early-warning exit | Current 3-of-5 model |

## Entry And Re-entry

The bot can buy/re-buy TQQQ when one of the re-entry triggers is active and all required filters pass:

- Profit pullback: price is at least 5% below the last profit-exit price.
- Profit timeout: 15 trading days passed since the profit exit, trend is still above SMA200.
- Manual pullback: price is at least 5% below the manual sell price.
- Manual timeout: 3 trading days passed since the manual sell, trend is still above SMA200.
- SMA reset after manual sell: price first went below SMA200, then crossed back above it.
- Early-risk recovery: after an early-warning sell, price is above SMA200 and SMA20.

All buy/re-buy paths require `RSI14 <= 80`.

## Exit Rules

While holding TQQQ, the bot can tell the user to sell all when:

- TQQQ falls below the 16% trailing stop.
- TQQQ crosses below SMA200.
- TQQQ reaches +20% profit from average cost.
- The early-warning model reaches 3 active warnings.
- The parabolic rule is hit while the position is profitable.

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

As of the latest local state inspection on 2026-05-21, the bot is back in an open TQQQ position:

- Position open: `true`
- Shares: `35.6658`
- Average cost: `$75.20`
- Entry date: `2026-05-21`
- Cash: `$0.00`
- Last action: `manual_broker_buy_sync`

If broker cash or shares differ from the repo's tracked state, run the relevant manual sync action:

1. GitHub Actions -> TQQQ Alert System -> Run workflow.
2. Use `manual_bought` to sync a broker TQQQ buy, or `manual_cash_set` to sync cash after broker changes.

Then run `daily` to confirm the Telegram message shows the current TQQQ position and cash.

## Bot-Only Benchmark

The bot-only benchmark models what would happen if the user followed only the bot's TQQQ instructions.

- It uses the same live TQQQ-only rule set.
- It stays in cash while out of TQQQ.
- It does not include manual moves unless they are part of the modeled bot rules.

## Hebrew Summary

הבוט עכשיו מוגדר כ-**TQQQ בלבד**.

- אין נכס המתנה אחר בתוך הריפו.
- כשהבוט מחוץ ל-TQQQ, הוא מחכה במזומן.
- הודעות טלגרם צריכות להציג רק TQQQ, מזומן, מצב סיכון, ובנצ'מרק של הבוט.
- אם המזומן בברוקר השתנה ידנית, משתמשים ב-`manual_cash_set`.

הכללים הפעילים:

- טריילינג סטופ של 16% מהשיא מאז הכניסה.
- מכירה מלאה ברווח של 20%.
- כניסה מחדש אחרי ירידה של 5% ממחיר היציאה. אחרי מכירת רווח רגילה הטיימאאוט הוא 15 ימי מסחר; אחרי מכירה ידנית הטיימאאוט הוא 3 ימי מסחר.
- כניסה מחדש רק אם RSI14 קטן או שווה ל-80.
- יציאת parabolic אם תשואת 5 ימים גדולה או שווה 25% או תשואת 10 ימים גדולה או שווה 30%.
- בזמן המתנה: מזומן בלבד.

מצב ידני:

- `manual_sold`: מתעד מכירת TQQQ ידנית ומפעיל מצב בטיחות.
- `manual_bought`: מתעד קניית TQQQ ידנית.
- `manual_cash_set`: מעדכן את סכום המזומן שהבוט עוקב אחריו.
