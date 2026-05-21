# TQQQ Research Handoff

Last updated: 2026-05-21

## Current Strategy

The repo is intentionally **TQQQ-only**. Out-of-position capital is modeled as cash.

Current live rules:

| Rule | Value |
|---|---:|
| TQQQ trailing stop | 25% |
| Profit target | +20%, sell all |
| Re-buy pullback | -7.5% from exit price |
| Re-buy timeout | 20 trading days |
| Manual safety timeout | 3 trading days |
| Re-entry RSI cap | RSI14 <= 70 |
| Parabolic exit | 5d >= 25% OR 10d >= 30% |
| Waiting state | Cash |
| Early-warning exit | 3-of-5 warnings |

## Historical Research Summary

The selected rule set came from the combined TQQQ strategy searches saved under `research/`.

The best clean live rule family was:

- 25% trailing stop.
- +20% profit target.
- -7.5% pullback re-entry.
- 20 trading-day timeout after normal profit exits.
- 3 trading-day timeout after manual safety sells.
- RSI14 <= 70 re-entry guard.
- Parabolic profit exit using either 5-day or 10-day stretch.
- Cash while waiting.

This was selected because it was the strongest clean TQQQ-only setup among the tested practical variants while keeping the operational behavior simple.

## Operational Notes

The repo should not fetch or report any non-TQQQ waiting asset.

Telegram reports should include:

- Current TQQQ price and price source.
- SMA200.
- TQQQ trailing stop when a position is open.
- Re-entry RSI.
- Cash.
- TQQQ position value.
- Total tracked value.
- Bot-only benchmark.
- Risk context and early-drop risk explanations.

Manual actions:

- `manual_sold`: use after a manual TQQQ sell.
- `manual_bought`: use after a manual TQQQ buy.
- `manual_cash_set`: use after broker cash changes manually.

## Current State Guidance

The user synced a manual broker TQQQ buy on 2026-05-21.

Current inspected state:

- `position_open`: `true`
- `shares`: `35.6658`
- `avg_cost`: `$75.20`
- `entry_date`: `2026-05-21`
- `cash`: `$0.00`
- `last_action`: `manual_broker_buy_sync`

While this position is open, follow the active-position exit/risk rules. If the broker cash or shares differ from `position_state.json`, run the relevant manual sync action.
