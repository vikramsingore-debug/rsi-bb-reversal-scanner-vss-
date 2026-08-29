"""
F&O Universe — RSI(40) + Bollinger Band(1.5) Reversal Scanner
================================================================
Daily EOD scanner. Conditions (all must be true):

1. Stock must be in NSE F&O (Futures & Options) universe.
2. Volume rising for at least the last 3 sessions (V[T] > V[T-1] > V[T-2]).
2.1 Delivery % (NSE bhavcopy DELIV_PER) on the latest session > 75%.
3. Previous session (T-1): daily close RSI(14) < 40 AND close < Lower
   Bollinger Band (20, 1.5 std-dev) -> stock was oversold.
4. Current session (T): daily close RSI(14) >= 40 AND close >= Lower
   Bollinger Band (20, 1.5 std-dev) -> stock has reversed back up.

Meant to run once daily after market close (bhavcopy is usually
available on NSE by early evening) via a scheduled GitHub Action.
Sends qualifying stocks as a Telegram alert.

NOTE ON DATA SOURCES:
- Price/volume history -> yfinance (Yahoo Finance), ticker.NS
- Delivery % -> NSE's official daily bhavcopy (sec_bhavdata_full),
  fetched directly from nsearchives.nseindia.com. NSE's site can be
  fussy about headers/session cookies and occasionally changes its
  file naming — if this fetch starts failing, that's the first place
  to check (see README).
- F&O universe -> attempted from NSE's fo_mktlots list, falls back to
  a static list below (STATIC_FNO_FALLBACK) if the live fetch fails.
  NSE revises the F&O list quarterly — keep the static list updated
  periodically as a safety net.
"""

import os
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
import yfinance as yf

# ---------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------
RSI_PERIOD = 14
RSI_THRESHOLD = 40
BB_PERIOD = 20
BB_STD_MULT = 1.5
VOLUME_LOOKBACK_SESSIONS = 3
DELIVERY_PCT_THRESHOLD = 75.0
MAX_TICKERS_TO_SCAN = None  # set an int for testing on a subset, None = full universe

NSE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Fallback F&O list — approximate/illustrative, verify & update periodically
# against the live NSE F&O securities list before relying on it.
STATIC_FNO_FALLBACK = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK", "BAJFINANCE",
    "ASIANPAINT", "MARUTI", "TITAN", "SUNPHARMA", "ULTRACEMCO", "NESTLEIND",
    "WIPRO", "ADANIENT", "ADANIPORTS", "TATASTEEL", "TATAMOTORS", "NTPC",
    "POWERGRID", "M&M", "HCLTECH", "BAJAJFINSV", "TECHM", "INDUSINDBK",
    "JSWSTEEL", "GRASIM", "CIPLA", "DRREDDY", "DIVISLAB", "EICHERMOT",
    "HEROMOTOCO", "BAJAJ-AUTO", "BRITANNIA", "COALINDIA", "HINDALCO",
    "APOLLOHOSP", "SBILIFE", "HDFCLIFE", "BPCL", "ONGC", "SHREECEM",
    "UPL", "TATACONSUM", "VEDL", "PIDILITIND", "DABUR", "MARICO",
    "GODREJCP", "SIEMENS", "ABB", "BEL", "HAL", "CGPOWER", "TRENT",
    "PERSISTENT", "COFORGE", "LTIM", "MPHASIS", "CHOLAFIN", "MUTHOOTFIN",
    "PFC", "RECLTD", "IRFC", "SUZLON", "INOXWIND", "ADANIGREEN",
    "ZOMATO", "PAYTM", "NYKAA", "DMART", "NAUKRI", "PIIND", "SRF",
    "AMBUJACEM", "ACC", "DLF", "GODREJPROP", "OBEROIRLTY", "CANBK",
    "PNB", "BANKBARODA", "IDFCFIRSTB", "FEDERALBNK", "AUBANK",
]


