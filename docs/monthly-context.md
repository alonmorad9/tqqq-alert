# TQQQ Alert Bot - Monthly Context

Last updated: 2026-04-30

## English

### What This Repo Does

This repo runs an automated TQQQ alert bot. It checks TQQQ during NASDAQ trading hours, sends Telegram alerts when action is needed, and keeps a small position state file so the strategy can continue over time without manual code changes.

The bot is advisory only. It sends instructions based on the strategy, and the human still places the real trades.

### Current Strategy

The current strategy is a high-risk/high-reward long-term TQQQ strategy:

1. Hold TQQQ while price is above the 200-day SMA.
2. Sell all remaining shares if price crosses below the 200-day SMA.
3. Sell all remaining shares if the 35% trailing stop is hit.
4. Re-enter when price crosses back above the 200-day SMA.
5. Take profit repeatedly: every time price reaches another +100% from the entry price, sell 50% of the remaining shares.
6. After a full exit, the bot waits for the next re-entry signal and starts the cycle again.

There is no separate 5% hard stop anymore.

### Why This Strategy Was Chosen

Historical TQQQ tests from 2010-11-24 through 2026-04-30 showed:

| Strategy | Final Multiple | CAGR | Max Drawdown |
| --- | ---: | ---: | ---: |
| No profit taking | 73.1x | 32.1% | -49.5% |
| Every +50%, sell 25% | 103.1x | 35.0% | -49.5% |
| Every +100%, sell 50% | 108.1x | 35.5% | -49.5% |

The selected rule is therefore:

> Every +100% gain from entry, sell 50% of the remaining shares.

Smaller profit-taking rules were tested too. They can feel better emotionally because they act more often, but historically they reduced compounding or did not improve risk enough to justify the extra activity.

This is still a volatile strategy. A roughly 50% drawdown happened historically even with the improved rules.

### Current Position State

The live state is stored in `position_state.json`.

Current starting state as of 2026-04-30:

```json
{
  "avg_cost": 61.54,
  "cash": 0.0,
  "entry_date": "2026-04-29",
  "last_action": null,
  "last_action_at": null,
  "next_profit_multiple": 2.0,
  "position_open": true,
  "shares": 40.4647,
  "ticker": "TQQQ"
}
```

Meaning:

- The bot assumes there is an open TQQQ position.
- Average cost is `$61.54`.
- Shares are `40.4647`.
- The next profit-taking target is `2.0x` the entry price, around `$123.08`.
- If a full exit happens, the bot will track cash and later tell when to re-enter.

If real trades are made manually, `position_state.json` must match reality.

### Scheduling

GitHub's native scheduled workflow was removed because it was unreliable. The current scheduler is a Cloudflare Worker.

Worker:

- Name: `tqqq-alert-scheduler`
- URL: `https://tqqq-alert-scheduler.alonmorad-tqqq.workers.dev`
- Worker file: `scheduler/cloudflare/worker.js`
- Config: `scheduler/cloudflare/wrangler.toml`

Cloudflare cron schedules:

```toml
"*/10 13-21 * * 1-5"
"45 13-20 * * 1-5"
```

The Cloudflare Worker dispatches the GitHub workflow with:

- `mode=auto`
- `schedule=<the Cloudflare cron expression>`

The Python script then decides whether the run is actually valid for NASDAQ trading hours.

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
- Include current price, SMA200, trailing stop, position mode, cash, shares, total value, P&L, and next profit target.

Failure alerts:

- If the GitHub workflow fails, it should send a Telegram warning with a link to the failed run.

### Most Important Files

- `script.py` - main strategy, Telegram messages, market calendar, and state updates.
- `position_state.json` - live position state.
- `.github/workflows/main.yml` - GitHub Action that runs the bot.
- `scheduler/cloudflare/worker.js` - external scheduler that triggers GitHub.
- `scheduler/cloudflare/wrangler.toml` - Cloudflare cron configuration.
- `docs/external-scheduler.md` - setup instructions for the Cloudflare scheduler.

### Recent Important Commits

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
7. Decide whether to keep the current strategy unchanged for another month.

### Do Not Change Lightly

Avoid changing the strategy numbers too often. The current setup was chosen because it was simple, historically strong, and repeatable. Frequent optimization can lead to overfitting.

Possible future improvements, only if needed:

- Add a second price data source as fallback if Yahoo/yfinance becomes unreliable.
- Add a weekly summary report.
- Add a small dashboard or log file.
- Add more robust state reconciliation if real trades differ from bot instructions.

---

## עברית

### מה הריפו הזה עושה

הריפו הזה מפעיל בוט התראות אוטומטי ל-TQQQ. הוא בודק את TQQQ בזמן שעות המסחר של נאסד"ק, שולח התראות לטלגרם כשצריך פעולה, ושומר קובץ מצב קטן כדי שהאסטרטגיה תוכל להמשיך לאורך זמן בלי שינוי ידני בקוד.

הבוט הוא כלי עזר בלבד. הוא שולח הנחיות לפי האסטרטגיה, והפעולות האמיתיות עדיין מבוצעות ידנית על ידי המשתמש.

### האסטרטגיה הנוכחית

האסטרטגיה הנוכחית היא אסטרטגיית TQQQ לטווח ארוך עם סיכון גבוה וסיכוי גבוה:

