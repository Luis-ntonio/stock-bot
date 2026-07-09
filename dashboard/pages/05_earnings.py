import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
import pandas as pd
from dashboard.api_client import fetch_watchlist, fetch_latest_suggestion as fetch_suggestion
from dashboard.constants import SIGNAL_COLORS
from dashboard.components.animations import inject_page_transition

st.set_page_config(page_title="Earnings", page_icon="📅", layout="wide")
st.title("📅 Earnings Calendar & History")
inject_page_transition()

tickers = fetch_watchlist()
if not tickers:
    st.warning("No hay tickers en el watchlist.")
    st.stop()

# Agregar datos de EPS surprise para todos los tickers US con sugerencia
st.subheader("Historial EPS Surprise")
rows = []
for t in tickers:
    if t.get("market") != "US":
        continue
    sug = fetch_suggestion(t["ticker"])
    if not sug:
        continue
    full = sug.get("full_output") or {}
    earnings = full.get("earnings_history") or []
    for e in earnings[:4]:
        sp = e.get("surprise_pct")
        rows.append({
            "Ticker": t["ticker"],
            "Nombre": t.get("name", ""),
            "Quarter": e.get("quarter_end", ""),
            "EPS Est": e.get("eps_estimate"),
            "EPS Real": e.get("eps_actual"),
            "Surprise %": f"{sp:+.1f}%" if sp is not None else "N/A",
            "Beat/Miss": "✅ Beat" if (sp or 0) >= 0 else "❌ Miss",
        })

if rows:
    df = pd.DataFrame(rows)
    st.dataframe(
        df.style.map(
            lambda v: f"color: {SIGNAL_COLORS['BUY']}" if "Beat" in str(v) else (f"color: {SIGNAL_COLORS['SELL']}" if "Miss" in str(v) else ""),
            subset=["Beat/Miss"]
        ),
        width="stretch",
    )
else:
    st.info("No hay datos de earnings. Ejecuta análisis desde la página Watchlist.")

st.subheader("Próximos Earnings")
from datetime import date as _date, datetime as _datetime
upcoming_rows = []
for t in tickers:
    if t.get("market") != "US":
        continue
    sug = fetch_suggestion(t["ticker"])
    if not sug:
        continue
    ue = (sug.get("full_output") or {}).get("upcoming_earnings")
    if not ue or not ue.get("date"):
        continue
    try:
        days_away = (_datetime.strptime(ue["date"], "%Y-%m-%d").date() - _date.today()).days
    except Exception:
        continue
    hour_map = {"BMO": "Antes apertura", "AMC": "Después cierre", "DMH": "Durante mercado"}
    upcoming_rows.append({
        "Ticker": t["ticker"],
        "Nombre": t.get("name", ""),
        "Fecha": ue["date"],
        "Días": days_away,
        "EPS est": ue.get("eps_estimate", "N/A"),
        "Revenue est": ue.get("revenue_estimate", "N/A"),
        "Horario": hour_map.get(ue.get("hour", ""), ue.get("hour", "")),
    })

if upcoming_rows:
    df_upcoming = pd.DataFrame(upcoming_rows).sort_values("Días")
    st.dataframe(df_upcoming, width="stretch")
else:
    st.info("Sin earnings próximos en los siguientes 60 días para los tickers analizados. Ejecuta análisis primero.")
