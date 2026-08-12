# TQQQ Swing Research Handoff

Last updated: 2026-08-12

## Decision

The repo has been converted back to a clean **TQQQ-only swing alert bot**.

Selected production profile:

- Profit target: `+8%`.
- Hard stop: `-7.5%` from entry.
- Trailing stop: `-12%` from highest high since entry.
- Re-entry: `-3%` from last sell price or `3` trading days.
- Manual-sell timeout: `3` trading days.
- RSI entry cap: `RSI14 <= 60`.
- SMA200 confirmation: `3` confirmed checks/days.
- Waiting asset: cash.
- Early-warning/parabolic/fibonacci sections: advisory only.

## Why This Replaced The Old Strategy

The old repo had drifted into a wide trend-following / max-return style:

- 25% trailing stop.
- 25% profit target.
- 10-day timeout.
- RSI <= 70.

That produced attractive theoretical returns in some broad grids, but it did not match the user's desired behavior after experiencing large TQQQ drawdowns. The user now wants a smaller swing bucket that takes profits often and cuts failed trades earlier.

## Backtest Result

Selected swing setup on `$1,000`:

- Final: `$70,718`.
- Multiple: `70.7x`.
- CAGR: `33.6%`.
- Max drawdown: `-28.6%`.
- Win rate: `60.6%`.
- Trades: `360`.
- Exits: `180`.

Exit mix:

- Profit exits: `109`.
- Hard stops: `45`.
- Trailing stops: `22`.
- SMA200 exits: `4`.

Key comparisons:

- A `10%` profit target made less money and had deeper drawdown.
- A `6%` profit target churned too much and made less money.
- A `15%` trailing stop made less money and had worse drawdown.
- A `5%` hard stop created too many whipsaws.
- RSI <= 65 allowed too many hot re-entries compared with RSI <= 60.

## Implementation Notes

The legacy `fresh_entry_guard` function name remains in code for compatibility, but its behavior is now the permanent hard stop:

- `active`: while position is open.
- `stop`: `avg_cost * 0.925`.
- `hit`: current price <= stop.

Do not reintroduce the old first-two-days guard unless a new backtest proves it.

All normal exits, including hard stop, trailing stop, and SMA200 exit, now enter the same swing re-entry path:

- Store `last_profit_sell_price`.
- Set `waiting_for_pullback = true`.
- Wait for 3% pullback or 3 trading days, with trend and RSI gates.

## Operational Notes

State was reset to:

- Real tracked path: `$1,000` cash, no TQQQ position.
- Bot-only benchmark: `$1,000` cash, no TQQQ position.

If real broker cash differs, run `manual_cash_set`.

To revive the same Telegram chat, use the same GitHub secrets:

- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`

Then enable the GitHub Actions workflow and redeploy the Cloudflare scheduler.

Cloudflare Worker requirements:

- `GITHUB_TOKEN` secret: dispatches GitHub workflows.
- `TELEGRAM_TOKEN` secret: answers Telegram button taps and command responses.
- Telegram webhook should point to the deployed worker URL.

Telegram commands:

- `/bought PRICE SHARES`
- `/sold PRICE`
- `/cash AMOUNT`
- `/daily`
- `/check`

Inline buttons on BUY/SELL messages are no-op confirmations or command helpers. The bot has already updated its internal state when it sends the original signal.
