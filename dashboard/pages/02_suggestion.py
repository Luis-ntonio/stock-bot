import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import httpx
from datetime import date as _date
from app.config import settings
from dashboard.components.signal_card import render_signal_card, get_conviction
from dashboard.components.animations import EASING, inject_page_transition
from dashboard.components.charts import render_candlestick_chart
from dashboard.constants import SIGNAL_COLORS

API_BASE = f"http://localhost:{settings.fastapi_port}/api"

st.set_page_config(page_title="Sugerencia", page_icon="💡", layout="wide")
st.title("Sugerencia")
inject_page_transition()


@st.cache_data(ttl="15m")
def fetch_watchlist() -> list[dict]:
    try:
        r = httpx.get(f"{API_BASE}/watchlist/", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"No se pudo conectar a la API: {e}. ¿Está corriendo `uvicorn app.main:app`?")
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


@st.cache_data(ttl="15m")
def fetch_suggestions(ticker: str) -> list[dict]:
    try:
        r = httpx.get(f"{API_BASE}/suggestions/{ticker}", params={"limit": 5}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.warning(f"Error cargando sugerencias para {ticker}: {e}")
        return []


# ── Ticker selector + run button ─────────────────────────────────────────────
watchlist = fetch_watchlist()
if not watchlist:
    st.warning("No hay tickers en el watchlist. Agrega uno desde la página Watchlist.")
    st.stop()

tickers = [t["ticker"] for t in watchlist]

col_sel, col_btn, col_sp = st.columns([2, 1, 4])
with col_sel:
    ticker = st.selectbox("Ticker", tickers, label_visibility="collapsed")
with col_btn:
    run = st.button("↻ Analizar", type="primary", use_container_width=True)

if run:
    mkt = next((t.get("market", "US") for t in watchlist if t["ticker"] == ticker), "US")
    with st.spinner(f"Analizando {ticker}… (1–2 minutos)"):
        try:
            r = httpx.post(
                f"{API_BASE}/analysis/{ticker}",
                params={"market": mkt},
                timeout=180,
            )
            if r.status_code == 200:
                st.success("Análisis completado")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(r.text)
        except Exception as e:
            st.error(str(e))

# ── Suggestions ───────────────────────────────────────────────────────────────
suggestions = fetch_suggestions(ticker)

if not suggestions:
    st.markdown("""
<div style="padding:40px 20px;text-align:center;color:#4a5568;font-size:0.9em;">
  Sin análisis para este ticker. Pulsa <b style="color:#e6edf3;">↻ Analizar</b> para generarlo.
</div>""", unsafe_allow_html=True)
    st.stop()

latest = suggestions[0]
full   = latest.get("full_output") or {}

# ── Signal hero card (full-width) ─────────────────────────────────────────────
render_signal_card(latest)

# ── Earnings alert ────────────────────────────────────────────────────────────
ue = full.get("upcoming_earnings")
if ue and ue.get("date"):
    try:
        days_away = (_date.fromisoformat(ue["date"]) - _date.today()).days
        if days_away <= 30:
            hour_map = {"BMO": "antes de apertura", "AMC": "después de cierre", "DMH": "durante mercado"}
            hour_str = hour_map.get(ue.get("hour", ""), "")
            st.markdown(f"""
<div style="display:flex;align-items:center;gap:10px;margin-top:12px;
            padding:10px 16px;background:rgba(255,187,51,0.05);
            border:1px solid rgba(255,187,51,0.25);border-radius:6px;
            animation:sb-earnings-glow 2s ease-in-out 0.3s 3 both;">
  <span style="color:#ffbb33;font-size:0.8em;">▲</span>
  <span style="color:#ffbb33;font-size:0.85em;">
    Earnings en <b>{days_away} días</b> ({ue["date"]}) {hour_str} — volatilidad esperada
  </span>
</div>""", unsafe_allow_html=True)
    except Exception:
        pass

# ── Chart patterns ────────────────────────────────────────────────────────────
patterns = full.get("chart_patterns", [])
if patterns:
    badges = " ".join(
        f'<span style="--i:{i};display:inline-block;background:#111e2d;'
        f'border:1px solid #1e3a5f;color:#7ea8c9;padding:3px 10px;border-radius:4px;'
        f'font-size:0.78em;margin:2px;letter-spacing:0.02em;'
        f'animation:sb-fade-in 180ms calc(var(--i)*55ms) {EASING} both;">{p}</span>'
        for i, p in enumerate(patterns)
    )
    st.markdown(
        f'<div style="margin-top:12px;color:#4a5568;font-size:0.72em;'
        f'letter-spacing:0.08em;text-transform:uppercase;margin-bottom:6px;">Patrones</div>'
        f'<div style="margin-bottom:4px;">{badges}</div>',
        unsafe_allow_html=True,
    )

# ── Candlestick Chart ─────────────────────────────────────────────────────────
mkt = next((t.get("market", "US") for t in watchlist if t["ticker"] == ticker), "US")
with st.expander("📈 Gráfica de Velas", expanded=True):
    period_opt = st.radio(
        "Período",
        ["1mo", "3mo", "6mo", "1y", "2y"],
        index=2,
        horizontal=True,
        label_visibility="collapsed",
        key="candle_period",
    )
    with st.spinner("Cargando datos de precio…"):
        ohlc_data = fetch_ohlc(ticker, period_opt, mkt)
    if ohlc_data:
        render_candlestick_chart(ohlc_data, ticker)
    else:
        st.info("No hay datos de precio disponibles para este ticker.")

# ── History ───────────────────────────────────────────────────────────────────
if len(suggestions) > 1:
    hist_rows = ""
    for s in suggestions[1:]:
        sig   = s.get("signal", "—")
        dstr  = str(s.get("created_at", ""))[:10]
        conf  = s.get("confidence", 0)
        px    = s.get("current_price", 0)
        col   = SIGNAL_COLORS.get(sig, "#555")
        conv  = get_conviction(sig, conf) if sig in ("BUY", "SELL", "HOLD") else sig
        hist_rows += f"""
<div style="display:grid;grid-template-columns:100px 130px 60px 1fr;
            gap:0;padding:9px 0;border-bottom:1px solid #12191f;align-items:center;">
  <span style="font-family:'JetBrains Mono',monospace;color:#4a5568;font-size:0.78em;">{dstr}</span>
  <span style="color:{col};font-size:0.82em;font-weight:600;">{conv}</span>
  <span style="font-family:'JetBrains Mono',monospace;color:#4a5568;font-size:0.78em;">{conf*100:.0f}%</span>
  <span style="font-family:'JetBrains Mono',monospace;color:#6e7681;font-size:0.78em;">${px:.2f}</span>
</div>"""

    st.markdown(f"""
<div style="margin-top:28px;">
  <div style="font-size:0.65em;color:#4a5568;letter-spacing:0.10em;text-transform:uppercase;
              padding-bottom:8px;border-bottom:1px solid #1e2938;margin-bottom:2px;">
    Historial reciente
  </div>
  <div style="display:grid;grid-template-columns:100px 130px 60px 1fr;
              gap:0;padding:7px 0 6px;border-bottom:1px solid #1e2938;">
    <span style="font-size:0.65em;color:#4a5568;letter-spacing:0.08em;text-transform:uppercase;">Fecha</span>
    <span style="font-size:0.65em;color:#4a5568;letter-spacing:0.08em;text-transform:uppercase;">Señal</span>
    <span style="font-size:0.65em;color:#4a5568;letter-spacing:0.08em;text-transform:uppercase;">Conf.</span>
    <span style="font-size:0.65em;color:#4a5568;letter-spacing:0.08em;text-transform:uppercase;">Precio</span>
  </div>
  {hist_rows}
</div>
""", unsafe_allow_html=True)

    # Individual reasoning expanders below the table
    for s in suggestions[1:]:
        dstr = str(s.get("created_at", ""))[:10]
        with st.expander(f"Razonamiento {dstr}", expanded=False):
            st.write(s.get("final_reasoning", ""))
