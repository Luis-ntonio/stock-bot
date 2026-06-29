import streamlit as st
from dashboard.constants import SIGNAL_COLORS
from dashboard.components.animations import inject_animations, SIGNAL_CARD_ANIM

_BUY  = SIGNAL_COLORS["BUY"]   # #00C851
_SELL = SIGNAL_COLORS["SELL"]  # #ff4444
_HOLD = SIGNAL_COLORS["HOLD"]  # #ffbb33
_RISK_COLORS = {"low": "#00C851", "medium": "#ffbb33", "high": "#ff4444"}
_MONO = "font-family:'JetBrains Mono','Cascadia Code',monospace;"


def get_conviction(signal: str, confidence: float) -> str:
    if signal == "BUY":
        if confidence >= 0.70: return "STRONG BUY"
        if confidence >= 0.50: return "BUY"
        return "WEAK BUY"
    if signal == "SELL":
        if confidence >= 0.70: return "STRONG SELL"
        return "SELL"
    return "HOLD"


def _card_glow(signal: str, confidence: float) -> str:
    if signal == "BUY" and confidence >= 0.70:
        return "0 0 56px -12px rgba(0,200,81,0.40), 0 0 0 1px rgba(0,200,81,0.12)"
    if signal == "SELL" and confidence >= 0.70:
        return "0 0 56px -12px rgba(255,68,68,0.35), 0 0 0 1px rgba(255,68,68,0.10)"
    return "none"


