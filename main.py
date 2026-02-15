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
POLYGON_KEY = "YOUR_POLYGON_API_KEY"  # Replace with your Polygon API key

st.set_page_config(page_title="Intraday Scanner", layout="wide")
st.title("📊 North America Intraday Signal Scanner")

# ---------------- TIME ----------------
est = pytz.timezone("US/Eastern")
st.markdown(f"### 🕒 Live EST Time: {
