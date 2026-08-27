# TQQQ Swing Bot Operating Manual

Last updated: 2026-08-12

## Method

This bot trades TQQQ as a swing instrument, not as a long-term investment.

The core idea is simple:

1. Buy only when the long-term trend is healthy.
2. Take profit quickly at a tested target.
3. Cut failed trades early.
4. Re-enter only after a small pullback or a short timeout.
5. Keep risk-warning sections visible, but do not let noisy advisory signals override the main tested rules.

## Production Rules

| Area | Rule |
|---|---|
| Asset | TQQQ only |
| Trend filter | TQQQ and QQQ above SMA200 |
| Confirmation | 3 confirmed checks/days |
| Anti-chop entry filter | QQQ ADX14 >= 25 |
| Entry RSI | Off |
| Profit exit | Sell all at +8% from entry |
| Hard stop | Sell all at -7.5% from entry |
| Trailing stop | Sell all at -12% from highest high since entry |
| Re-entry after sell | Buy after -3% from sell price or 3 trading days |
| Manual sell recovery | Same: -3% or 3 trading days, with trend and ADX filters |
| Waiting asset | Cash |

## Example Trade

If TQQQ buy signal is at `$100`:

- Profit target: `$108`.
- Hard stop: `$90`.
- Initial trailing stop: about `$85`, based on the highest high since entry.
- If TQQQ rises to `$106`, trailing stop rises to `$90.10`.
- If TQQQ rises to `$108`, bot sends `SELL ALL`.
- After sell at `$108`, re-buy target is `$104.76`, or 3 trading days later if the trend and ADX filters still allow it.

## What The Bot Does Automatically

The bot sends BUY/SELL instructions, but it does not place broker orders and does not auto-fill your real tracked state at the bot's market price.

Real state updates only after you sync the exact broker fill:

- After buying, send `/bought PRICE SHARES`.
- After selling, send `/sold PRICE`.
- If cash changes outside a trade, send `/cash AMOUNT`.

## Telegram Actions

### BUY SIGNAL

Means: bot believes the trend and QQQ ADX filters allow a new TQQQ swing.

What to do:

- Buy TQQQ with the intended bucket size.
- After the broker order fills, send `/bought PRICE SHARES`.

### SELL NOW

Means: one of the real exit rules fired.

What to do:

- Sell all tracked TQQQ shares.
- After the broker order fills, send `/sold PRICE`.

### WAIT

Means: no action. Stay with the current state.

## Telegram Sections

- `Action`: the only part you act on immediately.
- `Mode`: whether the bot is in TQQQ, cash, manual safety mode, or waiting for re-entry.
- `Price`: latest TQQQ price used by the bot.
- `SMA200`: long-term trend line.
- `SMA Confirm`: confirmation count for trend entries/exits.
- `Trail Stop`: 12% below highest high since entry.
- `Hard Stop`: 7.5% below average cost.
- `Next Profit`: +8% target.
- `Re-buy`: 3% below last sell price.
- `Re-entry RSI`: RSI gate is off in the current optimized version.
- `QQQ ADX Gate`: QQQ ADX must be >= 25 before buying; this is the anti-chop filter.
- `Market Health`: advisory context only.
- `Parabolic Stretch`: advisory context only.
- `Early Drop Warnings`: advisory context only.
- `Support Break Watch`: advisory warning for a break below the prior 30-period low. It also shows the 5-day near support for awareness. High means 2/2 confirmations; it does not auto-sell, but it is a prompt to consider manual broker/TradingView protection.

## Manual Sync

Use GitHub Actions `workflow_dispatch`:

- `manual_cash_set`: set cash after moving funds or resetting the bucket.
- `manual_bought`: record an outside broker buy.
- `manual_sold`: record an outside broker sell.
- `daily`: send a full Telegram report.
- `check`: run a signal check.

You can also sync directly from Telegram after the Cloudflare webhook is configured:

- `/bought 75.30 13.2802` syncs an exact broker buy.
- `/sold 82.10` syncs an exact broker sell.
- `/cash 1000` syncs the cash bucket.
- `/daily` queues a full report.
- `/check` queues a signal check.

Report types:

- `Daily report`: full status report right now. It explains current state, why WAIT/HOLD/BUY/SELL, account value, and risk context.
- `Check now`: compact status result. It checks the strategy now and sends a short message every time, including the current blocker when there is no signal.
- Weekly report: not active in this TQQQ swing bot. The active schedule is opening/closing full reports plus 10-minute signal checks.

Telegram uses one persistent keyboard:

- `Sync buy fill`: reminds you to send `/bought PRICE SHARES`.
- `Sync sell fill`: reminds you to send `/sold PRICE`.
- `Daily report`: queues a full Telegram report.
- `Check now`: queues a compact check result.
- `Add trade`: adds a manual swing trade to the dashboard after confirmation.
- `Positions`: lists open swing trades from the dashboard data.
- `Opening report`: queues the swing tracker opening report.
- `Closing report`: queues the swing tracker closing report/digest.
- `Weekly report`: queues the swing tracker weekly summary.
- `Ideas scan`: queues the strict strategy-ready ideas scan.
- `Swing stops`: checks swing tracker stop ladders now.
- `Cash sync help`: shows `/cash AMOUNT`.
- `Help`: explains what each button does.

Telegram buttons cannot enter an exact custom broker price by themselves. Sync buttons send persistent chat messages with examples. For exact fills, use `/bought PRICE SHARES` or `/sold PRICE`; there is no bot-price auto-fill for the real portfolio.

## Revival Steps

1. Confirm `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` secrets still exist in GitHub.
2. Enable `.github/workflows/main.yml`.
3. Confirm Cloudflare Worker secrets exist:
   - `GITHUB_TOKEN`
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. Set Telegram webhook to the Cloudflare Worker URL.
5. Redeploy the Cloudflare scheduler if you want external cron triggering too.
6. Run `manual_cash_set` or Telegram `/cash AMOUNT` if your real bucket is not exactly `$1,000`.
7. Run `daily` or Telegram `/daily` once and confirm the Telegram message arrives in the same chat.

## Important Risk Note

TQQQ is a 3x leveraged ETF. A better bot does not make it safe. This strategy reduced drawdown in the historical test versus wider trailing approaches, but losses can still be fast and uncomfortable.

## Latest Robustness Update

On 2026-08-12, the strategy was retested against the recent choppy two-month window and full-history daily data. The best robust update was:

- Keep +8% profit taking.
- Use a protected -7.5% hard stop and 12% trailing stop.
- Remove the RSI entry cap.
- Add QQQ ADX14 >= 25 as a real entry/re-entry gate.

This won the recent two-month intraday-style test while also improving the full-history result versus the prior live rules. The purpose of ADX is to avoid repeated small stop-outs when Nasdaq is above SMA200 but not trending strongly.
