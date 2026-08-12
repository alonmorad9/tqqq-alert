# TQQQ Swing Alert Bot

Telegram alert bot for a small aggressive TQQQ swing-trading bucket.

Current production style:

- TQQQ only.
- Cash while waiting.
- +8% profit target.
- -10% hard stop.
- 15% trailing stop from the highest high since entry.
- Re-buy after a 3% pullback or 3 trading days.
- Entry requires QQQ ADX >= 25 to avoid weak/choppy Nasdaq conditions.

Full operating notes are in [docs/tqqq-swing-bot-plan.md](docs/tqqq-swing-bot-plan.md).
