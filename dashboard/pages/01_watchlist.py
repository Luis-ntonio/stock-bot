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
    market_filter = st.selectbox("Mercado", ["Todos", "US", "CRYPTO", "LATAM", "EU"])

market_param = None if market_filter == "Todos" else market_filter
tickers = fetch_watchlist(market_param)

# Agregar ticker
with st.expander("➕ Agregar ticker al watchlist"):
    lk1, lk2, lk3 = st.columns([2, 2, 1])
    lookup_ticker = lk1.text_input("Ticker", placeholder="AAPL", key="add_ticker_input").upper().strip()
    lookup_market = lk2.selectbox("Mercado", ["US", "CRYPTO", "LATAM", "EU"], key="add_market_input")
    lk3.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    if lk3.button("🔍 Buscar", key="lookup_btn", use_container_width=True):
        if not lookup_ticker:
            st.warning("Ingresa un ticker primero")
        else:
            with st.spinner(f"Buscando {lookup_ticker}…"):
                try:
                    r = httpx.get(
                        f"{API_BASE}/watchlist/lookup",
                        params={"ticker": lookup_ticker, "market": lookup_market},
                        timeout=15,
                    )
                    if r.status_code == 200:
                        info = r.json()
                        st.session_state["lookup_key"] = (lookup_ticker, lookup_market)
                        st.session_state["lookup_result"] = info
                        if not info.get("name"):
                            st.warning(
                                f"No se encontró {lookup_ticker} en mercado {lookup_market}. "
                                "Verifica el ticker/mercado o completa los campos manualmente."
                            )
                    else:
                        st.error(r.text)
                except Exception as e:
                    st.error(str(e))

    # Sólo usar el resultado de búsqueda si sigue correspondiendo al ticker/mercado actuales
    lookup_result = {}
    if st.session_state.get("lookup_key") == (lookup_ticker, lookup_market):
        lookup_result = st.session_state.get("lookup_result") or {}

    with st.form("add_ticker"):
        c1, c2 = st.columns(2)
        new_name = c1.text_input("Nombre", value=lookup_result.get("name") or "", placeholder="Apple Inc.")
        new_sector = c2.text_input("Sector", value=lookup_result.get("sector") or "", placeholder="Technology")
        submitted = st.form_submit_button("➕ Agregar")
        if submitted:
            if not lookup_ticker or not new_name:
                st.error("Ticker y nombre son obligatorios (usa 'Buscar' o complétalos manualmente)")
            else:
                try:
                    r = httpx.post(
                        f"{API_BASE}/watchlist/",
                        json={"ticker": lookup_ticker, "name": new_name,
                              "market": lookup_market, "sector": new_sector or None,
                              "industry": lookup_result.get("industry")},
                        timeout=10,
                    )
                    if r.status_code == 201:
                        st.success(f"✓ {lookup_ticker} agregado")
                        st.session_state.pop("lookup_key", None)
                        st.session_state.pop("lookup_result", None)
                        fetch_watchlist.clear()
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

    cols = st.columns([1, 2, 1, 1, 1, 1, 1, 1])
    headers = ["Ticker", "Nombre", "Mercado", "Señal", "Confianza", "Precio", "Acción", ""]
    for col, h in zip(cols, headers):
        col.markdown(f"**{h}**")
    st.divider()

    for t in tickers:
        ticker_str = t["ticker"]
        sug = fetch_latest_suggestion(ticker_str)
        signal = sug["signal"] if sug else "—"
        conf   = f"{sug['confidence']*100:.0f}%" if sug else "—"
        price  = f"${sug['current_price']:.2f}" if sug else "—"

        cols = st.columns([1, 2, 1, 1, 1, 1, 1, 1])
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
                        fetch_latest_suggestion.clear(ticker_str)
                        st.rerun()
                    else:
                        st.error(r.text)
                except Exception as e:
                    st.error(str(e))

        confirm_key = f"confirm_del_{ticker_str}"
        if not st.session_state.get(confirm_key):
            if cols[7].button("🗑️", key=f"del_{ticker_str}", help=f"Eliminar {ticker_str}"):
                st.session_state[confirm_key] = True
                st.rerun()
        else:
            if cols[7].button("⚠️ Confirmar", key=f"del_confirm_{ticker_str}"):
                try:
                    r = httpx.delete(f"{API_BASE}/watchlist/{ticker_str}", timeout=10)
                    if r.status_code == 204:
                        st.success(f"✓ {ticker_str} eliminado")
                        st.session_state.pop(confirm_key, None)
                        fetch_watchlist.clear()
                        fetch_latest_suggestion.clear(ticker_str)
                        st.rerun()
                    else:
                        st.error(r.text)
                except Exception as e:
                    st.error(str(e))
