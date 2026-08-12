# TQQQ Swing Research Handoff

Last updated: 2026-08-12

## Decision

The repo has been converted back to a clean **TQQQ-only swing alert bot**.

Selected production profile:

- Profit target: `+8%`.
- Hard stop: `-10%` from entry.
- Trailing stop: `-15%` from highest high since entry.
- Re-entry: `-3%` from last sell price or `3` trading days.
- Manual-sell timeout: `3` trading days.
- RSI entry cap: off.
- Anti-chop entry filter: `QQQ ADX14 >= 25`.
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

Previous swing setup on `$1,000`:

- Multiple: `71.2x`.
- CAGR: `31.2%`.
- Max drawdown: `-34.7%`.
- Win rate: `59.4%`.
- Trades: `395`.

Latest robust candidate after choppy-market retest:

- Rules: `+8%` profit, `-10%` hard stop, `15%` trail, no RSI cap, `QQQ ADX14 >= 25`.
- Full-history multiple: `233.1x`.
- Full-history CAGR: `41.5%`.
- Full-history max drawdown: `-35.4%`.
- Full-history win rate: `72.0%`.
- Recent two-month intraday-style result: `+20.9%` versus `-19.4%` for the prior live rules.
- Recent two-month max drawdown: `-18.7%` versus `-28.7%` for the prior live rules.

Walk-forward sanity check:

- `2011-2014`: candidate `2.90x`, prior live `1.97x`.
- `2015-2018`: candidate `3.47x`, prior live `2.35x`.
- `2019-2022`: candidate `4.67x`, prior live `3.39x`.
- `2023-now`: candidate `5.52x`, prior live `3.37x`.
- `2025-now`: candidate `1.99x`, prior live `1.43x`.

Interpretation: `QQQ ADX >= 25` is not just a recent overfit in this test set. It avoided recent chop and improved all broad walk-forward periods tested. It should still be treated as aggressive because TQQQ itself remains a 3x leveraged ETF.

## Implementation Notes

The legacy `fresh_entry_guard` function name remains in code for compatibility, but its behavior is now the permanent hard stop:

- `active`: while position is open.
- `stop`: `avg_cost * 0.90`.
- `hit`: current price <= stop.

Do not reintroduce the old first-two-days guard unless a new backtest proves it.

All normal exits, including hard stop, trailing stop, and SMA200 exit, now enter the same swing re-entry path:

- Store `last_profit_sell_price`.
- Set `waiting_for_pullback = true`.
- Wait for 3% pullback or 3 trading days, with trend and ADX gates.

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
