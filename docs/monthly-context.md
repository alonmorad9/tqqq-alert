# TQQQ Alert Bot - Monthly Context

Last updated: 2026-05-14

## English

### What This Repo Does

This repo runs an automated TQQQ alert bot. It checks TQQQ during NASDAQ trading hours, sends Telegram alerts when action is needed, and keeps a small position state file so the strategy can continue over time without manual code changes.

The bot is advisory only. It sends instructions based on the strategy, and the human still places the real trades.

### Current Strategy

The current strategy is a high-risk/high-reward TQQQ swing strategy with an optimized early-warning exit layer:

1. Hold TQQQ while price is above the 200-day SMA.
2. Sell all remaining shares if price crosses below the 200-day SMA.
3. Sell all remaining shares if the true ratcheting 25% trailing stop is hit.
4. Sell all shares when price reaches +20% from the current entry price.
5. After a +20% profit exit, wait to re-buy after a 7.5% pullback from the profit-exit price.
6. If the pullback does not happen within 20 trading days, re-buy anyway as long as price is still above SMA200.
7. Sell all early if the optimized early-drop risk model reaches 3 active warning signs.
8. After an early-warning exit, re-buy only when TQQQ is back above both SMA200 and SMA20.
9. After a stop/SMA200 exit, do not use the pullback rule; wait for the next SMA200 cross-up.
10. Every fresh buy or re-buy also requires TQQQ RSI14 to be at or below 60. This avoids chasing stretched rallies.
11. After every re-entry, the cycle starts again with a new entry price, new trailing stop, and new +20% target.

There is no separate 5% hard stop anymore.

The daily Telegram report also includes an advisory-only parabolic stretch warning. It does not trigger automatic sells. It flags rare spike conditions that historically sometimes led to useful manual profit exits:

- TQQQ 5-trading-day return at or above 25%.
- TQQQ 10-trading-day return at or above 30%.

The early-warning sell model checks five signals:

- VIX is at or above 25.
- VIX rose 25% or more over the last 5 trading days.
- QQQ is below its EMA21.
- TQQQ is below its SMA50.
- TQQQ RSI14 is falling after being at or above 70.

If at least 3 of these 5 signals are active while a position is open, the bot sends a sell-all instruction and moves into early-risk recovery mode.

Manual safety mode is optional and does not run unless triggered manually from GitHub Actions. It is used only if the human manually/panic sells outside the normal strategy. In that case, the bot records the manual sell price and will not immediately re-buy just because TQQQ is still above SMA200. It waits for either:

- A 7.5% pullback from the manual sell price while TQQQ is still above SMA200.
- Or a full SMA200 reset: price goes below SMA200 first, then later crosses back above SMA200.
- Or, after 20 trading days, a trend re-entry while TQQQ is still above SMA200.

The RSI14 re-entry guard still applies in manual safety mode. Even if the manual pullback, SMA200 reset, or 20-day timeout is ready, the bot waits until RSI14 is 60 or lower before sending a re-buy instruction.

### Waiting Asset While Out Of TQQQ

On 2026-05-14, historical tests compared temporary "waiting assets" for periods when the bot is out of TQQQ and waiting for re-entry. `SGOV`/`BIL` were rejected because the expected short holding period is too small relative to broker/tax friction.

Corrected test window: 2010-11-24 through 2026-05-13.

| Waiting Asset | Final Multiple | CAGR | Max Drawdown | Interpretation |
| --- | ---: | ---: | ---: | --- |
| Cash | 38.2x | 26.6% | -47.7% | Missed too much upside |
| QQQ | 134.8x | 37.3% | -45.7% | Good simple option |
| XLK | 151.3x | 38.3% | -44.2% | Selected default waiting asset |
| VGT | 148.1x | 38.1% | -44.9% | Very close to XLK |
| SMH | 216.7x | 41.6% | -54.6% | More return, more risk |
| QLD | 218.9x | 41.7% | -66.5% | Too leveraged for waiting mode |
| USD | 308.2x | 44.9% | -79.0% | Too dangerous for waiting mode |

Decision: use `XLK` as the preferred waiting asset when the bot is out of TQQQ but the human still wants large-cap tech exposure. The bot does not buy or sell XLK automatically for the real account. It only shows the suggested waiting asset and tracks it if manually recorded.

Manual XLK tracking modes:

- `manual_parking_bought` with `manual_price=<actual XLK buy price>` and optional `manual_shares=<actual XLK shares>`.
- `manual_parking_sold` with `manual_price=<actual XLK sell price>`.

Flow:

1. If the bot exits TQQQ, sell TQQQ manually.
2. If you want the waiting-asset plan, buy XLK manually.
3. Run `manual_parking_bought` so the bot tracks XLK value in the real path.
4. When the bot later sends a TQQQ re-entry signal, sell XLK manually and buy TQQQ manually.
5. Run `manual_parking_sold`, then `manual_bought` with the actual TQQQ buy price.

XLK sell rules:

- Sell XLK and move back to TQQQ when the normal TQQQ re-entry signal triggers.
- Sell XLK and wait in cash if TQQQ falls below SMA200.
- Sell XLK and wait in cash if the early-drop risk model reaches 3 active warning signs.
- Sell XLK and wait in cash if XLK hits its own 5% ratcheting trailing stop, calculated from the highest XLK high since the XLK waiting-asset entry.