def render_signal_card(suggestion: dict):
    inject_animations()

    signal     = suggestion.get("signal", "HOLD")
    confidence = suggestion.get("confidence", 0)
    ticker     = suggestion.get("ticker", "")
    name       = suggestion.get("company_name", ticker)
    market     = suggestion.get("market", "US")
    price      = suggestion.get("current_price", 0)
    timeframe  = suggestion.get("timeframe", "1M")
    risk       = suggestion.get("risk_level", "medium").lower()
    t_low      = suggestion.get("target_price_low")
    t_base     = suggestion.get("target_price_base")
    t_high     = suggestion.get("target_price_high")
    bull_case  = suggestion.get("bull_case", "")
    bear_case  = suggestion.get("bear_case", "")
    reasoning  = suggestion.get("final_reasoning", "")
    analysis_date = suggestion.get("analysis_date", "")
    llm_model  = suggestion.get("llm_model_used", "")
    sources    = suggestion.get("data_sources", [])

    color      = SIGNAL_COLORS.get(signal, "#888")
    conv       = get_conviction(signal, confidence)
    glow       = _card_glow(signal, confidence)
    conf_pct   = confidence * 100
    risk_color = _RISK_COLORS.get(risk, "#888")

    # Target value with upside %
    if t_base and price:
        upside    = (t_base - price) / price * 100
        up_color  = _BUY if upside >= 0 else _SELL
        target_val = (
            f'<span style="{_MONO}color:#e6edf3;">${t_base:.2f}</span>'
            f' <span style="color:{up_color};font-size:0.8em;">({upside:+.1f}%)</span>'
        )
    elif t_base:
        target_val = f'<span style="{_MONO}color:#e6edf3;">${t_base:.2f}</span>'
    else:
        target_val = '<span style="color:#4a5568;">—</span>'

    # Target range strip
    range_html = ""
    if t_low and t_high and t_base:
        range_html = f"""
<div style="padding:10px 20px 12px;border-top:1px solid #1e2938;
            display:flex;align-items:center;gap:12px;">
  <span style="font-size:0.65em;color:#4a5568;letter-spacing:0.08em;
               text-transform:uppercase;white-space:nowrap;">Rango target</span>
  <span style="{_MONO}color:#6e7681;font-size:0.8em;">${t_low:.2f}</span>
  <div style="flex:1;height:3px;background:#1a2332;border-radius:2px;position:relative;">
    <div style="position:absolute;left:0;right:0;top:0;bottom:0;
                background:linear-gradient(90deg,{color}18,{color}36);border-radius:2px;"></div>
  </div>
  <span style="{_MONO}color:{color};font-size:0.8em;font-weight:600;">${t_base:.2f}</span>
  <div style="width:32px;height:3px;background:#1a2332;border-radius:2px;"></div>
  <span style="{_MONO}color:#6e7681;font-size:0.8em;">${t_high:.2f}</span>
</div>"""

    # ── Main card ────────────────────────────────────────────────────────────
    st.markdown(f"""
<div style="background:#0f1923;border:1px solid {color}22;border-top:2px solid {color};
            border-radius:8px;overflow:hidden;box-shadow:{glow};
            animation:{SIGNAL_CARD_ANIM};">
  <div style="display:flex;justify-content:space-between;align-items:center;
              padding:10px 20px;background:#0d1117;border-bottom:1px solid #1e2938;">
    <div style="display:flex;align-items:baseline;gap:10px;">
      <span style="font-size:1.25em;font-weight:700;color:#e6edf3;letter-spacing:-0.02em;">{ticker}</span>
      <span style="color:#4a5568;font-size:0.85em;">{name}</span>
      <span style="background:#1a2332;color:#6e7681;padding:2px 7px;border-radius:4px;
                  font-size:0.7em;{_MONO}">{market}</span>
    </div>
    <span style="{_MONO}color:#4a5568;font-size:0.75em;">{str(analysis_date)[:10]}</span>
  </div>
  <div style="display:flex;align-items:stretch;padding:20px 20px 16px;">
    <div style="flex:0 0 auto;padding-right:28px;border-right:1px solid #1e2938;min-width:168px;">
      <div style="font-size:0.65em;color:#4a5568;letter-spacing:0.10em;
                  text-transform:uppercase;margin-bottom:6px;">Señal</div>
      <div style="font-size:2.0em;font-weight:700;color:{color};
                  letter-spacing:-0.03em;line-height:1;">{conv}</div>
      <div style="margin-top:14px;">
        <div style="background:#1a2332;border-radius:2px;height:3px;overflow:hidden;">
          <div style="background:{color};width:{conf_pct:.0f}%;height:100%;border-radius:2px;"></div>
        </div>
        <div style="margin-top:5px;{_MONO}font-size:0.75em;color:{color};">{conf_pct:.0f}% confianza</div>
      </div>
    </div>
    <div style="flex:1;padding-left:28px;display:grid;
                grid-template-columns:repeat(4,1fr);gap:20px;align-items:start;">
      <div>
        <div style="font-size:0.65em;color:#4a5568;letter-spacing:0.08em;
                    text-transform:uppercase;margin-bottom:5px;">Precio</div>
        <div style="font-size:1.05em;font-weight:600;{_MONO}color:#e6edf3;">${price:.2f}</div>
      </div>
      <div>
        <div style="font-size:0.65em;color:#4a5568;letter-spacing:0.08em;
                    text-transform:uppercase;margin-bottom:5px;">Target base</div>
        <div style="font-size:1.05em;font-weight:600;">{target_val}</div>
      </div>
      <div>
        <div style="font-size:0.65em;color:#4a5568;letter-spacing:0.08em;
                    text-transform:uppercase;margin-bottom:5px;">Horizonte</div>
        <div style="font-size:1.05em;font-weight:600;{_MONO}color:#e6edf3;">{timeframe}</div>
      </div>
      <div>
        <div style="font-size:0.65em;color:#4a5568;letter-spacing:0.08em;
                    text-transform:uppercase;margin-bottom:5px;">Riesgo</div>
        <div style="font-size:1.05em;font-weight:600;{_MONO}color:{risk_color};">{risk.upper()}</div>
      </div>
    </div>
  </div>

  {range_html}
</div>
""", unsafe_allow_html=True)

    # ── Bull / Bear cases ────────────────────────────────────────────────────
    if bull_case or bear_case:
        st.markdown(f"""
<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px;">
  <div style="background:rgba(0,200,81,0.04);border:1px solid rgba(0,200,81,0.14);
              border-radius:6px;padding:16px 18px;">
    <div style="font-size:0.65em;color:{_BUY};letter-spacing:0.10em;font-weight:600;
                text-transform:uppercase;margin-bottom:8px;">Bull case</div>
    <div style="color:#c9d1d9;font-size:0.88em;line-height:1.65;">{bull_case}</div>
  </div>
  <div style="background:rgba(255,68,68,0.04);border:1px solid rgba(255,68,68,0.14);
              border-radius:6px;padding:16px 18px;">
    <div style="font-size:0.65em;color:{_SELL};letter-spacing:0.10em;font-weight:600;
                text-transform:uppercase;margin-bottom:8px;">Bear case</div>
    <div style="color:#c9d1d9;font-size:0.88em;line-height:1.65;">{bear_case}</div>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── Reasoning ────────────────────────────────────────────────────────────
    if reasoning:
        with st.expander("Razonamiento del modelo"):
            st.markdown(
                f'<div style="color:#c9d1d9;font-size:0.9em;line-height:1.7;">{reasoning}</div>',
                unsafe_allow_html=True,
            )

    # ── Meta ─────────────────────────────────────────────────────────────────
    if llm_model or sources:
        st.caption(f"Modelo: `{llm_model}` · Fuentes: {', '.join(sources)}")
    st.caption("Solo informativo — no constituye asesoramiento financiero.")
