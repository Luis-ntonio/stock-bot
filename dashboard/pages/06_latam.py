import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import httpx
import asyncio
from app.config import settings
from app.data.latam import BVL_TICKERS_YF, PERU_ADRS, LATAM_INDICES
from dashboard.constants import SIGNAL_ICONS, SIGNAL_COLORS
from dashboard.components.animations import inject_page_transition, EASING

API_BASE = f"http://localhost:{settings.fastapi_port}/api"

st.set_page_config(page_title="LATAM / Perú", page_icon="🌎", layout="wide")
st.title("🌎 LATAM / Perú")
inject_page_transition()

st.info(
    "Los tickers **.LM** (Bolsa de Valores de Lima) pueden tener datos con delay de hasta 20 minutos "
    "y en ocasiones datos insuficientes para indicadores técnicos. "
    "Los **ADRs peruanos** en NYSE ofrecen datos más confiables."
)

# ── ADRs peruanos ───────────────────────────────────────────────────────────
st.subheader("ADRs Peruanos (NYSE)")


@st.cache_data(ttl="15m")
def fetch_suggestion(ticker: str) -> dict | None:
    try:
        r = httpx.get(f"{API_BASE}/suggestions/{ticker}/latest", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        st.warning(f"Error cargando sugerencia de {ticker}: {e}")
    return None


SIGNAL_COLOR = SIGNAL_ICONS

cols = st.columns(len(PERU_ADRS))
for col, (ticker, name) in zip(cols, PERU_ADRS.items()):
    sug = fetch_suggestion(ticker)
    with col:
        st.markdown(f"**{ticker}**")
        st.caption(name)
        if sug:
            signal = sug.get("signal", "—")
            price  = sug.get("current_price", 0)
            conf   = sug.get("confidence", 0)
            st.markdown(f"{SIGNAL_COLOR.get(signal,'⚪')} **{signal}**")
            st.markdown(f"Precio: ${price:.2f}")
            st.markdown(f"Confianza: {conf*100:.0f}%")
        else:
            st.caption("Sin análisis — usa la página Watchlist")

# ── Tickers BVL ─────────────────────────────────────────────────────────────
st.subheader("Tickers BVL (.LM)")
st.markdown("Para analizar estos tickers, agrégalos al watchlist con mercado **LATAM**.")

bvl_data = []
for nemonico, yf_ticker in BVL_TICKERS_YF.items():
    sug = fetch_suggestion(nemonico)
    bvl_data.append({
        "Nemónico": nemonico,
        "Ticker yfinance": yf_ticker,
        "Señal": sug.get("signal", "—") if sug else "Sin análisis",
        "Precio": f"${sug.get('current_price', 0):.2f}" if sug else "—",
    })

import pandas as pd
st.dataframe(pd.DataFrame(bvl_data), use_container_width=True)

# ── Índices LATAM ────────────────────────────────────────────────────────────
st.subheader("Índices LATAM")
st.caption("Fuente: Yahoo Finance")

@st.cache_data(ttl="1h", show_spinner="Cargando índices LATAM…")
def fetch_latam_indices() -> dict:
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        from app.data.latam import get_latam_indices
        return loop.run_until_complete(get_latam_indices())
    except Exception as e:
        st.warning(f"Error cargando índices LATAM: {e}")
        return {}

indices = fetch_latam_indices()
if indices:
    idx_cols = st.columns(len(indices))
    for i, (col, (ticker_idx, data)) in enumerate(zip(idx_cols, indices.items())):
        with col:
            change = data.get("change_pct", 0)
            color = SIGNAL_COLORS["BUY"] if change >= 0 else SIGNAL_COLORS["SELL"]
            delay = i * 40
            st.markdown(f"""
<div style="animation: sb-fade-in 200ms {delay}ms {EASING} both;">
  <div style="font-weight:600; margin-bottom:4px;">{data.get('name', ticker_idx)}</div>
  <div style="font-size:1.3em;">{data.get('price', 0):,.2f}</div>
  <div style="color:{color};">{change:+.2f}%</div>
</div>""", unsafe_allow_html=True)
else:
    st.info("Cargando índices LATAM…")
