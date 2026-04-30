import os
import sys
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

# ── YOUR POSITION ─────────────────────────────────────────
ENTRY_DATE = "2026-04-29"
SHARES = 40.4647
AVG_COST = 61.54
TICKER = "TQQQ"
# ──────────────────────────────────────────────────────────

MARKET_TZ = ZoneInfo("America/New_York")

REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)


def observed_fixed_holiday(year, month, day):
    holiday = datetime(year, month, day).date()
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def nth_weekday(year, month, weekday, n):
    day = datetime(year, month, 1).date()
    while day.weekday() != weekday:
        day += timedelta(days=1)
    return day + timedelta(days=7 * (n - 1))


def last_weekday(year, month, weekday):
    if month == 12:
        day = datetime(year + 1, 1, 1).date() - timedelta(days=1)
    else:
        day = datetime(year, month + 1, 1).date() - timedelta(days=1)
    while day.weekday() != weekday:
        day -= timedelta(days=1)
    return day


def easter_date(year):
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return datetime(year, month, day).date()


def market_holidays(year):
    holidays = {
        observed_fixed_holiday(year, 1, 1),
        nth_weekday(year, 1, 0, 3),
        nth_weekday(year, 2, 0, 3),
        easter_date(year) - timedelta(days=2),
        last_weekday(year, 5, 0),
        observed_fixed_holiday(year, 6, 19),
        observed_fixed_holiday(year, 7, 4),
        nth_weekday(year, 9, 0, 1),
        nth_weekday(year, 11, 3, 4),
        observed_fixed_holiday(year, 12, 25),
        observed_fixed_holiday(year + 1, 1, 1),
    }
    return holidays


def early_close_days(year):
    thanksgiving = nth_weekday(year, 11, 3, 4)
    days = {thanksgiving + timedelta(days=1)}

    christmas_eve = datetime(year, 12, 24).date()
    if christmas_eve.weekday() < 5 and christmas_eve not in market_holidays(year):
        days.add(christmas_eve)

    independence_day = datetime(year, 7, 4).date()
    if independence_day.weekday() in {1, 2, 3, 4}:
        days.add(independence_day - timedelta(days=1))
    elif independence_day.weekday() == 6:
        days.add(independence_day - timedelta(days=2))

    return {day for day in days if day.weekday() < 5 and day not in market_holidays(year)}


def to_utc(trading_day, local_time):
    local_dt = datetime.combine(trading_day, local_time, tzinfo=MARKET_TZ)
    return local_dt.astimezone(UTC)


def get_market_session(trading_day):
    if trading_day.weekday() >= 5 or trading_day in market_holidays(trading_day.year):
        return None

    close_time = EARLY_CLOSE if trading_day in early_close_days(trading_day.year) else REGULAR_CLOSE
    return to_utc(trading_day, REGULAR_OPEN), to_utc(trading_day, close_time)


def parse_exact_cron_time(cron_expr):
    if not cron_expr:
        return None

    parts = cron_expr.split()
    if len(parts) != 5:
        return None

    minute, hour = parts[0], parts[1]
    if not minute.isdigit() or not hour.isdigit():
        return None

    return int(hour), int(minute)


def intended_schedule_time(cron_expr, now_utc=None):
    parsed_time = parse_exact_cron_time(cron_expr)
    if parsed_time is None:
        return None

    now_utc = now_utc or datetime.now(UTC)
    hour, minute = parsed_time
    return datetime.combine(now_utc.date(), time(hour, minute), tzinfo=UTC)


