import os
import requests
import yfinance as yf
import pandas as pd

def check_strategy():
    ticker = yf.download("TQQQ", period="2y", interval="1d", auto_adjust=True)
    
    # Flatten MultiIndex columns if present
    if isinstance(ticker.columns, pd.MultiIndex):
        ticker.columns = [c[0] for c in ticker.columns]
    
    ticker['SMA200'] = ticker['Close'].rolling(window=200).mean()
    
    current_price = float(ticker['Close'].iloc[-1])
    sma200 = float(ticker['SMA200'].iloc[-1])
    recent_high = float(ticker['High'].tail(30).max())
    trailing_stop = recent_high * 0.90
    
    print(f"Price: {current_price:.2f} | SMA200: {sma200:.2f} | TSL: {trailing_stop:.2f}")
    
    if current_price < sma200 or current_price < trailing_stop:
        reason = "below SMA200" if current_price < sma200 else "below Trailing Stop"
        msg = (
            f"⚠️ TQQQ SELL ALERT!\n"
            f"Reason: {reason}\n"
            f"Price: {current_price:.2f}\n"
            f"SMA200: {sma200:.2f}\n"
            f"TSL (90% of 30d high): {trailing_stop:.2f}"
        )
    else:
        msg = (
            f"✅ TQQQ Status OK\n"
            f"Price: {current_price:.2f}\n"
            f"SMA200: {sma200:.2f}\n"
            f"TSL: {trailing_stop:.2f}"
        )
    
    send_telegram(msg)

def send_telegram(message):
    token = os.getenv('TELEGRAM_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": message})

if __name__ == "__main__":
    check_strategy()
