# TQQQ Swing Bot Context

Last updated: 2026-08-12

## Current Purpose

This repo is now a **TQQQ-only swing alert bot** for a smaller aggressive bucket, currently initialized with `$1,000` cash.

The goal is no longer long-term TQQQ holding or maximum theoretical return. The goal is faster swing behavior:

- Take profits quickly.
- Cut bad trades earlier.
- Re-enter after a small pullback or short timeout.
- Keep Telegram messages clear enough to act on.

## Live Rule Set

| Rule | Current Value |
|---|---:|
| Execution asset | TQQQ |
| Trend filter | TQQQ and QQQ must be above SMA200 |
| SMA confirmation | 3 confirmed checks/days |
| Profit target | Sell all at +8% from entry |
| Hard stop | Sell all at -10% from entry |
| Trailing stop | Sell all at -15% from highest high since entry |
| Re-buy pullback | Buy after -3% from last sell price |
| Re-buy timeout | 3 trading days |
| Manual sell timeout | 3 trading days |
| Re-entry RSI cap | Off |
| Anti-chop entry filter | QQQ ADX14 >= 25 |
| Waiting asset | Cash only |
| Early warnings | Advisory only |
| Support break watch | Advisory only: shows 5-day near support plus prior 30-period tested support, High at 2/2 confirmed breaks |
| Fibonacci / patterns | Research context only, not automatic |

## Backtest Summary

Historical test from TQQQ inception using daily data:

| Strategy | Final On $1,000 | CAGR | Max DD | Win Rate | Trades |
|---|---:|---:|---:|---:|---:|
| Prior swing strategy | `71.2x` | `31.2%` | `-34.7%` | `59.4%` | `395` |
| Current ADX anti-chop strategy | `233.1x` | `41.5%` | `-35.4%` | `72.0%` | `329` |
| 10% profit variant | `$51,995` | lower | `-37.8%` | lower | similar |
| 6% profit variant | `$30,369` | lower | `-36.7%` | lower | more churn |
| 15% trail variant | `$52,695` | lower | `-33.1%` | lower | similar |
| 5% hard-stop variant | `$22,409` | lower | `-43.0%` | lower | more whipsaws |
| RSI <= 65 variant | `$47,601` | lower | `-34.8%` | lower | fewer good entries |

Exit reasons in the selected test:

- `profit_take`: 109 exits.
- `hard_stop`: 45 exits.
- `trail_stop`: 22 exits.
- `sma200_exit`: 4 exits.

Interpretation: this is still aggressive, but it behaves much more like a swing system than the old 25% trailing/large-profit setup. The latest ADX version specifically tries to avoid repeated losses in choppy Nasdaq markets.

## How The Trade Works

### When In Cash

The bot waits for:

- Trend confirmed above SMA200.
- Nasdaq trend strength ready: `QQQ ADX14 >= 25`.
- If after a prior sell: either price drops 3% from the sell price, or 3 trading days pass.
- No bot buy during the first 30 minutes after market open.

When ready, Telegram sends a `BUY SIGNAL` or `RE-BUY SIGNAL`.

### When In TQQQ

The bot watches:

- `+8%` profit target.
- `-10%` hard stop from entry.
- `-15%` trailing stop from highest high since entry.
- Confirmed SMA200 weakness.

If any real exit rule is hit, Telegram sends a `SELL NOW` message and the bot state moves to cash.

### After A Sell

The bot waits in cash for the next re-entry:

- Price down 3% from sell price, or
- 3 trading days pass,
- and trend/ADX filters allow the buy.

## Manual Workflow

GitHub Actions manual modes:

- `daily`: send a full Telegram status report.
- `check`: run a compact status check.
- `manual_cash_set`: sync cash after broker changes.
- `manual_bought`: tell the bot you bought TQQQ manually.
- `manual_sold`: tell the bot you sold TQQQ manually.

The bot does not place broker orders and does not auto-fill the real tracked portfolio at the bot's market price. It sends Telegram instructions; real state changes only after an exact broker-fill sync.

Telegram sync shortcuts, after the Cloudflare webhook is configured:

- `/bought PRICE SHARES`: sync exact broker buy.
- `/sold PRICE`: sync exact broker sell.
- `/cash AMOUNT`: sync cash bucket.
- `/daily`: queue a full report.
- `/check`: queue a compact status check.
- `/swing`: queue the swing tracker daily digest.
- `/swingstops`: immediately check swing trade manual stop ladders.

The persistent Telegram keyboard is the main control panel. BUY/SELL alerts do not update the real tracked state until `/bought PRICE SHARES` or `/sold PRICE` is sent.

Keyboard buttons:

- `Daily report`: queues a full status report now, even if there is no buy/sell signal.
- `Check now`: queues a compact status result every time, including the current blocker when there is no signal.
- `Add trade`: adds a manual swing trade to the dashboard after confirmation.
- `Positions`: lists open swing trades from the dashboard data.
- `Opening report`: queues the swing tracker opening report.
- `Closing report`: queues the swing tracker closing journal/report.
- `Weekly report`: queues the swing tracker weekly open-trades summary.
- `Ideas scan`: queues the strict strategy-ready ideas scan.
- `Swing stops`: immediately checks whether any swing trade reached a manual stop-ladder trigger.
- `Sync buy fill`: shows `/bought PRICE SHARES`.
- `Sync sell fill`: shows `/sold PRICE`.
- `Cash sync help`: shows `/cash AMOUNT`.
- `Button help`: explains the buttons.

TQQQ itself uses Daily/Check plus scheduled signal checks. Opening/Closing/Weekly/Ideas are for the swing tracker repo.

Exact broker fills still require a short command because Telegram buttons cannot collect arbitrary prices. The sync buttons send persistent Telegram messages with the exact command format.

## Telegram Message Meaning

Follow the `Action` line first.

Important lines:

- `Price`: latest TQQQ price used by the bot.
- `SMA200`: long-term trend filter.
- `SMA Confirm`: how many consecutive checks/days confirm above or below SMA200.
- `Trail Stop`: current 15% trailing stop from the highest high since entry.
- `Hard Stop`: permanent 10% stop from entry.
- `Next Profit`: +8% target from average cost.
- `Re-buy`: 3% pullback target from last sell.
- `Re-entry RSI`: off in the current optimized version.
- `QQQ ADX Gate`: anti-chop rule; QQQ ADX must be >= 25 before buying.
- `Market Health`: context only.
- `Parabolic Stretch`: context only.
- `Early Drop Warnings`: context only.
- `Support Break Watch`: context only; shows exact 5-day near support, prior-30 tested support, and whether the tested break is 0/2, 1/2, or 2/2 confirmed.

## Revival Checklist

To resume Telegram alerts in the same chat:

1. Make sure GitHub repo secrets still exist:
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
2. Keep GitHub Actions available for manual/Cloudflare dispatch. Native GitHub cron is intentionally disabled to avoid duplicate scheduled Telegram messages.
3. Deploy the Cloudflare scheduler after restoring its cron triggers.
4. Run the `daily` workflow once to confirm the Telegram chat receives a clean status report.
5. If the broker cash is not exactly `$1,000`, run `manual_cash_set` with the correct amount before taking any signal.
