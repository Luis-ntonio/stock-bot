import streamlit as st
import httpx
from app.config import settings

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
        st.warning(f"Error cargando datos de {ticker}: {e}")
    return None


@st.cache_data(ttl="15m", show_spinner=False)
def fetch_suggestions(ticker: str, limit: int = 5) -> list[dict]:
    try:
        r = httpx.get(f"{API_BASE}/suggestions/{ticker}", params={"limit": limit}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.warning(f"Error cargando sugerencias para {ticker}: {e}")
        return []


@st.cache_data(ttl="30m", show_spinner=False)
def fetch_ohlc(ticker: str, period: str, market: str) -> list[dict]:
    try:
        r = httpx.get(
            f"{API_BASE}/price/{ticker}/ohlc",
            params={"period": period, "market": market},
            timeout=20,
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        st.caption(f"⚠️ Sin datos OHLC para {ticker}: {e}")
    return []


def invalidate_ticker(ticker: str) -> None:
    """Clear every cached view of a ticker's data — call after a fresh analysis
    so all pages (not just the one that triggered it) see the new result."""
    fetch_latest_suggestion.clear(ticker)
    fetch_suggestions.clear(ticker)
