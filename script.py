import json
import os
import sys
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# ── YOUR POSITION ─────────────────────────────────────────
ENTRY_DATE = "2026-04-29"
SHARES = 40.4647
AVG_COST = 61.54
TICKER = "TQQQ"
# ──────────────────────────────────────────────────────────

STATE_FILE = Path("position_state.json")
MARKET_TZ = ZoneInfo("America/New_York")
TRAILING_STOP_PCT = 0.25
INITIAL_PROFIT_MULTIPLE = 2.25
PROFIT_STEP_PCT = 1.25
PROFIT_SELL_FRACTION = 0.90

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


def report_kind_near_time(now_utc, tolerance=timedelta(minutes=30)):
    session = get_market_session(now_utc.astimezone(MARKET_TZ).date())
    if session is None:
        return None, "NASDAQ is closed"

    market_open, market_close = session
    report_times = {
        market_open + timedelta(minutes=15): "open",
        market_close - timedelta(minutes=15): "close",
    }

    for report_time, kind in report_times.items():
        if report_time <= now_utc <= report_time + tolerance:
            return kind, f"{kind} report time"

    return None, "not near a report time"


def is_market_open(now_utc):
    session = get_market_session(now_utc.astimezone(MARKET_TZ).date())
    if session is None:
        return False, "NASDAQ is closed"

    market_open, market_close = session
    if market_open <= now_utc <= market_close:
        return True, "NASDAQ trading hours"

    return False, "outside NASDAQ trading hours"


def should_send_daily_report(mode, intended_utc=None):
    if mode == "daily":
        return True, "manual daily run"

    kind, reason = report_kind_for_schedule(intended_utc)
    return kind is not None, reason


def default_state():
    return {
        "ticker": TICKER,
        "position_open": True,
        "entry_date": ENTRY_DATE,
        "avg_cost": AVG_COST,
        "shares": SHARES,
        "cash": 0.0,
        "highest_high_since_entry": None,
        "next_profit_multiple": INITIAL_PROFIT_MULTIPLE,
        "last_action": None,
        "last_action_at": None,
        "last_report_key": None,
    }


def load_state():
    if not STATE_FILE.exists():
        return default_state()

    with STATE_FILE.open() as f:
        state = json.load(f)

    merged = default_state()
    merged.update(state)
    return merged