# ---------------------------------------------------------------------
# F&O UNIVERSE
# ---------------------------------------------------------------------
def get_fno_universe():
    """Try to fetch the live NSE F&O securities list; fall back to static list."""
    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=10)
        url = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"
        resp = session.get(url, headers=NSE_HEADERS, timeout=15)
        resp.raise_for_status()
        lines = resp.text.strip().splitlines()
        symbols = []
        for line in lines[1:]:
            parts = [p.strip() for p in line.split(",")]
            if parts and parts[0] and parts[0].upper() not in ("SYMBOL", ""):
                symbols.append(parts[0].upper())
        symbols = sorted(set(symbols))
        if len(symbols) > 50:  # sanity check — should be 150-200+ names
            print(f"F&O universe fetched live: {len(symbols)} symbols")
            return symbols
        raise ValueError("live list too small, falling back")
    except Exception as e:
        print(f"! Live F&O list fetch failed ({e}) — using static fallback list "
              f"({len(STATIC_FNO_FALLBACK)} symbols). Update this list periodically.")
        return STATIC_FNO_FALLBACK


# ---------------------------------------------------------------------
# NSE BHAVCOPY (for delivery %)
# ---------------------------------------------------------------------
def fetch_bhavcopy(date: datetime):
    """Fetch NSE full bhavcopy (with delivery %) for a given date. Returns DataFrame or None."""
    date_str = date.strftime("%d%m%Y")
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=10)
        resp = session.get(url, headers=NSE_HEADERS, timeout=15)
        if resp.status_code != 200 or len(resp.text) < 100:
            return None
        from io import StringIO
        df = pd.read_csv(StringIO(resp.text))
        df.columns = [c.strip() for c in df.columns]
        return df
    except Exception:
        return None


def get_latest_bhavcopy(max_days_back=7):
    """Walk backward from today until a valid bhavcopy file is found (skips weekends/holidays)."""
    d = datetime.now()
    for _ in range(max_days_back):
        df = fetch_bhavcopy(d)
        if df is not None and not df.empty:
            print(f"Bhavcopy found for {d.strftime('%Y-%m-%d')}")
            return df, d
        d -= timedelta(days=1)
    print("! Could not fetch bhavcopy for the last week — delivery% filter will be skipped/neutral.")
    return None, None


def get_delivery_pct(symbol, bhavcopy_df):
    if bhavcopy_df is None:
        return None
    try:
        row = bhavcopy_df[
            (bhavcopy_df["SYMBOL"].str.strip() == symbol) &
            (bhavcopy_df["SERIES"].str.strip() == "EQ")
        ]
        if row.empty:
            return None
        deliv_col = [c for c in bhavcopy_df.columns if "DELIV_PER" in c.upper()]
        if not deliv_col:
            return None
        val = row.iloc[0][deliv_col[0]]
        return float(val)
    except Exception:
        return None


# ---------------------------------------------------------------------
# INDICATORS
# ---------------------------------------------------------------------
def rsi(series: pd.Series, period=RSI_PERIOD):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))
    rsi_series = rsi_series.fillna(100)  # if avg_loss is 0, RSI = 100
    return rsi_series


def bollinger_lower(series: pd.Series, period=BB_PERIOD, std_mult=BB_STD_MULT):
    sma = series.rolling(period).mean()
    std = series.rolling(period).std()
    return sma - std_mult * std