The bot-only benchmark behaves differently: it automatically simulates moving into XLK after bot exits if TQQQ is still above SMA200 and early-drop risk is not high, moves from XLK back into TQQQ on bot re-entry, and moves from XLK to cash if TQQQ becomes defensive or the XLK 5% trailing stop is hit. This keeps the benchmark as "only follow bot rules, no manual decisions."

The trailing stop is now:

> Highest high since entry x 0.75

It only moves upward while the position is open. It resets after a full exit and starts again after the next re-entry.

### Why This Strategy Was Chosen

Historical TQQQ tests originally showed that profit-taking helped the strategy compound better than no profit-taking.

On 2026-05-05, a more active swing version was tested. The goal was to sell into strength, wait for a pullback, and then re-buy while the trend remains healthy.

The selected swing rule is:

> Sell all at +20%, then re-buy after a 7.5% pullback from the sell price, or after 20 trading days if TQQQ is still above SMA200.

Historical comparison from 2010-11-24 through 2026-05-01:

| Strategy | Final Multiple | CAGR | Max Drawdown |
| --- | ---: | ---: | ---: |
| Previous strategy: +125%, sell 90% | 77.8x | 32.6% | -42.7% |
| Swing +10%, re-buy after -3%, 20-day timeout | 36.6x | 26.3% | -44.6% |
| Swing +25%, re-buy after -5%, 20-day timeout | 52.2x | 29.2% | -42.7% |
| Swing +20%, re-buy after -7.5%, 20-day timeout | 97.4x | 34.5% | -42.4% |

The +10% swing version was rejected because it traded too often and reduced compounding. The +20% / -7.5% version was selected because it improved the full-history result without increasing historical max drawdown.

Important caveat: this is more active than the previous strategy. It may underperform during very strong uninterrupted bull runs because it sells earlier and waits for re-entry.

This is still a volatile strategy. A roughly 50% drawdown happened historically even with the improved rules.

On 2026-05-03, trailing stop variants were retested from 2010-11-24 through 2026-05-01. The best simple stop improvement was replacing the old rolling 30-day high minus 35% stop with a true 25% ratchet from the highest high since entry:

| Strategy | Final Multiple | CAGR | Max Drawdown |
| --- | ---: | ---: | ---: |
| Old rolling 30-day high -35% stop | 46.5x | 28.3% | -42.7% |
| Exact low -4x ATR14 stop | 11.1x | 16.9% | -42.4% |
| Exact low -8x ATR14 stop | 61.6x | 30.6% | -42.7% |
| Highest high since entry -25% stop | 66.0x | 31.2% | -42.7% |

The chosen stop is therefore the 25% true ratchet. ATR-based stops were tested, but the useful ATR version had to be very wide and still did not beat the simpler 25% ratchet.

On 2026-05-06, an early-warning strategy search was run from 2010-11-24 through 2026-05-06 using TQQQ, QQQ, and VIX. The selected version was the best return version that also improved drawdown versus the local current-swing baseline:

| Strategy | Final Multiple | CAGR | Max Drawdown | Trades | Early Exits |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current swing baseline in this test | 36.7x | 26.3% | -49.5% | 164 | 0 |
| Early warning: 3-of-5 risk model | 85.8x | 33.4% | -46.1% | 240 | 49 |
| Early warning: simpler best Calmar version | 75.1x | 32.3% | -44.0% | 228 | 42 |

Decision: switch the live bot to the best-return early-warning version because the real position is currently in cash. This is more active and may create more alerts, but historically it improved both final return and drawdown in the 2026-05-06 test.

On 2026-05-12, extra re-entry guard variants were tested from 2010-11-24 through 2026-05-12. The best practical improvement was to keep the same exit rules but require RSI14 <= 60 before any fresh buy or re-buy:

| Strategy | Final Multiple | CAGR | Max Drawdown | Trades |
| --- | ---: | ---: | ---: | ---: |
| Current early-warning strategy before RSI guard | 85.8x | 33.4% | -46.1% | 240 |
| Add RSI14 <= 60 re-entry guard | 82.1x | 33.0% | -26.0% | 116 |

Decision: add the RSI14 <= 60 re-entry guard. It gave up only a small amount of historical return while cutting historical max drawdown dramatically. It is especially relevant when TQQQ is very stretched and the real account is in cash.

Also on 2026-05-12, parabolic stretch exits were checked. The 5-day >= 25% and 10-day >= 30% rules improved the historical result in isolation, but each fired only once in more than 15 years. Decision: do not make them automatic sell rules yet. Add them to the Telegram report as advisory warnings only, so a human can decide whether to manually take profit during an unusually sharp spike.

Manual safety mode was also updated after testing strict manual re-entry, RSI-only re-entry, and hybrid timeout variants. The selected practical rule is: keep the strict manual pullback/reset first, but after 20 trading days allow re-entry above SMA200 if RSI14 <= 60. This avoids immediately chasing after a manual sell while reducing the risk of being stuck in cash for months.

### Current Position State

The live state is stored in `position_state.json`.

Current live state as of 2026-05-12 after the manual sell while in cash:

