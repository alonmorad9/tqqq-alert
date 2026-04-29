import yfinance as yf
import requests
import os

def check_strategy():
    df = yf.download("TQQQ", period="2y", interval="1d", auto_adjust=True)
    
    # Fix MultiIndex columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_names(0) if False else [c[0] for c in df.columns]
    
    import pandas as pd
    df['SMA200'] = df['Close'].rolling(window=200).mean()
    
    current_price = float(df['Close'].iloc[-1])
    sma200 = float(df['SMA200'].iloc[-1])
    recent_high = float(df['High'].tail(30).max())
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
        send_telegram(msg)
    else:
        msg = (
            f"✅ TQQQ Status OK\n"
            f"Price: {current_price:.2f}\n"
            f"SMA200: {sma200:.2f}\n"
            f"TSL: {trailing_stop:.2f}"
        )
        send_telegram(msg)  # optional: remove this if you only want alerts

def send_telegram(message):
    token = os.getenv('TELEGRAM_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": message})

if __name__ == "__main__":
    check_strategy()
