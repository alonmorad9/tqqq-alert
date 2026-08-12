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
| Hard stop | Sell all at -7.5% from entry |
| Trailing stop | Sell all at -12% from highest high since entry |
| Re-buy pullback | Buy after -3% from last sell price |
| Re-buy timeout | 3 trading days |
| Manual sell timeout | 3 trading days |
| Re-entry RSI cap | RSI14 <= 60 |
| Waiting asset | Cash only |
| Early warnings | Advisory only |
| Fibonacci / patterns | Research context only, not automatic |

## Backtest Summary

Historical test from TQQQ inception using daily data:

| Strategy | Final On $1,000 | CAGR | Max DD | Win Rate | Trades |
|---|---:|---:|---:|---:|---:|
| Selected swing strategy | `$70,718` | `33.6%` | `-28.6%` | `60.6%` | `360` |
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

Interpretation: this is still aggressive, but it behaves much more like a swing system than the old 25% trailing/large-profit setup.

## How The Trade Works

### When In Cash

The bot waits for:

- Trend confirmed above SMA200.
- Re-entry RSI ready: `RSI14 <= 60`.
- If after a prior sell: either price drops 3% from the sell price, or 3 trading days pass.
- No bot buy during the first 30 minutes after market open.

When ready, Telegram sends a `BUY SIGNAL` or `RE-BUY SIGNAL`.

### When In TQQQ

The bot watches:

- `+8%` profit target.
- `-7.5%` hard stop from entry.
- `-12%` trailing stop from highest high since entry.
- Confirmed SMA200 weakness.

If any real exit rule is hit, Telegram sends a `SELL NOW` message and the bot state moves to cash.

### After A Sell

The bot waits in cash for the next re-entry:

- Price down 3% from sell price, or
- 3 trading days pass,
- and trend/RSI filters allow the buy.

## Manual Workflow

GitHub Actions manual modes:

- `daily`: send a full Telegram status report.
- `check`: run a signal-only check.
- `manual_cash_set`: sync cash after broker changes.
- `manual_bought`: tell the bot you bought TQQQ manually.
- `manual_sold`: tell the bot you sold TQQQ manually.

The bot does not place broker orders. It updates its tracked state and sends Telegram instructions. You still place the trade manually unless you later connect broker automation.

Telegram sync shortcuts, after the Cloudflare webhook is configured:

- `/bought PRICE SHARES`: sync exact broker buy.
- `/sold PRICE`: sync exact broker sell.
- `/cash AMOUNT`: sync cash bucket.
- `/daily`: queue a full report.
- `/check`: queue a signal check.

Signal buttons are acknowledgements/helpers only. The bot does not wait for a button before updating its tracked state.

## Telegram Message Meaning

Follow the `Action` line first.

Important lines:

- `Price`: latest TQQQ price used by the bot.
- `SMA200`: long-term trend filter.
- `SMA Confirm`: how many consecutive checks/days confirm above or below SMA200.
- `Trail Stop`: current 12% trailing stop from the highest high since entry.
- `Hard Stop`: permanent 7.5% stop from entry.
- `Next Profit`: +8% target from average cost.
- `Re-buy`: 3% pullback target from last sell.
- `Re-entry RSI`: whether RSI is cool enough to buy.
- `Market Health`: context only.
- `Parabolic Stretch`: context only.
- `Early Drop Warnings`: context only.
- `Bot-Only Benchmark`: what would have happened with no manual overrides.

## Revival Checklist

To resume Telegram alerts in the same chat:

1. Make sure GitHub repo secrets still exist:
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
2. Enable the GitHub Actions workflow `main.yml`.
3. If using the Cloudflare scheduler, deploy the worker after restoring its cron triggers.
4. Run the `daily` workflow once to confirm the Telegram chat receives a clean status report.
5. If the broker cash is not exactly `$1,000`, run `manual_cash_set` with the correct amount before taking any signal.