```json
{
  "avg_cost": null,
  "cash": 2726.11,
  "early_exit_date": null,
  "early_exit_price": null,
  "entry_date": null,
  "highest_high_since_entry": null,
  "last_action": "manual_sold",
  "parking_avg_cost": null,
  "parking_shares": 0.0,
  "parking_ticker": "XLK",
  "manual_exit_date": "2026-05-05",
  "manual_exit_mode": true,
  "manual_exit_price": 67.37,
  "manual_exit_saw_below_sma": false,
  "position_open": false,
  "profit_exit_date": null,
  "shares": 0.0,
  "ticker": "TQQQ",
  "waiting_for_early_reentry": false,
  "waiting_for_pullback": false,
  "last_profit_sell_price": null
}
```

Meaning:

- The bot assumes there is no open TQQQ position.
- The previous real position was manually sold at `$67.37`.
- Tracked cash is `$2726.11`.
- Manual safety mode is active.
- The bot waits for the manual pullback target or SMA200 reset.
- Re-buy also requires RSI14 <= 60.

If real trades are made manually, `position_state.json` must match reality.

### Bot-Only Benchmark

The repo also keeps `bot_strategy_state.json`. This file tracks a paper benchmark:

> What would have happened if Alon only followed the bot strategy and made no manual moves?

This benchmark started from the same original position:

- Entry date: `2026-04-29`
- Shares: `40.4647`
- Average cost: `$61.54`

Unlike `position_state.json`, this file ignores manual/panic sells. It only follows the deterministic bot rules: +20% profit exit, 25% trailing stop, SMA200 exit, and the strategy's own re-entry rules.

As of 2026-05-14, the benchmark also simulates the selected waiting-asset behavior: after bot exits TQQQ, it parks the benchmark value in XLK until the next bot re-entry signal. This is paper-only and does not imply the real account bought XLK.

Daily reports include a `Bot-Only Benchmark` section with the benchmark total and the difference versus the real path. At month-end, compare:

- Real path: `position_state.json`
- Bot-only path: `bot_strategy_state.json`

### Scheduling

GitHub's native scheduled workflow was removed because it was unreliable. The current scheduler is a Cloudflare Worker.

Worker:

- Name: `tqqq-alert-scheduler`
- URL: `https://tqqq-alert-scheduler.alonmorad-tqqq.workers.dev`
- Worker file: `scheduler/cloudflare/worker.js`
- Config: `scheduler/cloudflare/wrangler.toml`

Cloudflare cron schedules:

```toml
"*/10 13-21 * * MON-FRI"
"45 13-20 * * MON-FRI"
```

Cloudflare weekday numbers are different from GitHub, so weekday names are used to avoid accidentally excluding Fridays.

On 2026-05-01, the scheduler did not run on Friday because the old Cloudflare cron used `1-5`. In Cloudflare, weekday numbers start with Sunday, so that meant Sunday-Thursday. The fix was to use `MON-FRI`. After redeploying, the Cloudflare schedule was confirmed working.

The Cloudflare Worker dispatches the GitHub workflow with:

- `mode=auto`
- `schedule=<the Cloudflare cron expression>`

The Python script then decides whether the run is actually valid for NASDAQ trading hours.

Manual safety mode is triggered only through GitHub Actions `workflow_dispatch`:

- `mode=manual_sold`
- `manual_price=<actual sell price>`

This is not used by the Cloudflare scheduler.

Manual XLK waiting-asset tracking is also triggered only through GitHub Actions `workflow_dispatch`:

- `mode=manual_parking_bought`
- `manual_price=<actual XLK buy price>`
- optional `manual_shares=<actual XLK shares>`

And when XLK is sold:

- `mode=manual_parking_sold`
- `manual_price=<actual XLK sell price>`

Expected behavior:

- Intraday checks happen every 10 minutes during NASDAQ trading hours.
- Daily reports happen 15 minutes after market open and 15 minutes before market close.
- On normal full trading days, that means approximately:
  - Opening report: 09:45 New York time.
  - Closing report: 15:45 New York time.
- On early-close days, the close report should happen 15 minutes before the early close.

### Telegram Behavior

Intraday checks:

- Usually do not send a Telegram message.
- They send only if there is a real signal, such as sell, buy, or profit-taking.

Daily reports:

- Send a full Telegram status message.
- Include current price, SMA200, trailing stop, position mode, cash, shares, total value, P&L, next profit target, and pullback re-entry target if waiting after a profit exit.
- If there is no open TQQQ position, include XLK waiting-asset guidance and any tracked XLK shares/value.
- Include the price source. During market hours, the bot overlays Yahoo's latest 1-minute TQQQ bar on top of the daily history so it does not rely on yesterday's close. If the latest 1-minute price is stale by more than 30 minutes while the market is open, the run fails and sends a workflow-failure alert instead of trading on stale data.
- Include an advisory risk context section inspired by the TradingAgents idea: trend, RSI momentum, ATR volatility, a 4x ATR reference stop, and risk level.
- This risk context is not a trading trigger. Buy/sell/profit-taking instructions still come only from the deterministic strategy rules.

Failure alerts:

- If the GitHub workflow fails, it should send a Telegram warning with a link to the failed run.

### Most Important Files

- `script.py` - main strategy, Telegram messages, market calendar, and state updates.
- `position_state.json` - live position state.
- `bot_strategy_state.json` - paper benchmark for the no-manual-moves bot strategy.
- `.github/workflows/main.yml` - GitHub Action that runs the bot.
- `scheduler/cloudflare/worker.js` - external scheduler that triggers GitHub.
- `scheduler/cloudflare/wrangler.toml` - Cloudflare cron configuration.
- `docs/external-scheduler.md` - setup instructions for the Cloudflare scheduler.

### Recent Important Commits

