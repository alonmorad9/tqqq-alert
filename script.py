import os
import requests
import yfinance as yf
import pandas as pd

# ── YOUR POSITION ──────────────────────────────────────────
ENTRY_DATE     = "2026-04-29"
SHARES         = 40.4647
AVG_COST       = 61.54
TICKER         = "TQQQ"
# ───────────────────────────────────────────────────────────

def check_strategy():
    ticker = yf.download(TICKER, period="2y", interval="1d", auto_adjust=True)

    # Flatten MultiIndex columns if present
    if isinstance(ticker.columns, pd.MultiIndex):
        ticker.columns = [c[0] for c in ticker.columns]

    ticker['SMA200'] = ticker['Close'].rolling(window=200).mean()

    current_price  = float(ticker['Close'].iloc[-1])
    sma200         = float(ticker['SMA200'].iloc[-1])
    prev_price     = float(ticker['Close'].iloc[-2])
    prev_sma200    = float(ticker['SMA200'].iloc[-2])
    recent_high    = float(ticker['High'].tail(30).max())
    trailing_stop  = round(recent_high * 0.90, 2)

    # P&L
    position_value  = SHARES * current_price
    cost_basis      = SHARES * AVG_COST
    pnl             = position_value - cost_basis
    pnl_pct         = (pnl / cost_basis) * 100

    # ── SIGNAL DETECTION ───────────────────────────────────
    crossed_below_sma  = prev_price >= prev_sma200 and current_price < sma200
    crossed_above_sma  = prev_price <= prev_sma200 and current_price > sma200
    hit_trailing_stop  = current_price < trailing_stop

    # ── BUILD MESSAGE ──────────────────────────────────────
    date_str = ticker.index[-1].strftime("%d/%m/%Y")
    pnl_emoji = "🟢" if pnl >= 0 else "🔴"

    if hit_trailing_stop:
        action = "🚨 SELL NOW — TRAILING STOP HIT"
    elif crossed_below_sma:
        action = "🚨 SELL NOW — CROSSED BELOW SMA200"
    elif crossed_above_sma:
        action = "🟢 BUY SIGNAL — PRICE CROSSED ABOVE SMA200"
    elif current_price > sma200:
        action = "✅ HOLD — Above SMA200, stop intact"
    else:
        action = "⚠️ CAUTION — Price below SMA200 (consider exiting)"

    msg = (
        f"📊 TQQQ Daily Report — {date_str}\n"
        f"{'─' * 30}\n"
        f"Action:        {action}\n"
        f"{'─' * 30}\n"
        f"💰 Price:      ${current_price:.2f}\n"
        f"📈 SMA200:     ${sma200:.2f}\n"
        f"🛑 Stop Loss:  ${trailing_stop:.2f}  (90% of 30d high ${recent_high:.2f})\n"
        f"{'─' * 30}\n"
        f"📦 Position:   {SHARES} shares\n"
        f"💵 Avg Cost:   ${AVG_COST:.2f}\n"
        f"💼 Value:      ${position_value:.2f}\n"
        f"{pnl_emoji} P&L:        ${pnl:+.2f} ({pnl_pct:+.2f}%)\n"
        f"{'─' * 30}\n"
        f"Entry Date:    {ENTRY_DATE}\n"
    )

    send_telegram(msg)

    # ── CONSOLE LOG ────────────────────────────────────────
    print(msg)

    # ── EXIT CODE: fail loudly if sell signal (optional) ──
    if hit_trailing_stop or crossed_below_sma:
        exit(0)  # still exits 0 so GitHub doesn't mark as failed


def send_telegram(message):
    token   = os.getenv('TELEGRAM_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    url     = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": message})


if __name__ == "__main__":
    check_strategy()
