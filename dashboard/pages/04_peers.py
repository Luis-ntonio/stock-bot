import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import httpx
import pandas as pd
from app.config import settings
from dashboard.components.charts import render_peers_radar
from dashboard.constants import SIGNAL_ICONS
from dashboard.components.animations import inject_page_transition

API_BASE = f"http://localhost:{settings.fastapi_port}/api"

st.set_page_config(page_title="Peers", page_icon="🔍", layout="wide")
st.title("🔍 Comparación de Peers")
inject_page_transition()


@st.cache_data(ttl="15m")
def fetch_watchlist() -> list[str]:
    try:
        r = httpx.get(f"{API_BASE}/watchlist/", timeout=10)
        r.raise_for_status()
        return [t["ticker"] for t in r.json() if t.get("market") == "US"]
    except Exception as e:
        st.error(f"No se pudo conectar a la API: {e}")
        return []


@st.cache_data(ttl="15m")
def fetch_latest_suggestion(ticker: str) -> dict | None:
    try:
        r = httpx.get(f"{API_BASE}/suggestions/{ticker}/latest", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        st.warning(f"Error cargando datos de {ticker}: {e}")
    return None


tickers = fetch_watchlist()
if not tickers:
    st.warning("No hay tickers US en el watchlist.")
    st.stop()

ticker = st.selectbox("Selecciona un ticker US", tickers)
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
    st.dataframe(df, use_container_width=True)
else:
    st.info("No hay datos de peers disponibles.")