- `f2434b6` - Fix Cloudflare weekday schedule.
- `91b2fe9` - Add Cloudflare scheduler logging.
- `71cd3dd` - Add native schedule backup.
- `93d7ef6` - Fix report distance signs.
- `176c310` - Update workflow actions.
- `ce81d23` - Add monitoring alerts.
- `e47de1e` - Add persistent position management.
- `42223a7` - Pass scheduler cron to workflow.
- `5f99620` - Use Cloudflare as workflow scheduler.
- `b6ccf0c` - Update TQQQ exit strategy.

### What To Check Next Month

1. Confirm Cloudflare scheduled runs triggered GitHub Actions reliably.
2. Confirm daily opening and closing reports arrived at the expected times.
3. Confirm no unexpected workflow failures occurred.
4. Confirm `position_state.json` still matches the real brokerage position.
5. Review whether any buy, sell, or profit-taking alerts were sent.
6. Compare bot-reported price, SMA200, trailing stop, and next profit target against current market data.
7. If a manual/panic sell happened, confirm manual safety mode has the correct manual sell price and re-buy target.
8. Compare `position_state.json` against `bot_strategy_state.json` to see whether manual behavior helped or hurt versus only following the bot.
9. Decide whether to keep the current strategy unchanged for another month.

### Do Not Change Lightly

Avoid changing the strategy numbers too often. The current setup was chosen because it was simple, historically strong, and repeatable. Frequent optimization can lead to overfitting.

Possible future improvements, only if needed:

- Add a second price data source as fallback if Yahoo/yfinance becomes unreliable.
- Add a weekly summary report.
- Add a small dashboard or log file.
- Log the daily risk context over time and later backtest whether risk warnings actually helped.
- Add more robust state reconciliation if real trades differ from bot instructions.

---

## עברית

### מה הריפו הזה עושה

הריפו הזה מפעיל בוט התראות אוטומטי ל-TQQQ. הוא בודק את TQQQ בזמן שעות המסחר של נאסד"ק, שולח התראות לטלגרם כשצריך פעולה, ושומר קובץ מצב קטן כדי שהאסטרטגיה תוכל להמשיך לאורך זמן בלי שינוי ידני בקוד.

הבוט הוא כלי עזר בלבד. הוא שולח הנחיות לפי האסטרטגיה, והפעולות האמיתיות עדיין מבוצעות ידנית על ידי המשתמש.

### האסטרטגיה הנוכחית

האסטרטגיה הנוכחית היא אסטרטגיית סווינג על TQQQ עם סיכון גבוה וסיכוי גבוה, בתוספת שכבת יציאה מוקדמת לפי סיכון:

1. להחזיק TQQQ כל עוד המחיר מעל SMA200.
2. למכור את כל שאר המניות אם המחיר חוצה למטה את SMA200.
3. למכור את כל שאר המניות אם הטריילינג סטופ האמיתי של 25% מופעל.
4. למכור את כל המניות כשהמחיר מגיע ל-+20% ממחיר הכניסה הנוכחי.
5. אחרי יציאת רווח של +20%, לחכות לכניסה מחדש אחרי ירידה של 7.5% ממחיר המכירה.
6. אם הירידה לא מגיעה תוך 20 ימי מסחר, להיכנס מחדש בכל זאת כל עוד המחיר עדיין מעל SMA200.
7. למכור הכל מוקדם אם מודל הסיכון המוקדם מגיע ל-3 סימני אזהרה פעילים.
8. אחרי יציאת early-warning, להיכנס מחדש רק כש-TQQQ חוזרת מעל SMA200 וגם מעל SMA20.
9. אחרי יציאה בגלל סטופ או SMA200, לא משתמשים בכלל ה-pullback; מחכים לחצייה חדשה מעל SMA200.
10. כל קנייה חדשה או כניסה מחדש דורשת גם RSI14 של TQQQ שווה או נמוך מ-60. זה נועד למנוע כניסה אחרי ראלי מתוח מדי.
11. אחרי כל כניסה מחדש, המחזור מתחיל מחדש עם מחיר כניסה חדש, טריילינג סטופ חדש, ויעד רווח חדש של +20%.

אין יותר סטופ קשיח נפרד של 5%.

בדוח היומי לטלגרם יש גם אזהרת parabolic stretch לצורך מידע בלבד. היא לא גורמת למכירה אוטומטית. היא מסמנת מצבי זינוק נדירים שבהיסטוריה לפעמים עזרו כנקודת יציאה ידנית:

- תשואת TQQQ ב-5 ימי מסחר שווה או מעל 25%.
- תשואת TQQQ ב-10 ימי מסחר שווה או מעל 30%.

מודל המכירה המוקדמת בודק חמישה סימנים:

- VIX שווה או מעל 25.
- VIX עלה 25% או יותר ב-5 ימי המסחר האחרונים.
- QQQ מתחת ל-EMA21.
- TQQQ מתחת ל-SMA50.
- RSI14 של TQQQ יורד אחרי שהיה 70 ומעלה.

אם לפחות 3 מתוך 5 הסימנים פעילים בזמן שיש פוזיציה פתוחה, הבוט שולח הוראת מכירה מלאה ונכנס למצב המתנה להתאוששות סיכון.