def save_state(state):
    state["last_action_at"] = datetime.now(UTC).isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def fetch_market_data():
    import pandas as pd
    import yfinance as yf

    ticker = yf.download(TICKER, period="2y", interval="1d", auto_adjust=True)

    if isinstance(ticker.columns, pd.MultiIndex):
        ticker.columns = [c[0] for c in ticker.columns]

    if ticker.empty:
        raise RuntimeError(f"No market data returned for {TICKER}")

    ticker["SMA200"] = ticker["Close"].rolling(window=200).mean()
    ticker["SMA20"] = ticker["Close"].rolling(window=20).mean()
    ticker["SMA50"] = ticker["Close"].rolling(window=50).mean()
    ticker["SMA60"] = ticker["Close"].rolling(window=60).mean()
    ticker["RSI14"] = calculate_rsi(ticker["Close"], 14)

    prev_close = ticker["Close"].shift(1)
    true_range = pd.concat([
        ticker["High"] - ticker["Low"],
        (ticker["High"] - prev_close).abs(),
        (ticker["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    ticker["ATR14"] = true_range.rolling(window=14).mean()
    return ticker


def calculate_rsi(close, window):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=window).mean()
    loss = (-delta.clip(upper=0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def money(value):
    return f"${value:.2f}"


def date_only(value):
    if hasattr(value, "date"):
        return value.date()
    return datetime.fromisoformat(str(value)).date()


def initialize_highest_high_since_entry(state, ticker):
    if not state.get("position_open"):
        return None

    existing_high = state.get("highest_high_since_entry")
    if existing_high is not None:
        return float(existing_high)

    entry_date = state.get("entry_date")
    if not entry_date:
        return float(ticker["High"].iloc[-1])

    entry_day = datetime.fromisoformat(entry_date).date()
    highs_since_entry = ticker[ticker.index.map(date_only) >= entry_day]["High"]
    if highs_since_entry.empty:
        return float(ticker["High"].iloc[-1])

    return float(highs_since_entry.max())


def calculate_trailing_stop(highest_high):
    if highest_high is None:
        return None
    return round(float(highest_high) * (1 - TRAILING_STOP_PCT), 2)


def build_risk_context(ticker, current_price, sma200, trailing_stop):
    sma20 = float(ticker["SMA20"].iloc[-1])
    sma50 = float(ticker["SMA50"].iloc[-1])
    sma60 = float(ticker["SMA60"].iloc[-1])
    rsi14 = float(ticker["RSI14"].iloc[-1])
    atr14 = float(ticker["ATR14"].iloc[-1])
    atr_pct = (atr14 / current_price) * 100 if current_price else 0.0
    atr_stop_4x = current_price - (4 * atr14)

    above_count = sum(current_price > value for value in [sma20, sma50, sma60, sma200])
    if above_count == 4:
        trend = "Strong bullish"
    elif above_count >= 3:
        trend = "Bullish"
    elif current_price > sma200:
        trend = "Mixed but above SMA200"
    else:
        trend = "Defensive"

    if rsi14 >= 75:
        momentum = "Very extended"
    elif rsi14 >= 70:
        momentum = "Extended"
    elif rsi14 >= 55:
        momentum = "Healthy"
    elif rsi14 >= 45:
        momentum = "Cooling"
    else:
        momentum = "Weak"

    risk_points = 0
    risk_notes = []
    if rsi14 >= 75:
        risk_points += 1
        risk_notes.append("RSI very high")
    elif rsi14 >= 70:
        risk_notes.append("RSI extended")

    if current_price < sma20:
        risk_points += 1
        risk_notes.append("below SMA20")
    if atr_pct >= 8:
        risk_points += 1
        risk_notes.append("very high ATR")
    elif atr_pct >= 5:
        risk_notes.append("high ATR")
    if trailing_stop is not None and current_price <= trailing_stop * 1.15:
        risk_points += 2
        risk_notes.append("near trailing stop")
    elif current_price <= sma200 * 1.08:
        risk_points += 1
        risk_notes.append("near SMA200")

    if risk_points >= 3:
        risk_level = "High"
    elif risk_points >= 1:
        risk_level = "Elevated"
    else:
        risk_level = "Normal"

    notes = ", ".join(risk_notes) if risk_notes else "no major warning"
    return [
        "🧭 Risk Context: advisory only",
        f"Trend:         {trend}",
        f"Momentum:      {momentum} (RSI14 {rsi14:.1f})",
        f"ATR14:         ${atr14:.2f} ({atr_pct:.1f}% daily range)",
        f"ATR Ref Stop:  ${atr_stop_4x:.2f} (4x ATR, not active)",
        f"Risk Level:    {risk_level} — {notes}",
    ]


def check_strategy(daily_report=False, report_kind=None, dedupe_report=False):
    state = load_state()
    ticker = fetch_market_data()

    current_price = float(ticker["Close"].iloc[-1])
    current_high = float(ticker["High"].iloc[-1])
    sma200 = float(ticker["SMA200"].iloc[-1])
    prev_price = float(ticker["Close"].iloc[-2])
    prev_sma200 = float(ticker["SMA200"].iloc[-2])

    position_open = bool(state["position_open"])
    shares = float(state["shares"])
    avg_cost = float(state["avg_cost"]) if state["avg_cost"] is not None else 0.0
    cash = float(state.get("cash", 0.0))
    next_profit_multiple = float(state.get("next_profit_multiple", INITIAL_PROFIT_MULTIPLE))
    state_changed = False
    state_dirty = False
    highest_high_since_entry = initialize_highest_high_since_entry(state, ticker)
    if position_open:
        updated_high = max(highest_high_since_entry or current_high, current_high)
        if state.get("highest_high_since_entry") != round(updated_high, 4):
            highest_high_since_entry = updated_high
            state["highest_high_since_entry"] = round(highest_high_since_entry, 4)
            state_dirty = True
    trailing_stop = calculate_trailing_stop(highest_high_since_entry)

    position_value = shares * current_price
    cost_basis = shares * avg_cost
    total_value = cash + position_value
    pnl = position_value - cost_basis if position_open else 0.0
    pnl_pct = (pnl / cost_basis) * 100 if cost_basis else 0.0

    # ── SIGNAL DETECTION ──────────────────────────────────
    crossed_below_sma = prev_price >= prev_sma200 and current_price < sma200
    crossed_above_sma = prev_price <= prev_sma200 and current_price > sma200
    hit_trailing_stop = trailing_stop is not None and current_price < trailing_stop
    hit_profit_target = (
        position_open
        and shares > 0
        and avg_cost > 0
        and current_price >= avg_cost * next_profit_multiple
    )

    action = None
    instruction_lines = []

    if position_open and hit_trailing_stop:
        sell_shares = shares
        cash += sell_shares * current_price
        shares = 0.0
        state.update({
            "position_open": False,
            "shares": shares,
            "cash": round(cash, 2),
            "avg_cost": None,
            "entry_date": None,
            "highest_high_since_entry": None,
            "next_profit_multiple": INITIAL_PROFIT_MULTIPLE,
            "last_action": "sell_all_trailing_stop",
        })
        state_changed = True
        action = "🚨 SELL NOW — TRAILING STOP HIT"
        instruction_lines.append(f"Sell all remaining shares: {sell_shares:.4f}")
    elif position_open and crossed_below_sma:
        sell_shares = shares
        cash += sell_shares * current_price
        shares = 0.0
        state.update({
            "position_open": False,
            "shares": shares,
            "cash": round(cash, 2),
            "avg_cost": None,
            "entry_date": None,
            "highest_high_since_entry": None,
            "next_profit_multiple": INITIAL_PROFIT_MULTIPLE,
            "last_action": "sell_all_sma200",
        })
        state_changed = True
        action = "🚨 SELL NOW — CROSSED BELOW SMA200"
        instruction_lines.append(f"Sell all remaining shares: {sell_shares:.4f}")
    elif position_open and hit_profit_target:
        sell_shares = shares * PROFIT_SELL_FRACTION
        cash += sell_shares * current_price
        shares -= sell_shares
        target_pct = int(round((next_profit_multiple - 1) * 100))
        state.update({
            "position_open": True,
            "shares": round(shares, 6),
            "cash": round(cash, 2),
            "next_profit_multiple": round(next_profit_multiple + PROFIT_STEP_PCT, 4),
            "last_action": f"profit_trim_{target_pct}",
        })
        state_changed = True
        action = f"💰 TAKE PROFIT — +{target_pct}% TARGET HIT"
        sell_pct = int(round(PROFIT_SELL_FRACTION * 100))
        instruction_lines.append(f"Sell {sell_pct}% of remaining shares: {sell_shares:.4f}")
        instruction_lines.append(f"Keep riding with: {shares:.4f} shares")
    elif not position_open and crossed_above_sma:
        buy_cash = cash
        buy_shares = buy_cash / current_price if buy_cash > 0 else 0.0
        if buy_shares > 0:
            shares = buy_shares
            cash = 0.0
            state.update({
                "position_open": True,
                "entry_date": ticker.index[-1].strftime("%Y-%m-%d"),
                "avg_cost": round(current_price, 4),
                "shares": round(shares, 6),
                "cash": cash,
                "highest_high_since_entry": round(current_high, 4),
                "next_profit_multiple": INITIAL_PROFIT_MULTIPLE,
                "last_action": "buy_sma200",
            })
            state_changed = True
            action = "🟢 BUY SIGNAL — PRICE CROSSED ABOVE SMA200"
            instruction_lines.append(f"Buy with available cash: {money(buy_cash)}")
            instruction_lines.append(f"Estimated shares: {buy_shares:.4f}")
        else:
            action = "🟢 BUY SIGNAL — PRICE CROSSED ABOVE SMA200"
            instruction_lines.append("No tracked cash is available; update position_state.json after buying.")
    elif position_open and trailing_stop is not None and current_price > sma200 and current_price > trailing_stop:
        action = "✅ HOLD — Above SMA200, stop intact"
    elif current_price < sma200:
        action = "⏸️ WAIT — Price below SMA200" if not position_open else "⚠️ CAUTION — Price below SMA200"
    else:
        action = "⏸️ WAIT — No open position" if not position_open else "⚠️ CAUTION — Price near stop level"

    if state_changed:
        state_dirty = True

    is_signal = state_changed or (not position_open and crossed_above_sma)

    position_open = bool(state["position_open"])
    shares = float(state["shares"])
    avg_cost = float(state["avg_cost"]) if state["avg_cost"] is not None else 0.0
    cash = float(state.get("cash", 0.0))
    next_profit_multiple = float(state.get("next_profit_multiple", INITIAL_PROFIT_MULTIPLE))
    highest_high_since_entry = state.get("highest_high_since_entry")
    trailing_stop = calculate_trailing_stop(highest_high_since_entry)
    position_value = shares * current_price
    cost_basis = shares * avg_cost
    total_value = cash + position_value
    pnl = position_value - cost_basis if position_open else 0.0
    pnl_pct = (pnl / cost_basis) * 100 if cost_basis else 0.0

    date_str = ticker.index[-1].strftime("%d/%m/%Y")
    pnl_emoji = "🟢" if pnl >= 0 else "🔴"
    gap_to_stop = round(((trailing_stop - current_price) / current_price) * 100, 2) if trailing_stop is not None else None
    gap_to_sma = round(((sma200 - current_price) / current_price) * 100, 2)
    next_profit_target = avg_cost * next_profit_multiple if position_open and avg_cost else None
    position_status = "In position" if position_open else "Waiting for re-entry"
    risk_context_lines = build_risk_context(ticker, current_price, sma200, trailing_stop)

    # ── DAILY REPORT (full message) ───────────────────────
    if daily_report:
        report_key = f"{ticker.index[-1].strftime('%Y-%m-%d')}:{report_kind or 'daily'}"
        if dedupe_report and state.get("last_report_key") == report_key:
            print(f"[DAILY] Skipping duplicate {report_kind or 'daily'} report | Price: {current_price:.2f}")
            return

        report_title = "Daily Report"
        if report_kind == "open":
            report_title = "Opening Report"
        elif report_kind == "close":
            report_title = "Closing Report"

        lines = [
            f"📊 TQQQ {report_title} — {date_str}",
            "─" * 30,
            f"Action: {action}",
            *instruction_lines,
            "─" * 30,
            f"Mode:          {position_status}",
            f"💰 Price:        ${current_price:.2f}",
            f"📈 SMA200:       ${sma200:.2f}  ({gap_to_sma:+.1f}% away)",
        ]
        if trailing_stop is not None:
            lines.append(f"🛑 Trail Stop:   ${trailing_stop:.2f}  ({gap_to_stop:+.1f}% away)")
            lines.append(f"🏔️ High Since Entry: ${float(highest_high_since_entry):.2f}")
        else:
            lines.append("🛑 Trail Stop:   Not active")
        if next_profit_target:
            next_profit_pct = int(round((next_profit_multiple - 1) * 100))
            lines.append(f"🎯 Next Profit:  ${next_profit_target:.2f}  (+{next_profit_pct}% target)")
        lines.extend([
            "─" * 30,
            *risk_context_lines,
        ])
        lines.extend([
            "─" * 30,
            f"📦 Shares:       {shares:.4f}",
        ])
        if position_open:
            lines.append(f"💵 Avg Cost:     ${avg_cost:.2f}")
        lines.extend([
            f"🏦 Cash:         ${cash:.2f}",
            f"💼 Value:        ${position_value:.2f}",
            f"📊 Total:        ${total_value:.2f}",
            f"{pnl_emoji} P&L:          ${pnl:+.2f} ({pnl_pct:+.2f}%)",
            "─" * 30,
            f"Entry Date:      {state.get('entry_date') or 'Waiting for entry'}",
        ])
        msg = "\n".join(lines)
        send_telegram(msg)
        if dedupe_report:
            state["last_report_key"] = report_key
            state_dirty = True
        if state_dirty:
            save_state(state)

    # ── INTRADAY: only send if signal ─────────────────────
    elif is_signal:
        lines = [
            "─" * 30,
            action,
            *instruction_lines,
            "─" * 30,
            f"💰 Price:      ${current_price:.2f}",
            f"📈 SMA200:     ${sma200:.2f}",
        ]
        if trailing_stop is not None:
            lines.append(f"🛑 Trail Stop: ${trailing_stop:.2f}")
        if next_profit_target:
            lines.append(f"🎯 Next Profit: ${next_profit_target:.2f}")
        lines.extend([
            f"📦 Shares:     {shares:.4f}",
            f"🏦 Cash:       ${cash:.2f}",
            f"{pnl_emoji} P&L:        ${pnl:+.2f} ({pnl_pct:+.2f}%)",
        ])
        msg = "\n".join(lines)
        send_telegram(msg)
        if state_dirty:
            save_state(state)

    elif state_dirty:
        save_state(state)

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

    if intended_utc is None:
        now_utc = datetime.now(UTC)
        if schedule and schedule.startswith("45 "):
            report_kind, report_reason = report_kind_near_time(now_utc)
            if report_kind:
                print(f"[AUTO] Running {report_kind} report: {report_reason}")
                check_strategy(daily_report=True, report_kind=report_kind, dedupe_report=True)
                return

            print(f"[AUTO] Skipping report candidate: {report_reason}")
            return

        intraday_check, intraday_reason = is_market_open(now_utc)
        if intraday_check:
            print(f"[AUTO] Running intraday check: {intraday_reason}")
            check_strategy(daily_report=False)
            return

        print(f"[AUTO] Skipping scheduled run: {intraday_reason}")
        return

    daily_report, daily_reason = should_send_daily_report("auto", intended_utc)
    if daily_report:
        report_kind, _ = report_kind_for_schedule(intended_utc)
        print(f"[AUTO] Running {report_kind} report: {daily_reason}")
        check_strategy(daily_report=True, report_kind=report_kind, dedupe_report=True)
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