# ---------------------------------------------------------------------
# SIGNAL LOGIC
# ---------------------------------------------------------------------
def check_signal(symbol, bhavcopy_df):
    ticker = f"{symbol}.NS"
    try:
        df = yf.Ticker(ticker).history(period="6mo", interval="1d")
    except Exception as e:
        return None
    if df is None or len(df) < BB_PERIOD + 5:
        return None

    close = df["Close"]
    vol = df["Volume"]

    rsi_series = rsi(close)
    lower_bb = bollinger_lower(close)

    if len(close) < 3:
        return None

    # T = latest completed session, T-1 = previous session
    close_t, close_t1 = close.iloc[-1], close.iloc[-2]
    rsi_t, rsi_t1 = rsi_series.iloc[-1], rsi_series.iloc[-2]
    bb_t, bb_t1 = lower_bb.iloc[-1], lower_bb.iloc[-2]

    if pd.isna(bb_t) or pd.isna(bb_t1) or pd.isna(rsi_t) or pd.isna(rsi_t1):
        return None

    # Condition 3: T-1 was oversold (RSI<40 and close below lower BB)
    cond_prev_oversold = (rsi_t1 < RSI_THRESHOLD) and (close_t1 < bb_t1)

    # Condition 4: T has reversed (RSI>=40 and close above/at lower BB)
    cond_curr_reversed = (rsi_t >= RSI_THRESHOLD) and (close_t >= bb_t)

    if not (cond_prev_oversold and cond_curr_reversed):
        return None

    # Condition 2: volume rising for at least last 3 sessions
    if len(vol) < VOLUME_LOOKBACK_SESSIONS:
        return None
    last_vols = vol.tail(VOLUME_LOOKBACK_SESSIONS).tolist()
    cond_volume_rising = all(last_vols[i] < last_vols[i + 1] for i in range(len(last_vols) - 1))
    if not cond_volume_rising:
        return None

    # Condition 2.1: delivery % > 75
    deliv_pct = get_delivery_pct(symbol, bhavcopy_df)
    if deliv_pct is None or deliv_pct <= DELIVERY_PCT_THRESHOLD:
        return None

    return {
        "symbol": symbol,
        "close": round(float(close_t), 2),
        "rsi_today": round(float(rsi_t), 1),
        "rsi_prev": round(float(rsi_t1), 1),
        "lower_bb_today": round(float(bb_t), 2),
        "lower_bb_prev": round(float(bb_t1), 2),
        "delivery_pct": round(deliv_pct, 1),
        "volumes_last_3": last_vols,
    }


# ---------------------------------------------------------------------
# TELEGRAM ALERT
# ---------------------------------------------------------------------
def send_telegram(text: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram creds not set — skipping alert. (set TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    text = text[:4000]
    try:
        resp = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=15)
        if resp.status_code == 200:
            print("Telegram alert sent.")
        else:
            print(f"! Telegram send failed: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"! Telegram send failed: {e}")


def build_message(hits, universe_size, bhavcopy_date):
    date_str = bhavcopy_date.strftime("%d-%b-%Y") if bhavcopy_date else "unknown"
    if not hits:
        return (f"📉 RSI/BB Reversal Scanner ({date_str})\n"
                f"Universe scanned: {universe_size} F&O stocks\n"
                f"No qualifying reversal signals today.")
    lines = [f"📈 RSI/BB Reversal Scanner ({date_str}) — {len(hits)} signal(s)\n"]
    for h in hits:
        lines.append(
            f"{h['symbol']} | Close: {h['close']} | RSI: {h['rsi_prev']}→{h['rsi_today']} "
            f"| LowerBB: {h['lower_bb_prev']}→{h['lower_bb_today']} | Deliv%: {h['delivery_pct']}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------
if __name__ == "__main__":
    universe = get_fno_universe()
    if MAX_TICKERS_TO_SCAN:
        universe = universe[:MAX_TICKERS_TO_SCAN]

    bhavcopy_df, bhavcopy_date = get_latest_bhavcopy()

    hits = []
    for i, symbol in enumerate(universe):
        result = check_signal(symbol, bhavcopy_df)
        if result:
            hits.append(result)
            print(f"  ✅ SIGNAL: {symbol}")
        if (i + 1) % 25 == 0:
            print(f"  ...scanned {i + 1}/{len(universe)}")
        time.sleep(0.1)  # small delay, be polite to Yahoo Finance

    print(f"\nScan complete. {len(hits)} signal(s) out of {len(universe)} stocks scanned.")

    if hits:
        pd.DataFrame(hits).to_csv("reversal_signals.csv", index=False)

    msg = build_message(hits, len(universe), bhavcopy_date)
    print("\n--- Telegram message ---")
    print(msg)
    send_telegram(msg)