מצב בטיחות ידני הוא אופציונלי ולא פועל אלא אם מפעילים אותו ידנית דרך GitHub Actions. משתמשים בו רק אם האדם מוכר ידנית/מפאניקה מחוץ לאסטרטגיה הרגילה. במקרה כזה, הבוט שומר את מחיר המכירה הידני ולא יקנה מיד בחזרה רק כי TQQQ עדיין מעל SMA200. הוא מחכה לאחד משני דברים:

- ירידה של 7.5% ממחיר המכירה הידני, כל עוד TQQQ עדיין מעל SMA200.
- או איפוס SMA200 מלא: המחיר יורד קודם מתחת ל-SMA200, ואז בהמשך חוצה בחזרה מעל SMA200.
- או, אחרי 20 ימי מסחר, כניסה מחדש לפי מגמה כל עוד TQQQ עדיין מעל SMA200.

גם במצב בטיחות ידני כלל ה-RSI14 עדיין חל. גם אם יעד ה-pullback הידני, איפוס SMA200, או timeout של 20 ימי מסחר מוכנים, הבוט יחכה עד ש-RSI14 יהיה 60 או נמוך יותר לפני שליחת הוראת קנייה מחדש.

### נכס המתנה מחוץ ל-TQQQ

ב-2026-05-14 נבדקו היסטורית נכסי המתנה זמניים לתקופות שבהן הבוט מחוץ ל-TQQQ ומחכה לכניסה מחדש. `SGOV`/`BIL` נדחו כי בתקופת המתנה קצרה הצפי לרווח קטן מדי ביחס לעלויות/מס/חיכוך.

חלון בדיקה מתוקן: 2010-11-24 עד 2026-05-13.

| נכס המתנה | מכפיל סופי | תשואה שנתית | ירידה מקסימלית | פירוש |
| --- | ---: | ---: | ---: | --- |
| מזומן | 38.2x | 26.6% | -47.7% | מפספס יותר מדי אפסייד |
| QQQ | 134.8x | 37.3% | -45.7% | אופציה פשוטה וטובה |
| XLK | 151.3x | 38.3% | -44.2% | נכס ההמתנה שנבחר |
| VGT | 148.1x | 38.1% | -44.9% | קרוב מאוד ל-XLK |
| SMH | 216.7x | 41.6% | -54.6% | יותר תשואה, יותר סיכון |
| QLD | 218.9x | 41.7% | -66.5% | ממונף מדי למצב המתנה |
| USD | 308.2x | 44.9% | -79.0% | מסוכן מדי למצב המתנה |

החלטה: להשתמש ב-`XLK` כנכס ההמתנה המועדף כשהבוט מחוץ ל-TQQQ אבל רוצים עדיין חשיפה לטכנולוגיה גדולה. הבוט לא קונה או מוכר XLK אוטומטית בחשבון האמיתי. הוא רק מציג את ההמלצה ועוקב אחרי XLK אם הפעולה נרשמה ידנית.

מצבי מעקב ידניים ל-XLK:

- `manual_parking_bought` עם `manual_price=<actual XLK buy price>` ואופציונלית `manual_shares=<actual XLK shares>`.
- `manual_parking_sold` עם `manual_price=<actual XLK sell price>`.

הזרימה:

1. אם הבוט יוצא מ-TQQQ, מוכרים TQQQ ידנית.
2. אם רוצים את תוכנית נכס ההמתנה, קונים XLK ידנית.
3. מריצים `manual_parking_bought` כדי שהבוט יעקוב אחרי ערך XLK במסלול האמיתי.
4. כשהבוט שולח בהמשך איתות כניסה ל-TQQQ, מוכרים XLK ידנית וקונים TQQQ ידנית.
5. מריצים `manual_parking_sold`, ואז `manual_bought` עם מחיר הקנייה האמיתי של TQQQ.

כללי מכירה ל-XLK:

- למכור XLK ולעבור בחזרה ל-TQQQ כשמופיע איתות כניסה רגיל ל-TQQQ.
- למכור XLK ולהמתין במזומן אם TQQQ יורדת מתחת ל-SMA200.
- למכור XLK ולהמתין במזומן אם מודל ה-early-drop risk מגיע ל-3 סימני אזהרה פעילים.
- למכור XLK ולהמתין במזומן אם XLK מפעילה טריילינג סטופ עצמאי של 5%, שמחושב מהשיא הגבוה ביותר של XLK מאז הכניסה לנכס ההמתנה.

הבנצ'מרק של Bot-Only מתנהג אחרת: הוא מדמה אוטומטית מעבר ל-XLK אחרי יציאת בוט אם TQQQ עדיין מעל SMA200 וסיכון early-drop לא גבוה, חזרה מ-XLK ל-TQQQ באיתות הכניסה הבא, ומעבר מ-XLK למזומן אם TQQQ נהיית דפנסיבית או אם סטופ XLK של 5% מופעל. זה על הנייר בלבד ולא אומר שהחשבון האמיתי קנה XLK.

הטריילינג סטופ עכשיו הוא:

> המחיר הגבוה ביותר מאז הכניסה x 0.75

הסטופ רק עולה בזמן שהפוזיציה פתוחה. אחרי מכירה מלאה הוא מתאפס, ומתחיל מחדש אחרי הכניסה הבאה.

### למה בחרנו באסטרטגיה הזו

בדיקות היסטוריות הראו שלקיחת רווח עוזרת לאסטרטגיה יותר מאשר לא לקחת רווח בכלל.

