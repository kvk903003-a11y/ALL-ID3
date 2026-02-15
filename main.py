import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
from datetime import datetime, time as dt_time
import pytz
import time

# ---------------- SETTINGS ----------------
REFRESH_SECONDS = 60
TOP_N = 10
RISK_PER_TRADE = 0.005  # 0.5% of virtual capital
INITIAL_CAPITAL = 100000

# Polygon.io API Key (put your key here or use Streamlit secrets)
POLYGON_KEY = "YOUR_POLYGON_API_KEY"

st.set_page_config(page_title="Institutional Intraday Engine", layout="wide")
st.title("📊 Hybrid Intraday Scanner + Portfolio Tracker")

# ---------------- SESSION STATE ----------------
if "capital" not in st.session_state:
    st.session_state.capital = INITIAL_CAPITAL
if "positions" not in st.session_state:
    st.session_state.positions = []

# ---------------- TIME ----------------
est = pytz.timezone("US/Eastern")
now_est = datetime.now(est)
st.markdown(f"### 🕒 Live EST Time: {now_est.strftime('%Y-%m-%d %H:%M:%S')}")

# ---------------- MARKET HOURS ----------------
def market_status():
    now = datetime.now(est).time()
    us_open = dt_time(9,30)
    us_close = dt_time(16,0)
    tsx_open = dt_time(9,30)
    tsx_close = dt_time(16,0)
    session = "Closed"
    if us_open <= now <= us_close:
        session = "US Regular"
    elif tsx_open <= now <= tsx_close:
        session = "TSX Regular"
    return (us_open <= now <= us_close, tsx_open <= now <= tsx_close, session)

us_open, tsx_open, session_status = market_status()
st.write(f"Market Session: {session_status}")
st.write(f"⚙ Virtual Capital: ${st.session_state.capital:,.2f}")

# ---------------- LOAD TICKERS ----------------
@st.cache_data(ttl=3600)
def load_tickers():
    try:
        tsx = pd.read_csv("data/tsx_tickers.csv")["Symbol"].dropna().tolist()
    except:
        tsx = ["SHOP.TO","RY.TO","TD.TO","SU.TO","ENB.TO"]
    try:
        nasdaq = pd.read_csv("data/nasdaq_tickers.csv")["Symbol"].dropna().tolist()
    except:
        nasdaq = ["AAPL","MSFT","NVDA","TSLA","AMD"]
    try:
        nyse = pd.read_csv("data/nyse_tickers.csv")["Symbol"].dropna().tolist()
    except:
        nyse = ["JPM","XOM","BA","KO","DIS"]
    return tsx[:50], nasdaq[:50], nyse[:50]

TSX, NASDAQ, NYSE = load_tickers()

# ---------------- INDEX FILTER ----------------
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

# ---------------- POLYGON FETCH ----------------
def polygon_intraday(ticker):
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/minute/2023-01-01/2026-12-31?adjusted=true&sort=desc&limit=50000&apiKey={POLYGON_KEY}"
    try:
        r = requests.get(url)
        data = r.json()
        if "results" not in data:
            return None
        df = pd.DataFrame(data["results"])
        df["t"] = pd.to_datetime(df["t"], unit="ms")
        df.set_index("t", inplace=True)
        df.rename(columns={"o":"Open","c":"Close","h":"High","l":"Low","v":"Volume"}, inplace=True)
        return df
    except:
        return None

# ---------------- SIGNAL ENGINE ----------------
def intraday_signal(symbol, market_type):
    try:
        if market_type == "TSX":
            df = yf.download(symbol, period="5d", interval="5m", progress=False)
        else:
            df = polygon_intraday(symbol)
        if df is None or len(df) < 50:
            return None
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
        # Penalize weak market but do not block
        if market_type == "US" and not spy_bull:
            score -= 20
        if market_type == "TSX" and not tsx_bull:
            score -= 20
        entry = close.iloc[last]
        stop = entry - atr.iloc[last]
        target = entry + (atr.iloc[last]*2)
        return {
            "Symbol": symbol,
            "Score": round(score,2),
            "Buy": round(entry,2),
            "Sell Target": round(target,2),
            "Stop Loss": round(stop,2)
        }
    except:
        return None

# ---------------- SCAN MARKETS ----------------
results = []
for ticker in TSX:
    sig = intraday_signal(ticker, "TSX")
    if sig:
        results.append(sig)
for ticker in NASDAQ:
    sig = intraday_signal(ticker, "US")
    if sig:
        results.append(sig)
for ticker in NYSE:
    sig = intraday_signal(ticker, "US")
    if sig:
        results.append(sig)

# ---------------- PORTFOLIO SIMULATION ----------------
if results:
    df_results = pd.DataFrame(results)
    df_results = df_results.sort_values("Score", ascending=False)
    df_results = df_results.head(TOP_N)
    st.subheader("🔥 Top Intraday Opportunities (Best → Worst)")
    st.dataframe(df_results, use_container_width=True)

    # Simulate opening trades (paper trading)
    for _, row in df_results.iterrows():
        capital_per_trade = st.session_state.capital * RISK_PER_TRADE
        position = {
            "Symbol": row["Symbol"],
            "Entry": row["Buy"],
            "Stop": row["Stop Loss"],
            "Target": row["Sell Target"],
            "Capital": capital_per_trade
        }
        st.session_state.positions.append(position)

    st.write("📝 Simulated Positions:")
    st.dataframe(pd.DataFrame(st.session_state.positions))

else:
    st.warning("No qualifying stocks right now based on filters.")

# ---------------- AUTO REFRESH ----------------
time.sleep(REFRESH_SECONDS)
st.rerun()
