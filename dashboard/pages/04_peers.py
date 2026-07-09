import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
from dashboard.api_client import fetch_watchlist, fetch_latest_suggestion
from dashboard.components.charts import render_peers_radar
from dashboard.constants import SIGNAL_ICONS
from dashboard.components.animations import inject_page_transition

st.set_page_config(page_title="Peers", page_icon="🔍", layout="wide")
st.title("🔍 Comparación de Peers")
inject_page_transition()

tickers = [t["ticker"] for t in fetch_watchlist() if t.get("market") in ("US", "EU", "LATAM")]
if not tickers:
    st.warning("No hay tickers con datos de peers en el watchlist (US, EU, LATAM).")
    st.stop()

ticker = st.selectbox("Selecciona un ticker", tickers)
suggestion = fetch_latest_suggestion(ticker)

if not suggestion:
    st.info(f"No hay datos para {ticker}. Ejecuta un análisis primero.")
    st.stop()

full_output = suggestion.get("full_output") or {}
peers = full_output.get("peers") or []

col1, col2 = st.columns([2, 1])
with col1:
    render_peers_radar(peers, ticker)

with col2:
    st.subheader("Señales de Peers")
    SIGNAL_COLOR = SIGNAL_ICONS
    for p in peers:
        signal = p.get("signal", "—")
        st.markdown(
            f"**{p.get('ticker', '')}** — {SIGNAL_COLOR.get(signal,'⚪')} {signal} | "
            f"P/E: {p.get('pe_ratio', 'N/A')}"
        )

st.subheader("Tabla Comparativa")
if peers:
    df = pd.DataFrame(peers)
    st.dataframe(df, width="stretch")
else:
    st.info("No hay datos de peers disponibles.")
