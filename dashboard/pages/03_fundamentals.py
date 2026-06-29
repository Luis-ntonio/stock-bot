import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import httpx
import pandas as pd
from app.config import settings
from dashboard.components.charts import render_revenue_chart
from dashboard.components.animations import inject_page_transition

API_BASE = f"http://localhost:{settings.fastapi_port}/api"

st.set_page_config(page_title="Fundamentales", page_icon="📊", layout="wide")
st.title("📊 Fundamentales")
inject_page_transition()


@st.cache_data(ttl="15m")
def fetch_watchlist() -> list[str]:
    try:
        r = httpx.get(f"{API_BASE}/watchlist/", timeout=10)
        r.raise_for_status()
        return [t["ticker"] for t in r.json()]
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
    st.warning("No hay tickers en el watchlist.")
    st.stop()

ticker = st.selectbox("Selecciona un ticker", tickers)
suggestion = fetch_latest_suggestion(ticker)

if not suggestion:
    st.info(f"No hay datos disponibles para {ticker}. Ejecuta un análisis desde la página Sugerencia.")
    st.stop()

# Tabs
tab1, tab2, tab3 = st.tabs(["📈 Métricas Clave", "📉 Earnings", "ℹ️ Info"])

with tab1:
    full_output = suggestion.get("full_output") or {}
    fund = full_output.get("fundamentals") or {}

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("P/E Ratio", f"{fund.get('pe_ratio', 'N/A')}")
    col2.metric("P/B Ratio", f"{fund.get('pb_ratio', 'N/A')}")
    col3.metric("Revenue Growth YoY", f"{(fund.get('revenue_growth_yoy') or 0)*100:.1f}%" if fund.get('revenue_growth_yoy') else "N/A")
    col4.metric("Earnings Growth YoY", f"{(fund.get('earnings_growth_yoy') or 0)*100:.1f}%" if fund.get('earnings_growth_yoy') else "N/A")

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Debt/Equity", f"{fund.get('debt_to_equity', 'N/A')}")
    col6.metric("FCF Yield", f"{(fund.get('free_cash_flow_yield') or 0)*100:.1f}%" if fund.get('free_cash_flow_yield') else "N/A")
    col7.metric("EPS Surprise último Q", f"{fund.get('eps_surprise_last_q', 'N/A')}%")
    col8.metric("EPS Surprise avg 4Q", f"{fund.get('eps_surprise_avg_4q', 'N/A')}%")

with tab2:
    # Earnings data viene del full_output si lo guardamos, sino mostramos vacío
    earnings = full_output.get("earnings_history") or []
    if earnings:
        render_revenue_chart(earnings, ticker)
        st.dataframe(pd.DataFrame(earnings), use_container_width=True)
    else:
        st.info("Datos de earnings no disponibles en este análisis.")

with tab3:
    st.markdown(f"**Señal actual:** {suggestion.get('signal')} | **Confianza:** {suggestion.get('confidence', 0)*100:.0f}%")
    st.markdown(f"**Modelo LLM:** `{suggestion.get('llm_model')}`")
    st.markdown(f"**Fuentes:** {', '.join(suggestion.get('data_sources') or [])}")
    st.markdown(f"**Fecha análisis:** {str(suggestion.get('created_at', ''))[:19]}")
