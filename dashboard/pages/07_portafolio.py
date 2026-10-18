import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import date as _date
import streamlit as st
from dashboard.api_client import (
    fetch_watchlist, fetch_positions, add_position, close_position, trigger_position_review,
)
from dashboard.job_tracker import track_job, has_active_job, poll_tracked_jobs, autorefresh_if_active
from dashboard.components.animations import inject_page_transition
from dashboard.constants import SIGNAL_COLORS

st.set_page_config(page_title="Portafolio", page_icon="💼", layout="wide")
st.title("Portafolio")
inject_page_transition()
st.markdown(
    '<p style="color:#6e7681;font-size:0.95em;margin-top:-8px;">'
    'Registra lo que compraste y fecha; el bot decide si conviene mantener o vender.'
    '</p>',
    unsafe_allow_html=True,
)

_REVIEWS_KEY = "sb_position_reviews"


def _on_review_done(meta: dict, job: dict) -> None:
    reviews = st.session_state.setdefault(_REVIEWS_KEY, {})
    reviews[meta["key"]] = job.get("result")


poll_tracked_jobs(on_done=_on_review_done)

watchlist = fetch_watchlist()
if not watchlist:
    st.warning("No hay tickers en el watchlist. Agrega uno desde la página Watchlist primero.")
    st.stop()

tickers = [t["ticker"] for t in watchlist]

# ── Formulario: nueva posición ───────────────────────────────────────────────
with st.expander("➕ Agregar posición", expanded=False):
    with st.form("new_position"):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            ticker = st.selectbox("Ticker", tickers)
        with c2:
            purchase_date = st.date_input("Fecha de compra", value=_date.today(), max_value=_date.today())
        with c3:
            purchase_price = st.number_input("Precio de compra", min_value=0.01, value=100.0, step=0.01)
        with c4:
            quantity = st.number_input("Cantidad", min_value=0.0001, value=1.0, step=1.0)
        notes = st.text_input("Notas (opcional)")
        submitted = st.form_submit_button("Agregar", type="primary")

        if submitted:
            mkt = next((t.get("market", "US") for t in watchlist if t["ticker"] == ticker), "US")
            result = add_position(ticker, mkt, purchase_date, purchase_price, quantity, notes or None)
            if result:
                st.success(f"Posición en {ticker} agregada")
                st.rerun()

# ── Listado de posiciones ────────────────────────────────────────────────────
positions = fetch_positions()

if not positions:
    st.markdown("""
<div style="padding:40px 20px;text-align:center;color:#4a5568;font-size:0.9em;">
  Sin posiciones registradas. Agrega una con <b style="color:#e6edf3;">➕ Agregar posición</b>.
</div>""", unsafe_allow_html=True)
    st.stop()

reviews = st.session_state.setdefault(_REVIEWS_KEY, {})

for pos in positions:
    days_held = (_date.today() - _date.fromisoformat(pos["purchase_date"])).days
    pid = pos["id"]
    job_key = f"pos:{pid}"

    with st.container(border=True):
        col_info, col_actions = st.columns([5, 1])
        with col_info:
            st.markdown(f"""
<div style="display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;">
  <span style="font-size:1.2em;font-weight:700;color:#e6edf3;">{pos['ticker']}</span>
  <span style="color:#6e7681;font-size:0.85em;">
    Comprado el {pos['purchase_date']} · {days_held} días en cartera
  </span>
</div>
<div style="margin-top:6px;color:#6e7681;font-size:0.85em;">
  {pos['quantity']} unidades @ ${pos['purchase_price']:.2f}
  {f" · {pos['notes']}" if pos.get('notes') else ""}
</div>
""", unsafe_allow_html=True)
        with col_actions:
            if st.button("Cerrar", key=f"close_{pid}", width="stretch"):
                if close_position(pid):
                    st.rerun()

        busy = has_active_job(job_key)
        run = st.button(
            "⏳ Revisando…" if busy else "🔍 Revisar: ¿mantener o vender?",
            key=f"review_{pid}", type="primary", disabled=busy,
        )

        if run:
            job = trigger_position_review(pid)
            if job:
                track_job(job["job_id"], key=job_key, ticker=pos["ticker"], label="Revisión")
                st.info(f"Revisión de {pos['ticker']} encolada — avisamos cuando termine.")
                st.rerun()

        if busy:
            st.caption("⏳ Revisión en curso — esta página se actualiza sola cada pocos segundos.")

        review = reviews.get(job_key)
        if review:
            rec = review["recommendation"]
            color = SIGNAL_COLORS.get(rec, "#888")
            pnl = review["unrealized_pnl_pct"]
            pnl_color = SIGNAL_COLORS["BUY"] if pnl >= 0 else SIGNAL_COLORS["SELL"]

            st.markdown(f"""
<div style="background:#0f1923;border:1px solid {color}33;border-top:2px solid {color};
            border-radius:8px;padding:18px 20px;margin-top:10px;">
  <div style="display:flex;gap:28px;align-items:flex-start;flex-wrap:wrap;">
    <div>
      <div style="font-size:0.65em;color:#4a5568;letter-spacing:0.10em;
                  text-transform:uppercase;margin-bottom:6px;">Recomendación</div>
      <div style="font-size:1.6em;font-weight:700;color:{color};">{rec}</div>
      <div style="font-family:'JetBrains Mono',monospace;color:{color};font-size:0.8em;margin-top:4px;">
        {review['confidence']*100:.0f}% confianza
      </div>
    </div>
    <div>
      <div style="font-size:0.65em;color:#4a5568;letter-spacing:0.10em;
                  text-transform:uppercase;margin-bottom:6px;">P&amp;L no realizado</div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:1.3em;font-weight:600;color:{pnl_color};">
        {pnl:+.2f}%
      </div>
      <div style="color:#6e7681;font-size:0.8em;margin-top:4px;">
        ${review['purchase_price']:.2f} → ${review['current_price']:.2f}
      </div>
    </div>
    <div>
      <div style="font-size:0.65em;color:#4a5568;letter-spacing:0.10em;
                  text-transform:uppercase;margin-bottom:6px;">Señal fresca del ticker</div>
      <div style="font-size:1.1em;font-weight:600;color:{SIGNAL_COLORS.get(review['fresh_signal'], '#888')};">
        {review['fresh_signal']}
      </div>
      <div style="color:#6e7681;font-size:0.8em;margin-top:4px;">
        {review['fresh_confidence']*100:.0f}% confianza
      </div>
    </div>
  </div>
  <div style="margin-top:16px;padding-top:14px;border-top:1px solid #1e2938;
              color:#c9d1d9;font-size:0.9em;line-height:1.6;">
    {review['reasoning']}
  </div>
</div>
""", unsafe_allow_html=True)

            if review.get("key_factors"):
                st.markdown(
                    " ".join(
                        f'<span style="display:inline-block;background:#111e2d;'
                        f'border:1px solid #1e3a5f;color:#7ea8c9;padding:3px 10px;'
                        f'border-radius:4px;font-size:0.78em;margin:6px 4px 0 0;">{f}</span>'
                        for f in review["key_factors"]
                    ),
                    unsafe_allow_html=True,
                )

            st.caption("Solo informativo — no constituye asesoramiento financiero ni fiscal.")

st.caption("Solo informativo — no constituye asesoramiento financiero.")

autorefresh_if_active()
