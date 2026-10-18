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


@st.cache_data(ttl="5m", show_spinner=False)
def fetch_positions(active_only: bool = True) -> list[dict]:
    try:
        r = httpx.get(f"{API_BASE}/positions/", params={"active_only": active_only}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Error cargando posiciones: {e}")
        return []


def add_position(ticker: str, market: str, purchase_date, purchase_price: float,
                  quantity: float, notes: str | None = None) -> dict | None:
    try:
        r = httpx.post(
            f"{API_BASE}/positions/",
            json={
                "ticker": ticker,
                "market": market,
                "purchase_date": purchase_date.isoformat(),
                "purchase_price": purchase_price,
                "quantity": quantity,
                "notes": notes,
            },
            timeout=10,
        )
        if r.status_code >= 400:
            st.error(r.json().get("detail", r.text))
            return None
        fetch_positions.clear()
        return r.json()
    except Exception as e:
        st.error(f"Error agregando posición: {e}")
        return None


def close_position(position_id: int, hard: bool = False) -> bool:
    try:
        r = httpx.delete(f"{API_BASE}/positions/{position_id}", params={"hard": hard}, timeout=10)
        r.raise_for_status()
        fetch_positions.clear()
        return True
    except Exception as e:
        st.error(f"Error cerrando posición: {e}")
        return False


def trigger_position_review(position_id: int) -> dict | None:
    """Encola la revisión HOLD/SELL y devuelve {'job_id', 'status'} al
    instante — no bloquea. El resultado se consulta con fetch_job()."""
    try:
        r = httpx.post(f"{API_BASE}/positions/{position_id}/review", timeout=10)
        if r.status_code >= 400:
            st.error(r.json().get("detail", r.text))
            return None
        return r.json()
    except Exception as e:
        st.error(f"Error encolando revisión: {e}")
        return None


def trigger_analysis(ticker: str, market: str = "US") -> dict | None:
    """Encola un análisis completo del ticker y devuelve {'job_id', 'status'}
    al instante — no bloquea esperando el pipeline."""
    try:
        r = httpx.post(f"{API_BASE}/analysis/{ticker}", params={"market": market}, timeout=10)
        if r.status_code >= 400:
            st.error(r.json().get("detail", r.text))
            return None
        return r.json()
    except Exception as e:
        st.error(f"Error encolando análisis: {e}")
        return None


def fetch_job(job_id: int) -> dict | None:
    try:
        r = httpx.get(f"{API_BASE}/jobs/{job_id}", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass  # errores de red en el polling no deben romper la página
    return None