ב-2026-05-05 נבדקה גרסת סווינג אקטיבית יותר. המטרה הייתה למכור לתוך חוזקה, לחכות לירידה, ואז להיכנס מחדש כל עוד המגמה עדיין בריאה.

כלל הסווינג שנבחר:

> למכור הכל ב-+20%, ואז להיכנס מחדש אחרי ירידה של 7.5% ממחיר המכירה, או אחרי 20 ימי מסחר אם TQQQ עדיין מעל SMA200.

השוואה היסטורית מ-2010-11-24 עד 2026-05-01:

| אסטרטגיה | מכפיל סופי | תשואה שנתית | ירידה מקסימלית |
| --- | ---: | ---: | ---: |
| אסטרטגיה קודמת: +125%, למכור 90% | 77.8x | 32.6% | -42.7% |
| סווינג +10%, כניסה אחרי -3%, timeout של 20 יום | 36.6x | 26.3% | -44.6% |
| סווינג +25%, כניסה אחרי -5%, timeout של 20 יום | 52.2x | 29.2% | -42.7% |
| סווינג +20%, כניסה אחרי -7.5%, timeout של 20 יום | 97.4x | 34.5% | -42.4% |

גרסת ה-+10% נדחתה כי היא סוחרת יותר מדי ופוגעת בקומפאונדינג. גרסת +20% / -7.5% נבחרה כי היא שיפרה את התוצאה ההיסטורית המלאה בלי להגדיל את הירידה המקסימלית ההיסטורית.

הערה חשובה: זו אסטרטגיה אקטיבית יותר מהקודמת. היא יכולה לפגר בתקופות של שוק שורי חזק בלי תיקונים, כי היא מוכרת מוקדם יותר ומחכה לכניסה מחדש.

זו עדיין אסטרטגיה תנודתית. גם עם הכללים המשופרים הייתה היסטורית ירידה של בערך 50%.

ב-2026-05-03 בדקנו מחדש וריאציות של טריילינג סטופ מ-2010-11-24 עד 2026-05-01. השיפור הכי טוב והכי פשוט היה להחליף את הסטופ הישן של rolling 30-day high פחות 35% בטריילינג סטופ אמיתי של 25% מהשיא מאז הכניסה:

| אסטרטגיה | מכפיל סופי | תשואה שנתית | ירידה מקסימלית |
| --- | ---: | ---: | ---: |
| סטופ ישן: שיא 30 יום פחות 35% | 46.5x | 28.3% | -42.7% |
| סטופ ATR: low -4x ATR14 | 11.1x | 16.9% | -42.4% |
| סטופ ATR: low -8x ATR14 | 61.6x | 30.6% | -42.7% |
| שיא מאז הכניסה פחות 25% | 66.0x | 31.2% | -42.7% |

לכן הסטופ שנבחר הוא טריילינג אמיתי של 25%. נבדקו גם סטופים לפי ATR, אבל הגרסה הטובה הייתה צריכה להיות רחבה מאוד ועדיין לא ניצחה את כלל ה-25% הפשוט.

ב-2026-05-06 הורץ חיפוש אסטרטגיות early-warning מ-2010-11-24 עד 2026-05-06 על TQQQ, QQQ ו-VIX. הגרסה שנבחרה הייתה גרסת התשואה הטובה ביותר שגם שיפרה את הירידה המקסימלית לעומת בסיס הסווינג המקומי:

| אסטרטגיה | מכפיל סופי | תשואה שנתית | ירידה מקסימלית | עסקאות | יציאות מוקדמות |
| --- | ---: | ---: | ---: | ---: | ---: |
| בסיס סווינג בבדיקה הזו | 36.7x | 26.3% | -49.5% | 164 | 0 |
| Early warning: מודל סיכון 3 מתוך 5 | 85.8x | 33.4% | -46.1% | 240 | 49 |
| Early warning: גרסת Calmar פשוטה יותר | 75.1x | 32.3% | -44.0% | 228 | 42 |

החלטה: להעביר את הבוט החי לגרסת ה-early-warning עם התשואה הטובה ביותר, כי הפוזיציה האמיתית כרגע במזומן. זו גרסה אקטיבית יותר ועלולה לשלוח יותר התראות, אבל בבדיקה ההיסטורית של 2026-05-06 היא שיפרה גם תשואה וגם drawdown.

ב-2026-05-12 נבדקו וריאציות נוספות של כניסה מחדש מ-2010-11-24 עד 2026-05-12. השיפור הפרקטי הכי טוב היה להשאיר את כללי היציאה כפי שהם, אבל לדרוש RSI14 <= 60 לפני כל קנייה חדשה או קנייה מחדש:

| אסטרטגיה | מכפיל סופי | תשואה שנתית | ירידה מקסימלית | עסקאות |
| --- | ---: | ---: | ---: | ---: |
| אסטרטגיית early-warning לפני כלל RSI | 85.8x | 33.4% | -46.1% | 240 |
| הוספת כלל כניסה RSI14 <= 60 | 82.1x | 33.0% | -26.0% | 116 |

החלטה: להוסיף את כלל הכניסה RSI14 <= 60. הוויתור ההיסטורי בתשואה היה קטן, אבל הירידה המקסימלית ההיסטורית ירדה משמעותית. זה רלוונטי במיוחד כש-TQQQ מתוחה מאוד והחשבון האמיתי במזומן.

