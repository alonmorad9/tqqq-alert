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
BOT_STRATEGY_STATE_FILE = Path("bot_strategy_state.json")
MARKET_TZ = ZoneInfo("America/New_York")
TRAILING_STOP_PCT = 0.25
SWING_PROFIT_TARGET_PCT = 0.20
SWING_REBUY_DROP_PCT = 0.05
SWING_REBUY_TIMEOUT_DAYS = 15
MANUAL_REBUY_TIMEOUT_DAYS = 3
EARLY_WARNING_VIX_LEVEL = 25
EARLY_WARNING_VIX_5D_SPIKE_PCT = 0.25
EARLY_WARNING_RISK_THRESHOLD = 3
AUTO_EARLY_WARNING_EXIT = False
REENTRY_RSI_MAX = 70
PARABOLIC_RET5_WARNING_PCT = 0.25
PARABOLIC_RET10_WARNING_PCT = None

REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)
MAX_LIVE_PRICE_AGE = timedelta(minutes=30)


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
        "waiting_for_pullback": False,
        **clear_early_exit_fields(),
        "last_profit_sell_price": None,
        "profit_exit_date": None,
        "manual_exit_mode": False,
        "manual_exit_price": None,
        "manual_exit_date": None,
        "manual_exit_saw_below_sma": False,
        "last_action": None,
        "last_action_at": None,
        "last_report_key": None,
    }


def load_state():
    if not STATE_FILE.exists():
        return default_state()

    with STATE_FILE.open() as f:
        state = json.load(f)

    state.pop("next_profit_multiple", None)
    merged = default_state()
    merged.update(state)
    return merged


def save_state(state):
    state["last_action_at"] = datetime.now(UTC).isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def load_bot_strategy_state():
    if not BOT_STRATEGY_STATE_FILE.exists():
        return default_state()

    with BOT_STRATEGY_STATE_FILE.open() as f:
        state = json.load(f)

    state.pop("next_profit_multiple", None)
    merged = default_state()
    merged.update(state)
    merged.update(clear_manual_exit_fields())
    return merged


