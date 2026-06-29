import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import httpx
from app.config import settings
from dashboard.constants import SIGNAL_COLORS, SIGNAL_ICONS
from dashboard.components.animations import inject_page_transition

API_BASE = f"http://localhost:{settings.fastapi_port}/api"


@st.cache_data(ttl="15m", show_spinner="Cargando watchlist…")
def fetch_watchlist(market: str | None = None) -> list[dict]:
    params = {"market": market} if market else {}
    try:
        r = httpx.get(f"{API_BASE}/watchlist/", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Error conectando a la API: {e}")
        return []


@st.cache_data(ttl="15m", show_spinner=False)
def fetch_latest_suggestion(ticker: str) -> dict | None:
    try:
        r = httpx.get(f"{API_BASE}/suggestions/{ticker}/latest", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        st.caption(f"⚠️ Sin datos para {ticker}: {e}")
    return None


st.set_page_config(page_title="Watchlist", page_icon="📋", layout="wide")
st.title("📋 Watchlist")
inject_page_transition()

# Filtros
col1, col2 = st.columns([3, 1])
with col2:
    market_filter = st.selectbox("Mercado", ["Todos", "US", "CRYPTO", "LATAM"])

market_param = None if market_filter == "Todos" else market_filter
tickers = fetch_watchlist(market_param)

# Agregar ticker
with st.expander("➕ Agregar ticker al watchlist"):
    with st.form("add_ticker"):
        c1, c2, c3, c4 = st.columns(4)
        new_ticker  = c1.text_input("Ticker", placeholder="AAPL")
        new_name    = c2.text_input("Nombre", placeholder="Apple Inc.")
        new_market  = c3.selectbox("Mercado", ["US", "CRYPTO", "LATAM"])
        new_sector  = c4.text_input("Sector", placeholder="Technology")
        submitted = st.form_submit_button("Agregar")
        if submitted and new_ticker and new_name:
            try:
                r = httpx.post(
                    f"{API_BASE}/watchlist/",
                    json={"ticker": new_ticker.upper(), "name": new_name,
                          "market": new_market, "sector": new_sector or None,
                          "industry": None},
                    timeout=10,
                )
                if r.status_code == 201:
                    st.success(f"✓ {new_ticker.upper()} agregado")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(r.text)
            except Exception as e:
                st.error(str(e))

# Tabla principal
if not tickers:
    st.info("No hay tickers en el watchlist.")
else:
    SIGNAL_COLOR = SIGNAL_ICONS

    cols = st.columns([1, 2, 1, 1, 1, 1, 1])
    headers = ["Ticker", "Nombre", "Mercado", "Señal", "Confianza", "Precio", "Acción"]
    for col, h in zip(cols, headers):
        col.markdown(f"**{h}**")
    st.divider()

    for t in tickers:
        ticker_str = t["ticker"]
        sug = fetch_latest_suggestion(ticker_str)
        signal = sug["signal"] if sug else "—"
        conf   = f"{sug['confidence']*100:.0f}%" if sug else "—"
        price  = f"${sug['current_price']:.2f}" if sug else "—"

        cols = st.columns([1, 2, 1, 1, 1, 1, 1])
        cols[0].write(f"**{ticker_str}**")
        cols[1].write(t.get("name", ""))
        cols[2].write(t.get("market", ""))
        cols[3].write(f"{SIGNAL_COLOR.get(signal, '⚪')} {signal}")
        cols[4].write(conf)
        cols[5].write(price)
        if cols[6].button("Analizar", key=f"btn_{ticker_str}"):
            with st.spinner(f"Analizando {ticker_str}…"):
                try:
                    r = httpx.post(
                        f"{API_BASE}/analysis/{ticker_str}",
                        params={"market": t.get("market", "US")},
                        timeout=120,
                    )
                    if r.status_code == 200:
                        st.success(f"✓ Análisis de {ticker_str} completado")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(r.text)
                except Exception as e:
                    st.error(str(e))