1. להחזיק TQQQ כל עוד המחיר מעל SMA200.
2. למכור את כל שאר המניות אם המחיר חוצה למטה את SMA200.
3. למכור את כל שאר המניות אם הטריילינג סטופ של 35% מופעל.
4. להיכנס מחדש כשהמחיר חוצה בחזרה מעל SMA200.
5. לקחת רווח שוב ושוב: בכל פעם שהמחיר מגיע לעוד +100% ממחיר הכניסה, למכור 50% מהמניות שנותרו.
6. אחרי יציאה מלאה, הבוט מחכה לאיתות כניסה חדש ומתחיל את המחזור מחדש.

אין יותר סטופ קשיח נפרד של 5%.

### למה בחרנו באסטרטגיה הזו

בדיקות היסטוריות על TQQQ מתאריך 2010-11-24 עד 2026-04-30 הראו:

| אסטרטגיה | מכפיל סופי | תשואה שנתית | ירידה מקסימלית |
| --- | ---: | ---: | ---: |
| בלי לקיחת רווח | 73.1x | 32.1% | -49.5% |
| כל +50%, למכור 25% | 103.1x | 35.0% | -49.5% |
| כל +100%, למכור 50% | 108.1x | 35.5% | -49.5% |

לכן הכלל שנבחר הוא:

> בכל +100% רווח ממחיר הכניסה, למכור 50% מהמניות שנותרו.

נבדקו גם כללים עם לקיחת רווח קטנה ותכופה יותר. הם יכולים להרגיש יותר נוחים כי יש יותר פעולות, אבל היסטורית הם פגעו בקומפאונדינג או לא שיפרו מספיק את הסיכון.

זו עדיין אסטרטגיה תנודתית. גם עם הכללים המשופרים הייתה היסטורית ירידה של בערך 50%.

### מצב הפוזיציה הנוכחי

המצב החי נשמר בקובץ `position_state.json`.

מצב התחלתי נכון ל-2026-04-30:

```json
{
  "avg_cost": 61.54,
  "cash": 0.0,
  "entry_date": "2026-04-29",
  "last_action": null,
  "last_action_at": null,
  "next_profit_multiple": 2.0,
  "position_open": true,
  "shares": 40.4647,
  "ticker": "TQQQ"
}
```

המשמעות:

- הבוט מניח שיש פוזיציה פתוחה ב-TQQQ.
- מחיר ממוצע הוא `$61.54`.
- כמות המניות היא `40.4647`.
- יעד לקיחת הרווח הבא הוא `2.0x` ממחיר הכניסה, בערך `$123.08`.
- אם תהיה יציאה מלאה, הבוט יעקוב אחרי המזומן ויגיד מתי להיכנס מחדש.

אם מבוצעות פעולות אמיתיות בתיק, חשוב ש-`position_state.json` יתאים למציאות.

### תזמון

התזמון המקורי של GitHub Actions הוסר כי הוא לא היה אמין מספיק. התזמון הנוכחי מתבצע דרך Cloudflare Worker.

Worker:

- שם: `tqqq-alert-scheduler`
- כתובת: `https://tqqq-alert-scheduler.alonmorad-tqqq.workers.dev`
- קובץ Worker: `scheduler/cloudflare/worker.js`
- קונפיגורציה: `scheduler/cloudflare/wrangler.toml`

תזמוני Cloudflare:

```toml
"*/10 13-21 * * 1-5"
"45 13-20 * * 1-5"
```

ה-Cloudflare Worker מפעיל את GitHub workflow עם:

- `mode=auto`
- `schedule=<the Cloudflare cron expression>`

אחר כך הסקריפט בפייתון מחליט אם ההרצה באמת רלוונטית לשעות המסחר של נאסד"ק.

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
- כוללים מחיר נוכחי, SMA200, טריילינג סטופ, מצב פוזיציה, מזומן, מניות, ערך כולל, רווח/הפסד, ויעד הרווח הבא.

התראות כשל:

- אם ה-GitHub workflow נכשל, אמורה להישלח התראת טלגרם עם קישור להרצה שנכשלה.

### הקבצים החשובים ביותר

- `script.py` - האסטרטגיה הראשית, הודעות טלגרם, לוח מסחר, ועדכוני מצב.
- `position_state.json` - מצב הפוזיציה החי.
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
7. להחליט האם להשאיר את האסטרטגיה ללא שינוי לחודש נוסף.

### לא לשנות בקלות

עדיף לא לשנות את מספרי האסטרטגיה לעיתים קרובות. ההגדרות הנוכחיות נבחרו כי הן פשוטות, חזקות היסטורית, וניתנות להפעלה חוזרת. אופטימיזציה תכופה מדי עלולה לגרום להתאמת יתר להיסטוריה.

שיפורים אפשריים בעתיד, רק אם יהיה צורך:

- להוסיף מקור מחירים נוסף לגיבוי אם Yahoo/yfinance יהפוך ללא אמין.
- להוסיף דוח שבועי.
- להוסיף דשבורד קטן או קובץ לוג.
- להוסיף מנגנון התאמה טוב יותר אם הפעולות האמיתיות שונות מהוראות הבוט.