def save_bot_strategy_state(state):
    state["last_action_at"] = datetime.now(UTC).isoformat()
    BOT_STRATEGY_STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def fetch_market_data():
    from io import StringIO
    import time as time_module

    import pandas as pd
    import yfinance as yf

    def normalize_columns(df):
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        return df

    def overlay_live_bar(daily, intraday):
        if intraday.empty:
            return daily, "daily", None

        intraday = normalize_columns(intraday).dropna(subset=["Close"])
        if intraday.empty:
            return daily, "daily", None

        latest_bar_time = intraday.index[-1]
        if latest_bar_time.tzinfo is None:
            latest_bar_utc = latest_bar_time.tz_localize(MARKET_TZ).tz_convert(UTC)
        else:
            latest_bar_utc = latest_bar_time.tz_convert(UTC)

        live_age = datetime.now(UTC) - latest_bar_utc.to_pydatetime()
        latest_day = latest_bar_utc.astimezone(MARKET_TZ).date()
        day_bars = intraday[intraday.index.map(date_only) == latest_day]
        latest_close = float(day_bars["Close"].iloc[-1])
        latest_high = float(day_bars["High"].max())
        latest_low = float(day_bars["Low"].min())
        latest_open = float(day_bars["Open"].iloc[0])
        latest_volume = float(day_bars["Volume"].sum()) if "Volume" in day_bars else 0.0

        daily_dates = daily.index.map(date_only)
        if latest_day in set(daily_dates):
            row_index = daily.index[daily_dates == latest_day][-1]
            daily.loc[row_index, "Open"] = latest_open
            daily.loc[row_index, "High"] = max(float(daily.loc[row_index, "High"]), latest_high)
            daily.loc[row_index, "Low"] = min(float(daily.loc[row_index, "Low"]), latest_low)
            daily.loc[row_index, "Close"] = latest_close
            daily.loc[row_index, "Volume"] = latest_volume
        else:
            daily.loc[pd.Timestamp(latest_day)] = {
                "Open": latest_open,
                "High": latest_high,
                "Low": latest_low,
                "Close": latest_close,
                "Volume": latest_volume,
            }
            daily = daily.sort_index()

        return daily, f"1m bar {latest_bar_utc.isoformat()}", live_age

    def yahoo_download(symbol, period, interval):
        last_error = None
        for attempt in range(3):
            try:
                df = normalize_columns(
                    yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False)
                )
            except Exception as exc:
                last_error = exc
                df = pd.DataFrame()

            if not df.empty:
                return df

            if attempt < 2:
                time_module.sleep(2 * (attempt + 1))

        if last_error:
            print(f"[DATA] Yahoo download failed for {symbol} {period}/{interval}: {last_error}")
        else:
            print(f"[DATA] Yahoo download returned no rows for {symbol} {period}/{interval}")
        return pd.DataFrame()

    def stooq_symbol(symbol):
        if symbol == "^VIX":
            return "^vix"
        return f"{symbol.lower()}.us"

    def fetch_stooq_daily(symbol):
        end_day = datetime.now(MARKET_TZ).date()
        start_day = end_day - timedelta(days=365 * 3)
        params = {
            "s": stooq_symbol(symbol),
            "d1": start_day.strftime("%Y%m%d"),
            "d2": end_day.strftime("%Y%m%d"),
            "i": "d",
        }
        try:
            response = requests.get("https://stooq.com/q/d/l/", params=params, timeout=20)
            response.raise_for_status()
            df = pd.read_csv(StringIO(response.text))
        except Exception as exc:
            print(f"[DATA] Stooq daily fallback failed for {symbol}: {exc}")
            return pd.DataFrame()

        if df.empty or "Date" not in df or "Close" not in df:
            print(f"[DATA] Stooq daily fallback returned no rows for {symbol}")
            return pd.DataFrame()

        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date", "Close"]).set_index("Date").sort_index()
        return df[["Open", "High", "Low", "Close", "Volume"]].apply(pd.to_numeric, errors="coerce").dropna(subset=["Close"])

    def fetch_stooq_quote(symbol):
        params = {"s": stooq_symbol(symbol), "f": "sd2t2ohlcv", "h": "", "e": "csv"}
        try:
            response = requests.get("https://stooq.com/q/l/", params=params, timeout=20)
            response.raise_for_status()
            quote = pd.read_csv(StringIO(response.text))
        except Exception as exc:
            print(f"[DATA] Stooq quote fallback failed for {symbol}: {exc}")
            return pd.DataFrame()

        if quote.empty or "Close" not in quote:
            print(f"[DATA] Stooq quote fallback returned no rows for {symbol}")
            return pd.DataFrame()

        row = quote.iloc[0]
        close = pd.to_numeric(row.get("Close"), errors="coerce")
        if pd.isna(close):
            print(f"[DATA] Stooq quote fallback returned invalid close for {symbol}")
            return pd.DataFrame()

        quote_day = pd.to_datetime(row.get("Date"), errors="coerce")
        if pd.isna(quote_day):
            quote_day = pd.Timestamp(datetime.now(MARKET_TZ).date())

        def numeric_or_close(name):
            value = pd.to_numeric(row.get(name), errors="coerce")
            return float(close if pd.isna(value) else value)

        return pd.DataFrame(
            [{
                "Open": numeric_or_close("Open"),
                "High": numeric_or_close("High"),
                "Low": numeric_or_close("Low"),
                "Close": float(close),
                "Volume": numeric_or_close("Volume"),
            }],
            index=[pd.Timestamp(quote_day.date())],
        )

    def daily_data(symbol):
        df = yahoo_download(symbol, period="2y", interval="1d")
        if not df.empty:
            return df
        fallback = fetch_stooq_daily(symbol)
        if not fallback.empty:
            print(f"[DATA] Using Stooq daily fallback for {symbol}")
        return fallback

    def intraday_data(symbol):
        return yahoo_download(symbol, period="5d", interval="1m")

    def overlay_quote_bar(daily, quote, symbol):
        if quote.empty:
            return daily, "daily", None

        quote_day = date_only(quote.index[-1])
        quote_row = quote.iloc[-1]
        daily_dates = daily.index.map(date_only)
        if quote_day in set(daily_dates):
            row_index = daily.index[daily_dates == quote_day][-1]
            for column in ["Open", "High", "Low", "Close", "Volume"]:
                daily.loc[row_index, column] = float(quote_row[column])
        else:
            daily.loc[pd.Timestamp(quote_day)] = {column: float(quote_row[column]) for column in ["Open", "High", "Low", "Close", "Volume"]}
            daily = daily.sort_index()

        return daily, f"stooq quote {symbol}", None

    def overlay_best_available(daily, intraday, symbol):
        daily, source, age = overlay_live_bar(daily, intraday)
        if source != "daily":
            return daily, source, age
        return overlay_quote_bar(daily, fetch_stooq_quote(symbol), symbol)

    ticker = daily_data(TICKER)

    if ticker.empty:
        raise RuntimeError(f"No market data returned for {TICKER}")

    qqq = daily_data("QQQ")
    vix = daily_data("^VIX")
    if qqq.empty:
        raise RuntimeError("No market data returned for QQQ")
    if vix.empty:
        raise RuntimeError("No market data returned for ^VIX")

    intraday = intraday_data(TICKER)
    qqq_intraday = intraday_data("QQQ")
    vix_intraday = intraday_data("^VIX")

    live_source = "daily"
    live_age = None
    market_open, _ = is_market_open(datetime.now(UTC))
    ticker, live_source, live_age = overlay_best_available(ticker, intraday, TICKER)
    qqq, qqq_live_source, qqq_live_age = overlay_best_available(qqq, qqq_intraday, "QQQ")
    vix, vix_live_source, vix_live_age = overlay_best_available(vix, vix_intraday, "^VIX")

    if market_open and live_source == "daily":
        age_text = "unavailable" if live_age is None else str(live_age)
        raise RuntimeError(f"Live price is stale during market hours: {age_text}")
    if market_open and live_age is not None and live_age > MAX_LIVE_PRICE_AGE:
        raise RuntimeError(f"Live price is stale during market hours: {live_age}")

    ticker["SMA200"] = ticker["Close"].rolling(window=200).mean()
    ticker["SMA20"] = ticker["Close"].rolling(window=20).mean()
    ticker["SMA50"] = ticker["Close"].rolling(window=50).mean()
    ticker["SMA60"] = ticker["Close"].rolling(window=60).mean()
    ticker["RSI14"] = calculate_rsi(ticker["Close"], 14)
    ticker["RET5"] = ticker["Close"].pct_change(5)
    ticker["RET10"] = ticker["Close"].pct_change(10)
    qqq["EMA21"] = qqq["Close"].ewm(span=21, adjust=False).mean()
    qqq["EMA50"] = qqq["Close"].ewm(span=50, adjust=False).mean()
    vix["RET5"] = vix["Close"].pct_change(5)

    prev_close = ticker["Close"].shift(1)
    true_range = pd.concat([
        ticker["High"] - ticker["Low"],
        (ticker["High"] - prev_close).abs(),
        (ticker["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    ticker["ATR14"] = true_range.rolling(window=14).mean()
    qqq_signal = qqq[["Close", "EMA21", "EMA50"]].add_prefix("QQQ_")
    vix_signal = vix[["Close", "RET5"]].add_prefix("VIX_")
    ticker = ticker.join(qqq_signal, how="left").join(vix_signal, how="left").ffill()
    ticker = ticker.dropna(subset=["SMA200", "SMA20", "SMA50", "RSI14", "RET5", "RET10", "QQQ_Close", "QQQ_EMA21", "VIX_Close", "VIX_RET5"])
    ticker.attrs["price_source"] = live_source
    ticker.attrs["qqq_price_source"] = qqq_live_source
    ticker.attrs["vix_price_source"] = vix_live_source
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
    if hasattr(value, "tzinfo") and value.tzinfo is not None:
        if hasattr(value, "tz_convert"):
            return value.tz_convert(MARKET_TZ).date()
        return value.astimezone(MARKET_TZ).date()
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


def trading_days_since(date_text, ticker):
    if not date_text:
        return 0

    start_day = datetime.fromisoformat(date_text).date()
    return int(sum(1 for value in ticker.index.map(date_only) if value > start_day))


def clear_manual_exit_fields():
    return {
        "manual_exit_mode": False,
        "manual_exit_price": None,
        "manual_exit_date": None,
        "manual_exit_saw_below_sma": False,
    }


def clear_early_exit_fields():
    return {
        "waiting_for_early_reentry": False,
        "early_exit_price": None,
        "early_exit_date": None,
    }


def calculate_early_warning(ticker):
    row = ticker.iloc[-1]
    prev = ticker.iloc[-2]

    conditions = [
        ("VIX >= 25", float(row["VIX_Close"]) >= EARLY_WARNING_VIX_LEVEL),
        ("VIX 5d spike >= 25%", float(row["VIX_RET5"]) >= EARLY_WARNING_VIX_5D_SPIKE_PCT),
        ("QQQ below EMA21", float(row["QQQ_Close"]) < float(row["QQQ_EMA21"])),
        ("TQQQ below SMA50", float(row["Close"]) < float(row["SMA50"])),
        ("RSI falling from 70+", float(prev["RSI14"]) >= 70 and float(row["RSI14"]) < float(prev["RSI14"])),
    ]
    active = [label for label, is_active in conditions if is_active]
    score = len(active)
    if score >= EARLY_WARNING_RISK_THRESHOLD:
        level = "High"
    elif score >= 2:
        level = "Elevated"
    elif score == 1:
        level = "Watch"
    else:
        level = "Low"

    return {
        "score": score,
        "threshold": EARLY_WARNING_RISK_THRESHOLD,
        "level": level,
        "active": active,
        "hit": score >= EARLY_WARNING_RISK_THRESHOLD,
        "vix": float(row["VIX_Close"]),
        "vix_ret5": float(row["VIX_RET5"]),
        "qqq_close": float(row["QQQ_Close"]),
        "qqq_ema21": float(row["QQQ_EMA21"]),
        "tqqq_sma50": float(row["SMA50"]),
        "rsi14": float(row["RSI14"]),
    }


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
        "🧭 Market Health — advisory only",
        "Meaning: background risk notes. This section never buys or sells by itself.",
        "What to do: use it to understand how stretched or calm the market is.",
        f"Trend:         {trend}",
        f"Momentum:      {momentum} (RSI14 {rsi14:.1f})",
        f"ATR14:         ${atr14:.2f} ({atr_pct:.1f}% daily range)",
        f"ATR Ref Stop:  ${atr_stop_4x:.2f} (4x ATR, not active)",
        f"Risk Level:    {risk_level} — {notes}",
    ]


def build_early_warning_lines(early_warning):
    active = ", ".join(early_warning["active"]) if early_warning["active"] else "none"
    fast_drop_combo = (
        "VIX 5d spike >= 25%" in early_warning["active"]
        and "RSI falling from 70+" in early_warning["active"]
    )
    if fast_drop_combo:
        fast_drop_note = "Active: VIX fear spike + RSI rollover. Consider manually tightening your broker/TradingView stop."
        fast_drop_note_he = "פעיל: קפיצה ב-VIX + RSI מתגלגל למטה. לשקול ידנית הידוק סטופ בברוקר/TradingView."
    else:
        fast_drop_note = "Not active."
        fast_drop_note_he = "לא פעיל."
    return [
        "🔮 Early Drop Warnings — advisory only",
        "Meaning: faster weakness signals. They do NOT auto-sell because backtests showed too many false exits.",
        "What to do: if warnings stack up, be more alert and consider manual stop tightening.",
        f"Level:         {early_warning['level']} ({early_warning['score']}/{early_warning['threshold']} active)",
        f"Active:        {active}",
        f"Fast combo:    {fast_drop_note}",
        f"🇮🇱 שילוב מהיר: {fast_drop_note_he}",
        f"VIX:           {early_warning['vix']:.2f} ({early_warning['vix_ret5']:+.1%} over 5d)",
        f"QQQ vs EMA21:  ${early_warning['qqq_close']:.2f} / ${early_warning['qqq_ema21']:.2f}",
    ]


def calculate_parabolic_stretch(ticker):
    row = ticker.iloc[-1]
    ret5 = float(row["RET5"])
    ret10 = float(row["RET10"])
    active = []
    if ret5 >= PARABOLIC_RET5_WARNING_PCT:
        active.append(f"5d return {ret5:+.1%}")
    if PARABOLIC_RET10_WARNING_PCT is not None and ret10 >= PARABOLIC_RET10_WARNING_PCT:
        active.append(f"10d return {ret10:+.1%}")

    return {
        "hit": bool(active),
        "active": active,
        "ret5": ret5,
        "ret10": ret10,
    }


def build_parabolic_warning_lines(ticker):
    parabolic = calculate_parabolic_stretch(ticker)
    ret5 = parabolic["ret5"]
    ret10 = parabolic["ret10"]
    active = parabolic["active"]
    level = "Watch" if active else "Low"
    active_text = ", ".join(active) if active else "none"
    return [
        "⚡ Parabolic Profit Rule",
        "Meaning: this CAN trigger SELL ALL, but only when TQQQ is open, profitable, and has spiked unusually fast.",
        "What to do: if Action says SELL, sell; otherwise it is just a stretch meter.",
        f"Level:         {level}",
        f"Active:        {active_text}",
        f"5d / 10d Ret:  {ret5:+.1%} / {ret10:+.1%}",
    ]


def update_bot_strategy_benchmark(ticker):
    state = load_bot_strategy_state()

    current_price = float(ticker["Close"].iloc[-1])
    current_high = float(ticker["High"].iloc[-1])
    sma200 = float(ticker["SMA200"].iloc[-1])
    prev_price = float(ticker["Close"].iloc[-2])
    prev_sma200 = float(ticker["SMA200"].iloc[-2])
    current_date = ticker.index[-1].strftime("%Y-%m-%d")
    current_rsi = float(ticker["RSI14"].iloc[-1])
    reentry_rsi_ok = current_rsi <= REENTRY_RSI_MAX

    position_open = bool(state["position_open"])
    shares = float(state["shares"])
    avg_cost = float(state["avg_cost"]) if state["avg_cost"] is not None else 0.0
    cash = float(state.get("cash", 0.0))
    waiting_for_pullback = bool(state.get("waiting_for_pullback", False))
    waiting_for_early_reentry = bool(state.get("waiting_for_early_reentry", False))
    last_profit_sell_price = state.get("last_profit_sell_price")
    last_profit_sell_price = float(last_profit_sell_price) if last_profit_sell_price is not None else None
    profit_exit_date = state.get("profit_exit_date")
    pullback_wait_days = trading_days_since(profit_exit_date, ticker) if waiting_for_pullback else 0

    state_changed = False
    action = "benchmark_hold"

    highest_high_since_entry = initialize_highest_high_since_entry(state, ticker)
    if position_open:
        updated_high = max(highest_high_since_entry or current_high, current_high)
        if state.get("highest_high_since_entry") != round(updated_high, 4):
            highest_high_since_entry = updated_high
            state["highest_high_since_entry"] = round(highest_high_since_entry, 4)
            state_changed = True

    trailing_stop = calculate_trailing_stop(highest_high_since_entry)
    early_warning = calculate_early_warning(ticker)
    parabolic = calculate_parabolic_stretch(ticker)
    crossed_below_sma = prev_price >= prev_sma200 and current_price < sma200
    crossed_above_sma = prev_price <= prev_sma200 and current_price > sma200
    hit_trailing_stop = trailing_stop is not None and current_price < trailing_stop
    hit_early_warning_exit = position_open and AUTO_EARLY_WARNING_EXIT and early_warning["hit"]
    hit_profit_target = (
        position_open
        and shares > 0
        and avg_cost > 0
        and current_price >= avg_cost * (1 + SWING_PROFIT_TARGET_PCT)
    )
    hit_parabolic_exit = (
        position_open
        and shares > 0
        and avg_cost > 0
        and current_price >= avg_cost
        and parabolic["hit"]
    )
    above_sma = current_price > sma200
    hit_rebuy_pullback = (
        waiting_for_pullback
        and last_profit_sell_price is not None
        and current_price <= last_profit_sell_price * (1 - SWING_REBUY_DROP_PCT)
    )
    hit_rebuy_timeout = waiting_for_pullback and pullback_wait_days >= SWING_REBUY_TIMEOUT_DAYS
    hit_rebuy_signal = (hit_rebuy_pullback or hit_rebuy_timeout) and above_sma and reentry_rsi_ok
    hit_early_reentry_signal = (
        waiting_for_early_reentry
        and current_price > sma200
        and current_price > float(ticker["SMA20"].iloc[-1])
        and reentry_rsi_ok
    )
    hit_fresh_buy_signal = (
        crossed_above_sma or (not state.get("last_action") and above_sma)
    ) and not waiting_for_pullback and not waiting_for_early_reentry and reentry_rsi_ok

    if position_open and (hit_trailing_stop or crossed_below_sma):
        cash += shares * current_price
        action = "benchmark_sell_stop" if hit_trailing_stop else "benchmark_sell_sma200"
        state.update({
            "position_open": False,
            "shares": 0.0,
            "cash": round(cash, 2),
            "avg_cost": None,
            "entry_date": None,
            "highest_high_since_entry": None,
            "waiting_for_pullback": False,
            "waiting_for_early_reentry": False,
            "early_exit_price": None,
            "early_exit_date": None,
            "last_profit_sell_price": None,
            "profit_exit_date": None,
            "last_action": action,
        })
        state_changed = True
    elif position_open and hit_profit_target:
        cash += shares * current_price
        action = "benchmark_profit_exit_20"
        state.update({
            "position_open": False,
            "shares": 0.0,
            "cash": round(cash, 2),
            "avg_cost": None,
            "entry_date": None,
            "highest_high_since_entry": None,
            "waiting_for_pullback": True,
            "waiting_for_early_reentry": False,
            "early_exit_price": None,
            "early_exit_date": None,
            "last_profit_sell_price": round(current_price, 4),
            "profit_exit_date": current_date,
            "last_action": action,
        })
        state_changed = True
    elif position_open and hit_early_warning_exit:
        cash += shares * current_price
        action = "benchmark_sell_early_warning"
        state.update({
            "position_open": False,
            "shares": 0.0,
            "cash": round(cash, 2),
            "avg_cost": None,
            "entry_date": None,
            "highest_high_since_entry": None,
            "waiting_for_pullback": False,
            "last_profit_sell_price": None,
            "profit_exit_date": None,
            "waiting_for_early_reentry": True,
            "early_exit_price": round(current_price, 4),
            "early_exit_date": current_date,
            "last_action": action,
        })
        state_changed = True
    elif position_open and hit_parabolic_exit:
        cash += shares * current_price
        action = "benchmark_parabolic_profit_exit"
        state.update({
            "position_open": False,
            "shares": 0.0,
            "cash": round(cash, 2),
            "avg_cost": None,
            "entry_date": None,
            "highest_high_since_entry": None,
            "waiting_for_pullback": True,
            "waiting_for_early_reentry": False,
            "early_exit_price": None,
            "early_exit_date": None,
            "last_profit_sell_price": round(current_price, 4),
            "profit_exit_date": current_date,
            "last_action": action,
        })
        state_changed = True
    elif not position_open and (hit_fresh_buy_signal or hit_rebuy_signal or hit_early_reentry_signal):
        buy_cash = cash
        buy_shares = buy_cash / current_price if buy_cash > 0 else 0.0
        if buy_shares > 0:
            action = "benchmark_buy_sma200"
            if hit_rebuy_pullback:
                action = "benchmark_buy_pullback"
            elif hit_rebuy_timeout:
                action = "benchmark_buy_timeout"
            elif hit_early_reentry_signal:
                action = "benchmark_buy_early_reentry"
            state.update({
                "position_open": True,
                "entry_date": current_date,
                "avg_cost": round(current_price, 4),
                "shares": round(buy_shares, 6),
                "cash": 0.0,
                "highest_high_since_entry": round(current_high, 4),
                "waiting_for_pullback": False,
                "waiting_for_early_reentry": False,
                "early_exit_price": None,
                "early_exit_date": None,
                "last_profit_sell_price": None,
                "profit_exit_date": None,
                "last_action": action,
            })
            state_changed = True

    state.update(clear_manual_exit_fields())
    if state_changed:
        save_bot_strategy_state(state)

    position_open = bool(state["position_open"])
    shares = float(state["shares"])
    avg_cost = float(state["avg_cost"]) if state["avg_cost"] is not None else 0.0
    cash = float(state.get("cash", 0.0))
    waiting_for_pullback = bool(state.get("waiting_for_pullback", False))
    waiting_for_early_reentry = bool(state.get("waiting_for_early_reentry", False))
    last_profit_sell_price = state.get("last_profit_sell_price")
    last_profit_sell_price = float(last_profit_sell_price) if last_profit_sell_price is not None else None
    position_value = shares * current_price
    total_value = cash + position_value
    if position_open:
        benchmark_status = "In TQQQ"
    elif waiting_for_early_reentry:
        benchmark_status = "Waiting for early-risk recovery"
    elif waiting_for_pullback:
        benchmark_status = "Waiting for swing re-entry"
    else:
        benchmark_status = "Waiting for re-entry"
    next_profit_target = avg_cost * (1 + SWING_PROFIT_TARGET_PCT) if position_open and avg_cost else None
    rebuy_target = last_profit_sell_price * (1 - SWING_REBUY_DROP_PCT) if waiting_for_pullback and last_profit_sell_price else None

    return {
        "action": action,
        "cash": cash,
        "position_open": position_open,
        "shares": shares,
        "status": benchmark_status,
        "total_value": total_value,
        "next_profit_target": next_profit_target,
        "rebuy_target": rebuy_target,
        "early_warning": early_warning,
        "reentry_rsi_ok": reentry_rsi_ok,
    }


def check_strategy(daily_report=False, report_kind=None, dedupe_report=False):
    state = load_state()
    ticker = fetch_market_data()
    bot_strategy = update_bot_strategy_benchmark(ticker)

    current_price = float(ticker["Close"].iloc[-1])
    current_high = float(ticker["High"].iloc[-1])
    sma200 = float(ticker["SMA200"].iloc[-1])
    current_rsi = float(ticker["RSI14"].iloc[-1])
    reentry_rsi_ok = current_rsi <= REENTRY_RSI_MAX
    prev_price = float(ticker["Close"].iloc[-2])
    prev_sma200 = float(ticker["SMA200"].iloc[-2])

    position_open = bool(state["position_open"])
    shares = float(state["shares"])
    avg_cost = float(state["avg_cost"]) if state["avg_cost"] is not None else 0.0
    cash = float(state.get("cash", 0.0))
    waiting_for_pullback = bool(state.get("waiting_for_pullback", False))
    waiting_for_early_reentry = bool(state.get("waiting_for_early_reentry", False))
    last_profit_sell_price = state.get("last_profit_sell_price")
    last_profit_sell_price = float(last_profit_sell_price) if last_profit_sell_price is not None else None
    profit_exit_date = state.get("profit_exit_date")
    pullback_wait_days = trading_days_since(profit_exit_date, ticker) if waiting_for_pullback else 0
    manual_exit_mode = bool(state.get("manual_exit_mode", False))
    manual_exit_price = state.get("manual_exit_price")
    manual_exit_price = float(manual_exit_price) if manual_exit_price is not None else None
    manual_exit_date = state.get("manual_exit_date")
    manual_wait_days = trading_days_since(manual_exit_date, ticker) if manual_exit_mode else 0
    manual_exit_saw_below_sma = bool(state.get("manual_exit_saw_below_sma", False))
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
    early_warning = calculate_early_warning(ticker)
    parabolic = calculate_parabolic_stretch(ticker)
    position_value = shares * current_price
    cost_basis = shares * avg_cost
    total_value = cash + position_value
    pnl = position_value - cost_basis if position_open else 0.0
    pnl_pct = (pnl / cost_basis) * 100 if cost_basis else 0.0

    # ── SIGNAL DETECTION ──────────────────────────────────
    crossed_below_sma = prev_price >= prev_sma200 and current_price < sma200
    crossed_above_sma = prev_price <= prev_sma200 and current_price > sma200
    hit_trailing_stop = trailing_stop is not None and current_price < trailing_stop
    hit_early_warning_exit = position_open and AUTO_EARLY_WARNING_EXIT and early_warning["hit"]
    hit_profit_target = (
        position_open
        and shares > 0
        and avg_cost > 0
        and current_price >= avg_cost * (1 + SWING_PROFIT_TARGET_PCT)
    )
    hit_parabolic_exit = (
        position_open
        and shares > 0
        and avg_cost > 0
        and current_price >= avg_cost
        and parabolic["hit"]
    )
    above_sma = current_price > sma200
    if manual_exit_mode and current_price < sma200 and not manual_exit_saw_below_sma:
        manual_exit_saw_below_sma = True
        state["manual_exit_saw_below_sma"] = True
        state_dirty = True

    hit_rebuy_pullback = (
        waiting_for_pullback
        and last_profit_sell_price is not None
        and current_price <= last_profit_sell_price * (1 - SWING_REBUY_DROP_PCT)
    )
    hit_rebuy_timeout = waiting_for_pullback and pullback_wait_days >= SWING_REBUY_TIMEOUT_DAYS
    hit_rebuy_signal = (hit_rebuy_pullback or hit_rebuy_timeout) and above_sma and reentry_rsi_ok
    hit_manual_rebuy_pullback = (
        manual_exit_mode
        and manual_exit_price is not None
        and current_price <= manual_exit_price * (1 - SWING_REBUY_DROP_PCT)
    )
    hit_manual_rebuy_reset = manual_exit_mode and manual_exit_saw_below_sma and crossed_above_sma
    hit_manual_rebuy_timeout = manual_exit_mode and manual_wait_days >= MANUAL_REBUY_TIMEOUT_DAYS and above_sma
    hit_manual_rebuy_signal = (
        hit_manual_rebuy_pullback or hit_manual_rebuy_reset or hit_manual_rebuy_timeout
    ) and above_sma and reentry_rsi_ok
    hit_early_reentry_signal = (
        waiting_for_early_reentry
        and current_price > sma200
        and current_price > float(ticker["SMA20"].iloc[-1])
        and reentry_rsi_ok
    )
    hit_fresh_buy_signal = (
        crossed_above_sma or (not state.get("last_action") and current_price > sma200 and current_price > float(ticker["SMA20"].iloc[-1]))
    ) and not waiting_for_pullback and not waiting_for_early_reentry and not manual_exit_mode and reentry_rsi_ok

    raw_reentry_trigger = (
        ((hit_rebuy_pullback or hit_rebuy_timeout) and above_sma)
        or ((hit_manual_rebuy_pullback or hit_manual_rebuy_reset or hit_manual_rebuy_timeout) and above_sma)
        or (waiting_for_early_reentry and current_price > sma200 and current_price > float(ticker["SMA20"].iloc[-1]))
        or (
            (crossed_above_sma or (not state.get("last_action") and current_price > sma200 and current_price > float(ticker["SMA20"].iloc[-1])))
            and not waiting_for_pullback
            and not waiting_for_early_reentry
            and not manual_exit_mode
        )
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
            "waiting_for_pullback": False,
            **clear_early_exit_fields(),
            "last_profit_sell_price": None,
            "profit_exit_date": None,
            **clear_manual_exit_fields(),
            "last_action": "sell_all_trailing_stop",
        })
        state_changed = True
        action = "🚨 SELL NOW — TRAILING STOP HIT"
        instruction_lines.append(f"Sell all remaining shares: {sell_shares:.4f}")
        instruction_lines.append("After selling, wait in cash until the next TQQQ re-entry signal.")
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
            "waiting_for_pullback": False,
            **clear_early_exit_fields(),
            "last_profit_sell_price": None,
            "profit_exit_date": None,
            **clear_manual_exit_fields(),
            "last_action": "sell_all_sma200",
        })
        state_changed = True
        action = "🚨 SELL NOW — CROSSED BELOW SMA200"
        instruction_lines.append(f"Sell all remaining shares: {sell_shares:.4f}")
        instruction_lines.append("After selling, wait in cash until the next TQQQ re-entry signal.")
    elif position_open and hit_profit_target:
        sell_shares = shares
        cash += sell_shares * current_price
        shares = 0.0
        target_pct = int(round(SWING_PROFIT_TARGET_PCT * 100))
        state.update({
            "position_open": False,
            "shares": shares,
            "cash": round(cash, 2),
            "avg_cost": None,
            "entry_date": None,
            "highest_high_since_entry": None,
            "waiting_for_pullback": True,
            **clear_early_exit_fields(),
            "last_profit_sell_price": round(current_price, 4),
            "profit_exit_date": ticker.index[-1].strftime("%Y-%m-%d"),
            **clear_manual_exit_fields(),
            "last_action": f"swing_profit_exit_{target_pct}",
        })
        state_changed = True
        action = f"💰 SELL ALL — +{target_pct}% SWING TARGET HIT"
        instruction_lines.append(f"Sell all shares: {sell_shares:.4f}")
        instruction_lines.append("Then wait in cash.")
        rebuy_price = current_price * (1 - SWING_REBUY_DROP_PCT)
        instruction_lines.append(f"Next re-buy trigger: ${rebuy_price:.2f} or {SWING_REBUY_TIMEOUT_DAYS} trading days if still above SMA200")
    elif position_open and hit_early_warning_exit:
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
            "waiting_for_pullback": False,
            "last_profit_sell_price": None,
            "profit_exit_date": None,
            "waiting_for_early_reentry": True,
            "early_exit_price": round(current_price, 4),
            "early_exit_date": ticker.index[-1].strftime("%Y-%m-%d"),
            **clear_manual_exit_fields(),
            "last_action": "sell_all_early_warning",
        })
        state_changed = True
        action = "🔮 SELL ALL — EARLY DROP RISK HIGH"
        instruction_lines.append(f"Sell all shares: {sell_shares:.4f}")
        instruction_lines.append("Then wait in cash until risk recovery.")
        instruction_lines.append(f"Risk signals: {', '.join(early_warning['active'])}")
        instruction_lines.append("Next re-buy trigger: price above SMA200 and SMA20 after risk cools.")
    elif position_open and hit_parabolic_exit:
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
            "waiting_for_pullback": True,
            **clear_early_exit_fields(),
            "last_profit_sell_price": round(current_price, 4),
            "profit_exit_date": ticker.index[-1].strftime("%Y-%m-%d"),
            **clear_manual_exit_fields(),
            "last_action": "parabolic_profit_exit",
        })
        state_changed = True
        action = "⚡ SELL ALL — PARABOLIC PROFIT EXIT"
        instruction_lines.append(f"Sell all shares: {sell_shares:.4f}")
        instruction_lines.append(f"Reason: {', '.join(parabolic['active'])}.")
        instruction_lines.append("Then wait in cash.")
        rebuy_price = current_price * (1 - SWING_REBUY_DROP_PCT)
        instruction_lines.append(f"Next re-buy trigger: ${rebuy_price:.2f} or {SWING_REBUY_TIMEOUT_DAYS} trading days if still above SMA200")
    elif not position_open and (hit_fresh_buy_signal or hit_rebuy_signal or hit_manual_rebuy_signal or hit_early_reentry_signal):
        buy_cash = cash
        buy_shares = buy_cash / current_price if buy_cash > 0 else 0.0
        if buy_shares > 0:
            buy_reason = "buy_sma200"
            action = "🟢 BUY SIGNAL — PRICE CROSSED ABOVE SMA200"
            if hit_rebuy_pullback:
                buy_reason = "buy_swing_pullback"
                action = "🟢 RE-BUY SIGNAL — PULLBACK TARGET HIT"
            elif hit_rebuy_timeout:
                buy_reason = "buy_swing_timeout"
                action = "🟢 RE-BUY SIGNAL — TIMEOUT HIT, TREND STILL OK"
            elif hit_manual_rebuy_pullback:
                buy_reason = "buy_manual_pullback"
                action = "🟢 RE-BUY SIGNAL — MANUAL EXIT PULLBACK HIT"
            elif hit_manual_rebuy_reset:
                buy_reason = "buy_manual_sma_reset"
                action = "🟢 RE-BUY SIGNAL — SMA200 RESET COMPLETE"
            elif hit_manual_rebuy_timeout:
                buy_reason = "buy_manual_timeout"
                action = "🟢 RE-BUY SIGNAL — MANUAL TIMEOUT, TREND STILL OK"
            elif hit_early_reentry_signal:
                buy_reason = "buy_early_risk_recovery"
                action = "🟢 RE-BUY SIGNAL — EARLY RISK RECOVERED"
            shares = buy_shares
            cash = 0.0
            state.update({
                "position_open": True,
                "entry_date": ticker.index[-1].strftime("%Y-%m-%d"),
                "avg_cost": round(current_price, 4),
                "shares": round(shares, 6),
                "cash": cash,
                "highest_high_since_entry": round(current_high, 4),
                "waiting_for_pullback": False,
                **clear_early_exit_fields(),
                "last_profit_sell_price": None,
                "profit_exit_date": None,
                **clear_manual_exit_fields(),
                "last_action": buy_reason,
            })
            state_changed = True
            instruction_lines.append(f"Buy with available cash: {money(buy_cash)}")
            instruction_lines.append(f"Estimated shares: {buy_shares:.4f}")
        else:
            action = "🟢 BUY SIGNAL — PRICE CROSSED ABOVE SMA200"
            if hit_rebuy_pullback:
                action = "🟢 RE-BUY SIGNAL — PULLBACK TARGET HIT"
            elif hit_rebuy_timeout:
                action = "🟢 RE-BUY SIGNAL — TIMEOUT HIT, TREND STILL OK"
            elif hit_manual_rebuy_pullback:
                action = "🟢 RE-BUY SIGNAL — MANUAL EXIT PULLBACK HIT"
            elif hit_manual_rebuy_reset:
                action = "🟢 RE-BUY SIGNAL — SMA200 RESET COMPLETE"
            elif hit_manual_rebuy_timeout:
                action = "🟢 RE-BUY SIGNAL — MANUAL TIMEOUT, TREND STILL OK"
            elif hit_early_reentry_signal:
                action = "🟢 RE-BUY SIGNAL — EARLY RISK RECOVERED"
            instruction_lines.append("No tracked cash is available. Run manual_cash_set after you update your broker cash, or run manual_bought after buying.")
    elif position_open and trailing_stop is not None and current_price > sma200 and current_price > trailing_stop:
        action = "✅ HOLD — Above SMA200, stop intact"
    elif raw_reentry_trigger and not reentry_rsi_ok:
        action = f"⏳ WAIT — Re-entry blocked until RSI <= {REENTRY_RSI_MAX}"
    elif waiting_for_pullback:
        action = "⏳ WAIT — Waiting for pullback or timeout re-entry"
    elif waiting_for_early_reentry:
        action = "🔮 WAIT — Waiting for early-risk recovery"
    elif manual_exit_mode:
        action = "🧯 WAIT — Manual safety mode"
    elif current_price < sma200:
        action = "⏸️ WAIT — Price below SMA200" if not position_open else "⚠️ CAUTION — Price below SMA200"
    else:
        action = "⏸️ WAIT — No open position" if not position_open else "⚠️ CAUTION — Price near stop level"

    if state_changed:
        state_dirty = True

    is_signal = state_changed or (not position_open and hit_fresh_buy_signal)
    is_signal = is_signal or (not position_open and hit_rebuy_signal)
    is_signal = is_signal or (not position_open and hit_manual_rebuy_signal)
    is_signal = is_signal or (not position_open and hit_early_reentry_signal)

    position_open = bool(state["position_open"])
    shares = float(state["shares"])
    avg_cost = float(state["avg_cost"]) if state["avg_cost"] is not None else 0.0
    cash = float(state.get("cash", 0.0))
    waiting_for_pullback = bool(state.get("waiting_for_pullback", False))
    waiting_for_early_reentry = bool(state.get("waiting_for_early_reentry", False))
    last_profit_sell_price = state.get("last_profit_sell_price")
    last_profit_sell_price = float(last_profit_sell_price) if last_profit_sell_price is not None else None
    profit_exit_date = state.get("profit_exit_date")
    pullback_wait_days = trading_days_since(profit_exit_date, ticker) if waiting_for_pullback else 0
    manual_exit_mode = bool(state.get("manual_exit_mode", False))
    manual_exit_price = state.get("manual_exit_price")
    manual_exit_price = float(manual_exit_price) if manual_exit_price is not None else None
    manual_exit_date = state.get("manual_exit_date")
    manual_wait_days = trading_days_since(manual_exit_date, ticker) if manual_exit_mode else 0
    manual_exit_saw_below_sma = bool(state.get("manual_exit_saw_below_sma", False))
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
    next_profit_target = avg_cost * (1 + SWING_PROFIT_TARGET_PCT) if position_open and avg_cost else None
    rebuy_target = last_profit_sell_price * (1 - SWING_REBUY_DROP_PCT) if waiting_for_pullback and last_profit_sell_price else None
    manual_rebuy_target = manual_exit_price * (1 - SWING_REBUY_DROP_PCT) if manual_exit_mode and manual_exit_price else None
    if position_open:
        position_status = "In position"
    elif manual_exit_mode:
        position_status = "Manual safety mode"
    elif waiting_for_early_reentry:
        position_status = "Waiting for early-risk recovery"
    elif waiting_for_pullback:
        position_status = "Waiting for swing re-entry"
    else:
        position_status = "Waiting for re-entry"
    risk_context_lines = build_risk_context(ticker, current_price, sma200, trailing_stop)
    price_source = ticker.attrs.get("price_source", "daily")
    strategy_gap = total_value - bot_strategy["total_value"]
    strategy_gap_pct = (strategy_gap / bot_strategy["total_value"]) * 100 if bot_strategy["total_value"] else 0.0

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
            "Read first: follow the Action line. The risk sections below explain context unless they explicitly create the Action.",
            *instruction_lines,
            "─" * 30,
            f"Mode:          {position_status}",
            f"💰 Price:        ${current_price:.2f}",
            f"🕒 Price Source: {price_source}",
            f"📈 SMA200:       ${sma200:.2f}  ({gap_to_sma:+.1f}% away)",
        ]
        if trailing_stop is not None:
            lines.append(f"🛑 Trail Stop:   ${trailing_stop:.2f}  ({gap_to_stop:+.1f}% away)")
            lines.append(f"🏔️ High Since Entry: ${float(highest_high_since_entry):.2f}")
        else:
            lines.append("🛑 Trail Stop:   Not active")
        if next_profit_target:
            next_profit_pct = int(round(SWING_PROFIT_TARGET_PCT * 100))
            lines.append(f"🎯 Next Profit:  ${next_profit_target:.2f}  (+{next_profit_pct}% target)")
        if rebuy_target:
            lines.append(f"🔁 Re-buy:       ${rebuy_target:.2f}  (-{SWING_REBUY_DROP_PCT * 100:.1f}% from profit exit)")
            lines.append(f"⏳ Wait Days:    {pullback_wait_days}/{SWING_REBUY_TIMEOUT_DAYS} trading days")
        if manual_rebuy_target:
            lines.append(f"🧯 Manual Re-buy: ${manual_rebuy_target:.2f}  (-{SWING_REBUY_DROP_PCT * 100:.1f}% from manual exit)")
            lines.append(f"⏳ Manual Wait:  {manual_wait_days}/{MANUAL_REBUY_TIMEOUT_DAYS} trading days")
            reset_status = "seen" if manual_exit_saw_below_sma else "not yet"
            lines.append(f"🔄 SMA Reset:    {reset_status}")
            lines.append(
                f"🇮🇱 מצב ידני: קנייה מחדש רק אחרי ירידה של {SWING_REBUY_DROP_PCT * 100:.1f}%, "
                f"או אחרי {MANUAL_REBUY_TIMEOUT_DAYS} ימי מסחר, או אחרי איפוס SMA200; תמיד רק אם RSI <= {REENTRY_RSI_MAX}."
            )
        if not position_open:
            rsi_status = "ready" if reentry_rsi_ok else "too hot"
            lines.append(f"🧊 Re-entry RSI: {current_rsi:.1f}/{REENTRY_RSI_MAX} max ({rsi_status})")
            if cash > 0:
                lines.append("🅿️ Waiting Asset: Cash")
                lines.append("   Plan: stay in cash until the next TQQQ buy/re-buy signal.")
            else:
                lines.append("   Plan: no tracked cash. Run manual_cash_set after updating broker cash.")
        lines.extend([
            "─" * 30,
            *risk_context_lines,
            "─" * 30,
            *build_parabolic_warning_lines(ticker),
            "─" * 30,
            *build_early_warning_lines(early_warning),
        ])
        if manual_exit_mode:
            lines.append(f"Current controller: manual safety mode; re-buy waits for pullback, {MANUAL_REBUY_TIMEOUT_DAYS}-day timeout, or SMA200 reset, plus RSI <= {REENTRY_RSI_MAX}.")
            lines.append(f"🇮🇱 מצב בטיחות ידני: מחכים לירידה, טיימאאוט של {MANUAL_REBUY_TIMEOUT_DAYS} ימי מסחר, או איפוס SMA200; כניסה רק אם RSI <= {REENTRY_RSI_MAX}.")
        elif waiting_for_early_reentry:
            lines.append(f"Current controller: early-risk recovery; re-buy waits for TQQQ above SMA200 and SMA20, plus RSI <= {REENTRY_RSI_MAX}.")
        lines.extend([
            "─" * 30,
            f"📦 Shares:       {shares:.4f}",
        ])
        if position_open:
            lines.append(f"💵 Avg Cost:     ${avg_cost:.2f}")
        lines.extend([
            f"🏦 Cash:         ${cash:.2f}",
            f"💼 TQQQ Value:   ${position_value:.2f}",
            f"📊 Total:        ${total_value:.2f}",
            f"{pnl_emoji} TQQQ P&L:     ${pnl:+.2f} ({pnl_pct:+.2f}%)",
            "─" * 30,
            "🧪 Bot-Only Benchmark",
            f"Mode:          {bot_strategy['status']}",
            f"📊 Total:        ${bot_strategy['total_value']:.2f}",
            f"Vs Real Path:   ${strategy_gap:+.2f} ({strategy_gap_pct:+.2f}%)",
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
            "Read first: follow this Action. Extra risk notes are context only unless this is a SELL/BUY signal.",
            *instruction_lines,
            "─" * 30,
            f"💰 Price:      ${current_price:.2f}",
            f"🕒 Source:     {price_source}",
            f"📈 SMA200:     ${sma200:.2f}",
        ]
        if trailing_stop is not None:
            lines.append(f"🛑 Trail Stop: ${trailing_stop:.2f}")
        if next_profit_target:
            lines.append(f"🎯 Next Profit: ${next_profit_target:.2f}")
        if rebuy_target:
            lines.append(f"🔁 Re-buy:     ${rebuy_target:.2f}")
            lines.append(f"⏳ Wait Days:  {pullback_wait_days}/{SWING_REBUY_TIMEOUT_DAYS}")
        if manual_rebuy_target:
            lines.append(f"🧯 Manual Re-buy: ${manual_rebuy_target:.2f}")
            lines.append(f"⏳ Manual Wait: {manual_wait_days}/{MANUAL_REBUY_TIMEOUT_DAYS}")
            reset_status = "seen" if manual_exit_saw_below_sma else "not yet"
            lines.append(f"🔄 SMA Reset: {reset_status}")
            lines.append(f"🇮🇱 מצב ידני: כניסה מחדש רק אחרי ירידה, {MANUAL_REBUY_TIMEOUT_DAYS} ימי מסחר, או איפוס SMA200; תמיד RSI <= {REENTRY_RSI_MAX}.")
        if waiting_for_early_reentry:
            lines.append(f"🔮 Early Re-buy: above SMA200 and SMA20, RSI <= {REENTRY_RSI_MAX}")
        if not position_open:
            lines.append(f"🧊 Re-entry RSI: {current_rsi:.1f}/{REENTRY_RSI_MAX} max")
            lines.append("🅿️ Waiting Asset: Cash")
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


def parse_manual_price(mode="manual_sold"):
    raw_price = os.getenv("MANUAL_PRICE", "").strip()
    if not raw_price:
        raise RuntimeError(f"{mode} mode requires MANUAL_PRICE / manual_price input")

    price = float(raw_price)
    if price <= 0:
        raise RuntimeError("manual_price must be greater than 0")

    return price


def parse_manual_amount(mode="manual_cash_set"):
    raw_amount = os.getenv("MANUAL_AMOUNT", "").strip()
    if not raw_amount:
        raise RuntimeError(f"{mode} mode requires MANUAL_AMOUNT / manual_amount input")

    amount = float(raw_amount)
    if amount <= 0:
        raise RuntimeError("manual_amount must be greater than 0")

    return amount


def mark_manual_sold():
    manual_price = parse_manual_price()
    state = load_state()
    shares = float(state.get("shares", 0.0))
    cash = float(state.get("cash", 0.0))
    sale_value = shares * manual_price
    cash += sale_value
    rebuy_target = manual_price * (1 - SWING_REBUY_DROP_PCT)

    state.update({
        "position_open": False,
        "shares": 0.0,
        "cash": round(cash, 2),
        "avg_cost": None,
        "entry_date": None,
        "highest_high_since_entry": None,
        "waiting_for_pullback": False,
        "last_profit_sell_price": None,
        "profit_exit_date": None,
        "manual_exit_mode": True,
        "manual_exit_price": round(manual_price, 4),
        "manual_exit_date": datetime.now(UTC).date().isoformat(),
        "manual_exit_saw_below_sma": False,
        "last_action": "manual_sold",
    })
    save_state(state)

    lines = [
        "🧯 Manual Safety Mode Activated",
        "─" * 30,
        f"Manual sell price: ${manual_price:.2f}",
        f"Tracked shares sold: {shares:.4f}",
        f"Tracked cash: ${cash:.2f}",
        "─" * 30,
        f"Re-buy pullback: ${rebuy_target:.2f}",
        f"Or: after {MANUAL_REBUY_TIMEOUT_DAYS} trading days if TQQQ is still above SMA200.",
        "Or: wait for price to go below SMA200, then cross back above SMA200.",
        f"All manual re-buy paths still require RSI14 <= {REENTRY_RSI_MAX}.",
        "The bot will not immediately re-buy just because TQQQ is currently above SMA200.",
        "─" * 30,
        "🇮🇱 מצב בטיחות ידני הופעל",
        f"מחיר מכירה ידני: ${manual_price:.2f}",
        f"מזומן במעקב: ${cash:.2f}",
        f"קנייה מחדש: ירידה ל-${rebuy_target:.2f}, או אחרי {MANUAL_REBUY_TIMEOUT_DAYS} ימי מסחר אם TQQQ עדיין מעל SMA200.",
        f"אפשרות נוספת: ירידה מתחת ל-SMA200 ואז חציה חזרה למעלה. בכל מקרה נדרש RSI14 <= {REENTRY_RSI_MAX}.",
    ]
    send_telegram("\n".join(lines))
    print(f"[MANUAL SOLD] Safety mode activated | Price: {manual_price:.2f} | Cash: {cash:.2f}")


def mark_manual_bought():
    manual_price = parse_manual_price("manual_bought")
    state = load_state()
    cash = float(state.get("cash", 0.0))

    raw_shares = os.getenv("MANUAL_SHARES", "").strip()
    if raw_shares:
        shares = float(raw_shares)
        if shares <= 0:
            raise RuntimeError("manual_shares must be greater than 0")
        spent = shares * manual_price
        remaining_cash = round(cash - spent, 2)
        if remaining_cash < -0.01:
            raise RuntimeError(f"manual_shares implies spending ${spent:.2f} but only ${cash:.2f} tracked cash available")
    else:
        shares = cash / manual_price if cash > 0 else 0.0
        remaining_cash = 0.0

    if shares <= 0:
        raise RuntimeError("No tracked cash available to buy with — update position_state.json first")

    state.update({
        "position_open": True,
        "shares": round(shares, 6),
        "avg_cost": round(manual_price, 4),
        "cash": remaining_cash,
        "entry_date": datetime.now(UTC).date().isoformat(),
        "highest_high_since_entry": round(manual_price, 4),
        "waiting_for_pullback": False,
        "waiting_for_early_reentry": False,
        "early_exit_price": None,
        "early_exit_date": None,
        "last_profit_sell_price": None,
        "profit_exit_date": None,
        "manual_exit_mode": False,
        "manual_exit_price": None,
        "manual_exit_date": None,
        "manual_exit_saw_below_sma": False,
        "last_action": "manual_bought",
    })
    save_state(state)

    next_profit_target = manual_price * (1 + SWING_PROFIT_TARGET_PCT)
    lines = [
        "\U0001f7e2 Manual Buy Recorded",
        "\u2500" * 30,
        f"Buy price:      ${manual_price:.2f}",
        f"Shares bought:  {shares:.4f}",
        f"Cash remaining: ${remaining_cash:.2f}",
        "\u2500" * 30,
        f"\U0001f3af Profit target: ${next_profit_target:.2f} (+{int(SWING_PROFIT_TARGET_PCT * 100)}%)",
        "Bot will now track position and send alerts normally.",
    ]
    send_telegram("\n".join(lines))
    print(f"[MANUAL BOUGHT] Position recorded | Price: {manual_price:.2f} | Shares: {shares:.4f}")


def mark_manual_cash_set():
    amount = parse_manual_amount("manual_cash_set")
    state = load_state()
    state.update({
        "position_open": False,
        "shares": 0.0,
        "avg_cost": None,
        "cash": round(amount, 2),
        "entry_date": None,
        "highest_high_since_entry": None,
        "last_action": "manual_cash_set",
    })
    save_state(state)

    lines = [
        "🏦 Manual Cash Updated",
        "─" * 30,
        f"Tracked cash: ${amount:.2f}",
        "─" * 30,
        "The TQQQ bot will wait in cash until the next TQQQ buy/re-buy signal.",
        "Manual safety mode and re-entry rules remain unchanged.",
    ]
    send_telegram("\n".join(lines))
    print(f"[MANUAL CASH SET] Cash: {amount:.2f}")


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
    # - manual_sold: record a manual TQQQ sell and enter safety mode
    # - manual_bought: record a manual TQQQ buy
    # - manual_cash_set: set tracked cash after a broker-side cash update
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"

    if mode == "auto":
        run_auto_mode()
    elif mode == "daily":
        check_strategy(daily_report=True)
    elif mode == "manual_sold":
        mark_manual_sold()
    elif mode == "manual_bought":
        mark_manual_bought()
    elif mode == "manual_cash_set":
        mark_manual_cash_set()
    else:
        check_strategy(daily_report=False)