def should_run_intraday_check(intended_utc):
    if intended_utc is None:
        return False, "missing exact scheduled time"

    session = get_market_session(intended_utc.astimezone(MARKET_TZ).date())
    if session is None:
        return False, "NASDAQ is closed"

    market_open, market_close = session
    if not market_open <= intended_utc <= market_close:
        return False, "outside NASDAQ trading hours"

    minutes_since_open = int((intended_utc - market_open).total_seconds() // 60)
    if minutes_since_open % 10 != 0:
        return False, "not on a 10-minute trading interval"

    return True, "10-minute trading interval"


def report_kind_for_schedule(intended_utc):
    if intended_utc is None:
        return None, "missing exact scheduled time"

    session = get_market_session(intended_utc.astimezone(MARKET_TZ).date())
    if session is None:
        return None, "NASDAQ is closed"

    market_open, market_close = session
    report_times = {
        market_open + timedelta(minutes=15): "open",
        market_close - timedelta(minutes=15): "close",
    }

    kind = report_times.get(intended_utc)
    if kind is None:
        return None, "not a report time"

    return kind, f"{kind} report time"


def should_send_daily_report(mode, intended_utc=None):
    if mode == "daily":
        return True, "manual daily run"

    kind, reason = report_kind_for_schedule(intended_utc)
    return kind is not None, reason


def check_strategy(daily_report=False, report_kind=None):
    import pandas as pd
    import yfinance as yf

    ticker = yf.download(TICKER, period="2y", interval="1d", auto_adjust=True)

    if isinstance(ticker.columns, pd.MultiIndex):
        ticker.columns = [c[0] for c in ticker.columns]

    ticker["SMA200"] = ticker["Close"].rolling(window=200).mean()

    current_price = float(ticker["Close"].iloc[-1])
    sma200 = float(ticker["SMA200"].iloc[-1])
    recent_high = float(ticker["High"].tail(30).max())
    trailing_stop = round(recent_high * 0.90, 2)
    prev_price = float(ticker["Close"].iloc[-2])
    prev_sma200 = float(ticker["SMA200"].iloc[-2])
    prev_recent_high = float(ticker["High"].tail(31).iloc[:-1].max())
    prev_trailing_stop = round(prev_recent_high * 0.90, 2)
    hard_stop = round(AVG_COST * 0.95, 2)

    position_value = SHARES * current_price
    cost_basis = SHARES * AVG_COST
    pnl = position_value - cost_basis
    pnl_pct = (pnl / cost_basis) * 100

    # ── SIGNAL DETECTION ──────────────────────────────────
    crossed_below_sma = prev_price >= prev_sma200 and current_price < sma200
    crossed_above_sma = prev_price <= prev_sma200 and current_price > sma200
    hit_trailing_stop = prev_price >= prev_trailing_stop and current_price < trailing_stop
    hit_hard_stop = prev_price >= hard_stop and current_price < hard_stop

    is_signal = hit_trailing_stop or hit_hard_stop or crossed_below_sma or crossed_above_sma

    if hit_trailing_stop:
        action = "🚨 SELL NOW — TRAILING STOP HIT"
    elif hit_hard_stop:
        action = "🚨 SELL NOW — HARD STOP HIT (5% below entry)"
    elif crossed_below_sma:
        action = "🚨 SELL NOW — CROSSED BELOW SMA200"
    elif crossed_above_sma:
        action = "🟢 BUY SIGNAL — PRICE CROSSED ABOVE SMA200"
    elif current_price > sma200 and current_price > trailing_stop:
        action = "✅ HOLD — Above SMA200, stop intact"
    elif current_price < sma200:
        action = "⚠️ CAUTION — Price below SMA200"
    else:
        action = "⚠️ CAUTION — Price near stop level"

    date_str = ticker.index[-1].strftime("%d/%m/%Y")
    pnl_emoji = "🟢" if pnl >= 0 else "🔴"
    gap_to_stop = round(((current_price - trailing_stop) / current_price) * 100, 2)

    # ── DAILY REPORT (full message) ───────────────────────
    if daily_report:
        report_title = "Daily Report"
        if report_kind == "open":
            report_title = "Opening Report"
        elif report_kind == "close":
            report_title = "Closing Report"

        msg = (
            f"📊 TQQQ {report_title} — {date_str}\n"
            f"{'─' * 30}\n"
            f"Action: {action}\n"
            f"{'─' * 30}\n"
            f"💰 Price:        ${current_price:.2f}\n"
            f"📈 SMA200:       ${sma200:.2f}\n"
            f"🛑 Trail Stop:   ${trailing_stop:.2f}  ({gap_to_stop:+.1f}% away)\n"
            f"🔒 Hard Stop:    ${hard_stop:.2f}  (5% below entry)\n"
            f"{'─' * 30}\n"
            f"📦 Shares:       {SHARES}\n"
            f"💵 Avg Cost:     ${AVG_COST:.2f}\n"
            f"💼 Value:        ${position_value:.2f}\n"
            f"{pnl_emoji} P&L:          ${pnl:+.2f} ({pnl_pct:+.2f}%)\n"
            f"{'─' * 30}\n"
            f"Entry Date:      {ENTRY_DATE}\n"
        )
        send_telegram(msg)

    # ── INTRADAY: only send if signal ─────────────────────
    elif is_signal:
        msg = (
            f"{'─' * 30}\n"
            f"{action}\n"
            f"{'─' * 30}\n"
            f"💰 Price:      ${current_price:.2f}\n"
            f"📈 SMA200:     ${sma200:.2f}\n"
            f"🛑 Trail Stop: ${trailing_stop:.2f}\n"
            f"🔒 Hard Stop:  ${hard_stop:.2f}\n"
            f"{pnl_emoji} P&L:        ${pnl:+.2f} ({pnl_pct:+.2f}%)\n"
        )
        send_telegram(msg)

    print(f"[{'DAILY' if daily_report else 'CHECK'}] {action} | Price: {current_price:.2f}")


def send_telegram(message):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=30)
    response.raise_for_status()


def run_auto_mode():
    schedule = os.getenv("GITHUB_EVENT_SCHEDULE")
    intended_utc = intended_schedule_time(schedule)

    daily_report, daily_reason = should_send_daily_report("auto", intended_utc)
    if daily_report:
        report_kind, _ = report_kind_for_schedule(intended_utc)
        print(f"[AUTO] Running {report_kind} report: {daily_reason}")
        check_strategy(daily_report=True, report_kind=report_kind)
        return

    intraday_check, intraday_reason = should_run_intraday_check(intended_utc)
    if intraday_check:
        print(f"[AUTO] Running intraday check: {intraday_reason}")
        check_strategy(daily_report=False)
        return

    print(f"[AUTO] Skipping scheduled run: {daily_reason}; {intraday_reason}")


if __name__ == "__main__":
    # Modes:
    # - auto: scheduled run; decide from cron + NASDAQ calendar
    # - daily: manual full report
    # - check: manual signal-only check
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"

    if mode == "auto":
        run_auto_mode()
    elif mode == "daily":
        check_strategy(daily_report=True)
    else:
        check_strategy(daily_report=False)
