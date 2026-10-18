import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from dashboard.components.animations import inject_page_transition

st.set_page_config(
    page_title="StockBot",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_page_transition()

st.title("StockBot")
st.markdown(
    '<p style="color:#6e7681;font-size:0.95em;margin-top:-8px;">'
    'Sugerencias de inversión mensuales basadas en análisis fundamental, técnico, '
    'sentimiento y macro.</p>',
    unsafe_allow_html=True,
)

st.markdown("""
<div style="margin-top:32px;display:grid;grid-template-columns:repeat(4,1fr);gap:12px;">
  <a href="/suggestion" target="_self" style="text-decoration:none;">
    <div style="background:#0f1923;border:1px solid #1e2938;border-radius:8px;padding:20px;
                transition:border-color 150ms ease;">
      <div style="font-size:0.65em;color:#00b4d8;letter-spacing:0.10em;
                  text-transform:uppercase;margin-bottom:6px;">Principal</div>
      <div style="font-size:1.05em;font-weight:600;color:#e6edf3;">Sugerencia</div>
      <div style="font-size:0.82em;color:#4a5568;margin-top:4px;">Señal activa y análisis por ticker</div>
    </div>
  </a>
  <a href="/portafolio" target="_self" style="text-decoration:none;">
    <div style="background:#0f1923;border:1px solid #1e2938;border-radius:8px;padding:20px;">
      <div style="font-size:0.65em;color:#6e7681;letter-spacing:0.10em;
                  text-transform:uppercase;margin-bottom:6px;">Posiciones</div>
      <div style="font-size:1.05em;font-weight:600;color:#e6edf3;">Portafolio</div>
      <div style="font-size:0.82em;color:#4a5568;margin-top:4px;">¿Mantener o vender según fecha de compra?</div>
    </div>
  </a>
  <a href="/fundamentals" target="_self" style="text-decoration:none;">
    <div style="background:#0f1923;border:1px solid #1e2938;border-radius:8px;padding:20px;">
      <div style="font-size:0.65em;color:#6e7681;letter-spacing:0.10em;
                  text-transform:uppercase;margin-bottom:6px;">Análisis</div>
      <div style="font-size:1.05em;font-weight:600;color:#e6edf3;">Fundamentales</div>
      <div style="font-size:0.82em;color:#4a5568;margin-top:4px;">P/E, revenue growth, deuda</div>
    </div>
  </a>
  <a href="/earnings" target="_self" style="text-decoration:none;">
    <div style="background:#0f1923;border:1px solid #1e2938;border-radius:8px;padding:20px;">
      <div style="font-size:0.65em;color:#6e7681;letter-spacing:0.10em;
                  text-transform:uppercase;margin-bottom:6px;">Calendario</div>
      <div style="font-size:1.05em;font-weight:600;color:#e6edf3;">Earnings</div>
      <div style="font-size:0.82em;color:#4a5568;margin-top:4px;">Próximos reportes e historial EPS</div>
    </div>
  </a>
</div>
<p style="margin-top:32px;font-size:0.75em;color:#4a5568;">
  Solo informativo — no constituye asesoramiento financiero.
</p>
""", unsafe_allow_html=True)
