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
| Entry RSI | RSI14 <= 60 |
| Profit exit | Sell all at +8% from entry |
| Hard stop | Sell all at -7.5% from entry |
| Trailing stop | Sell all at -12% from highest high since entry |
| Re-entry after sell | Buy after -3% from sell price or 3 trading days |
| Manual sell recovery | Same: -3% or 3 trading days, with RSI/trend filters |
| Waiting asset | Cash |

## Example Trade

If TQQQ buy signal is at `$100`:

- Profit target: `$108`.
- Hard stop: `$92.50`.
- Initial trailing stop: about `$88`, based on the highest high since entry.
- If TQQQ rises to `$106`, trailing stop rises to `$93.28`.
- If TQQQ rises to `$108`, bot sends `SELL ALL`.
- After sell at `$108`, re-buy target is `$104.76`, or 3 trading days later if the trend and RSI filters still allow it.

## What The Bot Does Automatically

The bot automatically updates its internal tracked state when it sends a buy or sell signal.

It does not send real broker orders.

You should either:

- Manually place the broker trade when Telegram says `BUY` or `SELL`, or
- Run `manual_bought` / `manual_sold` if your broker execution price differs materially from the bot's tracked price.

## Telegram Actions

### BUY SIGNAL

Means: bot believes the trend and RSI filters allow a new TQQQ swing.

What to do:

- Buy TQQQ with the intended bucket size.
- If your execution price differs from the bot's price, run `manual_bought`.

### SELL NOW

Means: one of the real exit rules fired.

What to do:

- Sell all tracked TQQQ shares.
- If your broker execution price differs from the bot's price, run `manual_sold`.

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
- `Re-entry RSI`: RSI must be <= 60 before buying.
- `Market Health`: advisory context only.
- `Parabolic Stretch`: advisory context only.
- `Early Drop Warnings`: advisory context only.
- `Bot-Only Benchmark`: paper path with no manual overrides.

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

- `Daily report`: full status report right now. It explains current state, why WAIT/HOLD/BUY/SELL, account value, risk context, and benchmark.
- `Check now`: compact status result. It checks the strategy now and sends a short message every time, including the current blocker when there is no signal.
- Weekly report: not active in this TQQQ swing bot. The active schedule is opening/closing full reports plus 10-minute signal checks.

Signal messages include buttons:

- `Bought at bot price`: acknowledgement only. The bot already tracked the buy when it sent the signal.
- `Sold at bot price`: acknowledgement only. The bot already tracked the sell when it sent the signal.
- `Different buy price`: reminds you to send `/bought PRICE SHARES`.
- `Different sell price`: reminds you to send `/sold PRICE`.
- `Daily report`: queues a full Telegram report.
- `Check now`: queues a compact check result.
- `Cash sync help`: shows `/cash AMOUNT`.
- `Button help`: explains what each button does.

Telegram inline buttons cannot enter an exact custom broker price by themselves. Help buttons send persistent chat messages with examples. For exact fills, use `/bought PRICE SHARES` or `/sold PRICE`.

## Revival Steps

1. Confirm `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` secrets still exist in GitHub.
2. Enable `.github/workflows/main.yml`.
3. Confirm Cloudflare Worker secrets exist:
   - `GITHUB_TOKEN`
   - `TELEGRAM_TOKEN`
4. Set Telegram webhook to the Cloudflare Worker URL.
5. Redeploy the Cloudflare scheduler if you want external cron triggering too.
6. Run `manual_cash_set` or Telegram `/cash AMOUNT` if your real bucket is not exactly `$1,000`.
7. Run `daily` or Telegram `/daily` once and confirm the Telegram message arrives in the same chat.

## Important Risk Note

TQQQ is a 3x leveraged ETF. A better bot does not make it safe. This strategy reduced drawdown in the historical test versus wider trailing approaches, but losses can still be fast and uncomfortable.
