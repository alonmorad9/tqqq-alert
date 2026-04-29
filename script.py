import os
import sys
import requests
import yfinance as yf
import pandas as pd

# ── YOUR POSITION ──────────────────────────────────────────
ENTRY_DATE = "2026-04-29"
SHARES     = 40.4647
AVG_COST   = 61.54
TICKER     = "TQQQ"
# ───────────────────────────────────────────────────────────

def check_strategy(daily_report=False):
    ticker = yf.download(TICKER, period="2y", interval="1d", auto_adjust=True)

    if isinstance(ticker.columns, pd.MultiIndex):
        ticker.columns = [c[0] for c in ticker.columns]

    ticker['SMA200'] = ticker['Close'].rolling(window=200).mean()

    current_price      = float(ticker['Close'].iloc[-1])
    sma200             = float(ticker['SMA200'].iloc[-1])
    recent_high        = float(ticker['High'].tail(30).max())
    trailing_stop      = round(recent_high * 0.90, 2)
    prev_price         = float(ticker['Close'].iloc[-2])
    prev_sma200        = float(ticker['SMA200'].iloc[-2])
    prev_recent_high   = float(ticker['High'].tail(31).iloc[:-1].max())
    prev_trailing_stop = round(prev_recent_high * 0.90, 2)
    hard_stop          = round(AVG_COST * 0.95, 2)

    position_value = SHARES * current_price
    cost_basis     = SHARES * AVG_COST
    pnl            = position_value - cost_basis
    pnl_pct        = (pnl / cost_basis) * 100

    # ── SIGNAL DETECTION ──────────────────────────────────
    crossed_below_sma = prev_price >= prev_sma200 and current_price < sma200
    crossed_above_sma = prev_price <= prev_sma200 and current_price > sma200
    hit_trailing_stop = prev_price >= prev_trailing_stop and current_price < trailing_stop
    hit_hard_stop     = prev_price >= hard_stop and current_price < hard_stop

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

    date_str    = ticker.index[-1].strftime("%d/%m/%Y")
    pnl_emoji   = "🟢" if pnl >= 0 else "🔴"
    gap_to_stop = round(((current_price - trailing_stop) / current_price) * 100, 2)

    # ── DAILY REPORT (full message) ────────────────────────
    if daily_report:
        msg = (
            f"📊 TQQQ Daily Report — {date_str}\n"
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

    # ── INTRADAY: only send if signal ──────────────────────
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
    token   = os.getenv('TELEGRAM_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    url     = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": message})


if __name__ == "__main__":
    # Pass "daily" argument for full report, otherwise just check for signals
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    check_strategy(daily_report=(mode == "daily"))