גם ב-2026-05-12 נבדקו יציאות בגלל parabolic stretch. כללי 5 ימים >= 25% ו-10 ימים >= 30% שיפרו את התוצאה ההיסטורית בנפרד, אבל כל אחד הופעל רק פעם אחת ביותר מ-15 שנה. החלטה: לא להפוך אותם לכללי מכירה אוטומטיים עדיין. להוסיף אותם לדוח הטלגרם כאזהרות מידע בלבד, כדי שהאדם יוכל להחליט אם לממש ידנית בזמן זינוק חריג מאוד.

מצב בטיחות ידני עודכן גם אחרי בדיקה של כניסה ידנית קשיחה, כניסה לפי RSI בלבד, וגרסאות timeout היברידיות. הכלל הפרקטי שנבחר: קודם לשמור על pullback/reset ידני קשיח, אבל אחרי 20 ימי מסחר לאפשר כניסה מחדש מעל SMA200 אם RSI14 <= 60. זה מונע קנייה מיידית אחרי מכירה ידנית, אבל מקטין את הסיכון להיתקע במזומן חודשים.

### מצב הפוזיציה הנוכחי

המצב החי נשמר בקובץ `position_state.json`.

מצב חי נכון ל-2026-05-12 אחרי המכירה הידנית בזמן שהחשבון במזומן:

```json
{
  "avg_cost": null,
  "cash": 2726.11,
  "early_exit_date": null,
  "early_exit_price": null,
  "entry_date": null,
  "highest_high_since_entry": null,
  "last_action": "manual_sold",
  "manual_exit_date": "2026-05-05",
  "manual_exit_mode": true,
  "manual_exit_price": 67.37,
  "manual_exit_saw_below_sma": false,
  "position_open": false,
  "profit_exit_date": null,
  "shares": 0.0,
  "ticker": "TQQQ",
  "waiting_for_early_reentry": false,
  "waiting_for_pullback": false,
  "last_profit_sell_price": null
}
```

המשמעות:

- הבוט מניח שאין פוזיציה פתוחה ב-TQQQ.
- הפוזיציה האמיתית הקודמת נמכרה ידנית במחיר `$67.37`.
- המזומן במעקב הוא `$2726.11`.
- מצב בטיחות ידני פעיל.
- הבוט מחכה ליעד ה-pullback הידני או לאיפוס SMA200.
- קנייה מחדש דורשת גם RSI14 <= 60.

אם מבוצעות פעולות אמיתיות בתיק, חשוב ש-`position_state.json` יתאים למציאות.

### השוואת Bot-Only

הריפו שומר גם את `bot_strategy_state.json`. הקובץ הזה עוקב אחרי בנצ'מרק על הנייר:

> מה היה קורה אם אלון היה עושה רק את מה שהבוט אומר, בלי פעולות ידניות?

הבנצ'מרק התחיל מאותה פוזיציה מקורית:

- תאריך כניסה: `2026-04-29`
- מניות: `40.4647`
- מחיר ממוצע: `$61.54`

בניגוד ל-`position_state.json`, הקובץ הזה מתעלם ממכירות ידניות/פאניקה. הוא עוקב רק אחרי חוקי הבוט הדטרמיניסטיים: יציאת רווח ב-+20%, טריילינג סטופ של 25%, יציאת SMA200, וכללי הכניסה מחדש של האסטרטגיה.

בדוחות היומיים מופיע אזור `Bot-Only Benchmark` עם הערך של הבנצ'מרק וההפרש מול המסלול האמיתי. בסוף החודש נשווה:

- מסלול אמיתי: `position_state.json`
- מסלול בוט בלבד: `bot_strategy_state.json`

### תזמון

התזמון המקורי של GitHub Actions הוסר כי הוא לא היה אמין מספיק. התזמון הנוכחי מתבצע דרך Cloudflare Worker.

Worker:

- שם: `tqqq-alert-scheduler`
- כתובת: `https://tqqq-alert-scheduler.alonmorad-tqqq.workers.dev`
- קובץ Worker: `scheduler/cloudflare/worker.js`
- קונפיגורציה: `scheduler/cloudflare/wrangler.toml`

תזמוני Cloudflare:

```toml
"*/10 13-21 * * MON-FRI"
"45 13-20 * * MON-FRI"
```

מספרי ימי השבוע ב-Cloudflare שונים מ-GitHub, ולכן משתמשים בשמות ימים כדי לא להוציא בטעות את יום שישי.

ב-2026-05-01 הסקדולר לא רץ ביום שישי כי ה-cron הישן של Cloudflare השתמש ב-`1-5`. ב-Cloudflare מספרי הימים מתחילים מיום ראשון, ולכן זה היה ראשון-חמישי. התיקון היה להשתמש ב-`MON-FRI`. אחרי deploy מחדש, התזמון של Cloudflare אומת כעובד.

ה-Cloudflare Worker מפעיל את GitHub workflow עם:

- `mode=auto`
- `schedule=<the Cloudflare cron expression>`

אחר כך הסקריפט בפייתון מחליט אם ההרצה באמת רלוונטית לשעות המסחר של נאסד"ק.

מצב בטיחות ידני מופעל רק דרך `workflow_dispatch` ב-GitHub Actions:

- `mode=manual_sold`
- `manual_price=<actual sell price>`

ה-Cloudflare scheduler לא משתמש בזה.

התנהגות צפויה:

