import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
from datetime import datetime, time as dt_time
import pytz
import time

# ================= SETTINGS =================
REFRESH_SECONDS = 60
TOP_N = 10

# Get Polygon key from secrets or fallback
POLYGON_KEY = st.secrets["POLYGON_KEY"] if "POLYGON_KEY" in st.secrets else "YOUR_POLYGON_API_KEY"

st.set_page_config(page_title="Efficient Intraday Scanner", layout="wide")
st.title("📊 Batch Intraday Scanner (Polygon + Yahoo)")

# ================= LIVE EST TIME =================
est = pytz.timezone("US/Eastern")
st.markdown(f"### 🕒 Live EST Time: {datetime.now(est).strftime('%Y-%m-%d %H:%M:%S')}")

# ================= MARKET HOURS =================
def market_session():
    now = datetime.now(est).time()
    us_open = dt_time(9,30)
    us_close = dt_time(16,0)
    if us_open <= now <= us_close:
        return "US Regular"
    elif us_open <= now <= us_close:
        return "TSX Regular"
    return "Closed"

session_status = market_session()
st.write(f"Market Session: {session_status}")

# ================= LOAD TICKERS =================
@st.cache_data(ttl=3600)
def load_tickers():
    tsx = pd.read_csv("data/tsx_tickers.csv")["Symbol"].dropna().tolist()[:50]
    nasdaq = pd.read_csv("data/nasdaq_tickers.csv")["Symbol"].dropna().tolist()[:50]
    nyse = pd.read_csv("data/nyse_tickers.csv")["Symbol"].dropna().tolist()[:50]
    return tsx, nasdaq, nyse

TSX, NASDAQ, NYSE = load_tickers()

# ================= INDEX TREND FILTER =================
@st.cache_data(ttl=300)
def get_index_trend(symbol):
    df = yf.download(symbol, period="6mo", interval="1d", progress=False)
    if df.empty or len(df) < 200:
        return True
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:,0]
    ema200 = close.ewm(span=200, adjust=False).mean()
    return close.iloc[-1] > ema200.iloc[-1]

spy_bull = get_index_trend("SPY")
tsx_bull = get_index_trend("^GSPTSE")
st.write(f"SPY Bullish: {spy_bull}")
st.write(f"TSX Bullish: {tsx_bull}")

# ================= POLYGON SNAPSHOT FETCH =================
def fetch_polygon_snapshot(tickers):
    """
    Fetch a snapshot of multiple US tickers in one API call.
    This endpoint returns last minute aggregates and other useful info.
    """
    symbols = ",".join(tickers)
    url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers?symbols={symbols}&apiKey={POLYGON_KEY}"
    data = requests.get(url).json()
    results = {}
    if "tickers" not in data:
        return {}
    for item in data["tickers"]:
        ticker = item["ticker"]
        # intraday bars
        bars = item.get("day", {}).get("aggregates", [])
        # if no bars, skip
        if not bars:
            continue
        df = pd.DataFrame(bars)
        # normalize polygon minute fields
        df["t"] = pd.to_datetime(df["t"], unit="ms")
        df.rename(columns={"o":"Open","c":"Close","h":"High","l":"Low","v":"Volume"}, inplace=True)
        df.set_index("t", inplace=True)
        results[ticker] = df
    return results

# ================= SIGNAL LOGIC =================
def compute_score(df):
    """
    Compute score for a symbol's intraday dataframe.
    """
    if df is None or len(df) < 30:
        return None
    try:
        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:,0]
        # Indicators
        ema10 = close.ewm(span=10, adjust=False).mean()
        ema30 = close.ewm(span=30, adjust=False).mean()
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -delta.clip(upper=0).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        atr = (high - low).rolling(14).mean()

        last = -1
        score = 0
        if ema10.iloc[last] > ema30.iloc[last]:
            score += 40
        if 45 < rsi.iloc[last] < 80:
            score += 30
        if close.iloc[last] > close.rolling(20).mean().iloc[last]:
            score += 30
        return score, close.iloc[last], atr.iloc[last]
    except:
        return None

# ================= SCAN TSX =================
results = []

for ticker in TSX:
    df = None
    try:
        df = yf.download(ticker, period="5d", interval="5m", progress=False)
    except:
        df = None
    out = compute_score(df)
    if out:
        score, entry, atr_val = out
        stop = entry - atr_val
        target = entry + (atr_val * 2)
        results.append({
            "Symbol": ticker,
            "Score": round(score,2),
            "Buy": round(entry,2),
            "Sell Target": round(target,2),
            "Stop Loss": round(stop,2)
        })

# ================= SCAN US SNAPSHOT =================
us_tickers = NASDAQ + NYSE
polygon_data = fetch_polygon_snapshot(us_tickers)

for ticker, df in polygon_data.items():
    out = compute_score(df)
    if out:
        score, entry, atr_val = out
        stop = entry - atr_val
        target = entry + (atr_val * 2)
        results.append({
            "Symbol": ticker,
            "Score": round(score,2),
            "Buy": round(entry,2),
            "Sell Target": round(target,2),
            "Stop Loss": round(stop,2)
        })

# ================= DISPLAY =================
if results:
    df_results = pd.DataFrame(results)
    df_results = df_results.sort_values("Score", ascending=False)
    df_results = df_results.head(TOP_N)
    st.subheader("🔥 Top Intraday Opportunities (Best → Worst)")
    st.dataframe(df_results, use_container_width=True)
else:
    st.warning("No qualifying stocks right now based on filters.")

# ================= AUTO REFRESH =================
time.sleep(REFRESH_SECONDS)
st.rerun()