- בדיקות תוך-יומיות מתבצעות כל 10 דקות בזמן המסחר של נאסד"ק.
- דוחות יומיים נשלחים 15 דקות אחרי פתיחת המסחר ו-15 דקות לפני סגירת המסחר.
- ביום מסחר רגיל:
  - דוח פתיחה: 09:45 שעון ניו יורק.
  - דוח סגירה: 15:45 שעון ניו יורק.
- ביום מסחר מקוצר, דוח הסגירה אמור להישלח 15 דקות לפני הסגירה המוקדמת.

### התנהגות טלגרם

בדיקות תוך-יומיות:

- בדרך כלל לא שולחות הודעת טלגרם.
- הן שולחות הודעה רק אם יש איתות אמיתי, כמו מכירה, קנייה, או לקיחת רווח.

דוחות יומיים:

- שולחים הודעת סטטוס מלאה לטלגרם.
- כוללים מחיר נוכחי, SMA200, טריילינג סטופ, מצב פוזיציה, מזומן, מניות, ערך כולל, רווח/הפסד, יעד הרווח הבא, ויעד כניסה מחדש אם מחכים אחרי יציאת רווח.
- כוללים את מקור המחיר. בזמן המסחר, הבוט משתמש בבר 1 דקה האחרון של Yahoo על גבי ההיסטוריה היומית, כדי לא להסתמך בטעות על מחיר הסגירה של אתמול. אם מחיר ה-1 דקה האחרון ישן ביותר מ-30 דקות בזמן שהשוק פתוח, ההרצה נכשלת ושולחת התראת כשל במקום לפעול על מחיר לא עדכני.
- כוללים גם אזור הקשר סיכון בהשראת רעיון TradingAgents: מגמה, מומנטום RSI, תנודתיות ATR, סטופ ייחוס של 4x ATR, ורמת סיכון.
- הקשר הסיכון הוא מידע בלבד ולא טריגר למסחר. הוראות קנייה/מכירה/לקיחת רווח עדיין מגיעות רק מכללי האסטרטגיה הדטרמיניסטיים.

התראות כשל:

- אם ה-GitHub workflow נכשל, אמורה להישלח התראת טלגרם עם קישור להרצה שנכשלה.

### הקבצים החשובים ביותר

- `script.py` - האסטרטגיה הראשית, הודעות טלגרם, לוח מסחר, ועדכוני מצב.
- `position_state.json` - מצב הפוזיציה החי.
- `bot_strategy_state.json` - בנצ'מרק על הנייר לאסטרטגיית הבוט בלי פעולות ידניות.
- `.github/workflows/main.yml` - GitHub Action שמריץ את הבוט.
- `scheduler/cloudflare/worker.js` - הסקדולר החיצוני שמפעיל את GitHub.
- `scheduler/cloudflare/wrangler.toml` - הגדרות התזמון של Cloudflare.
- `docs/external-scheduler.md` - הוראות ההקמה של הסקדולר החיצוני.

### קומיטים חשובים אחרונים

- `93d7ef6` - תיקון סימני מרחק בדוח.
- `176c310` - עדכון גרסאות GitHub Actions.
- `ce81d23` - הוספת התראות ניטור.
- `e47de1e` - הוספת ניהול פוזיציה מתמשך.
- `42223a7` - העברת cron מהסקדולר ל-workflow.
- `5f99620` - מעבר ל-Cloudflare כסקדולר.
- `b6ccf0c` - עדכון אסטרטגיית יציאה ב-TQQQ.

### מה לבדוק בחודש הבא

1. לוודא שההרצות המתוזמנות של Cloudflare הפעילו את GitHub Actions בצורה אמינה.
2. לוודא שדוחות הפתיחה והסגירה הגיעו בזמנים הצפויים.
3. לוודא שלא היו כשלונות workflow לא צפויים.
4. לוודא ש-`position_state.json` עדיין תואם לפוזיציה האמיתית בחשבון.
5. לבדוק אם נשלחו איתותי קנייה, מכירה, או לקיחת רווח.
6. להשוות את המחיר, SMA200, הטריילינג סטופ ויעד הרווח הבא לנתוני שוק עדכניים.
7. אם הייתה מכירה ידנית/פאניקה, לוודא שמצב הבטיחות הידני שמר את מחיר המכירה ואת יעד הכניסה מחדש הנכון.
8. להשוות בין `position_state.json` לבין `bot_strategy_state.json` כדי להבין אם ההתנהלות הידנית עזרה או פגעה ביחס לביצוע מדויק של הוראות הבוט.
9. להחליט האם להשאיר את האסטרטגיה ללא שינוי לחודש נוסף.

### לא לשנות בקלות

עדיף לא לשנות את מספרי האסטרטגיה לעיתים קרובות. ההגדרות הנוכחיות נבחרו כי הן פשוטות, חזקות היסטורית, וניתנות להפעלה חוזרת. אופטימיזציה תכופה מדי עלולה לגרום להתאמת יתר להיסטוריה.

שיפורים אפשריים בעתיד, רק אם יהיה צורך:

- להוסיף מקור מחירים נוסף לגיבוי אם Yahoo/yfinance יהפוך ללא אמין.
- להוסיף דוח שבועי.
- להוסיף דשבורד קטן או קובץ לוג.
- לשמור את הקשר הסיכון היומי לאורך זמן, ואז לבדוק היסטורית אם אזהרות הסיכון באמת עזרו.
- להוסיף מנגנון התאמה טוב יותר אם הפעולות האמיתיות שונות מהוראות הבוט.
