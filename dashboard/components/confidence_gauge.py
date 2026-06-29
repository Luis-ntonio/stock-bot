import plotly.graph_objects as go
import streamlit as st
from dashboard.constants import SIGNAL_COLORS
from dashboard.components.animations import PLOTLY_EASING


def render_confidence_gauge(confidence: float, signal: str = "HOLD"):
    color = SIGNAL_COLORS.get(signal, "#888")

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=confidence * 100,
        number={"suffix": "%", "font": {"size": 28}},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": color},
            "steps": [
                {"range": [0, 33], "color": "#1a1a2e"},
                {"range": [33, 66], "color": "#16213e"},
                {"range": [66, 100], "color": "#0f3460"},
            ],
            "threshold": {
                "line": {"color": "white", "width": 3},
                "thickness": 0.75,
                "value": confidence * 100,
            },
        },
        title={"text": "Confianza", "font": {"size": 16}},
    ))

    fig.update_layout(
        height=220,
        margin={"t": 40, "b": 0, "l": 20, "r": 20},
        paper_bgcolor="rgba(0,0,0,0)",
        font={"color": "white"},
        transition={"duration": 400, "easing": PLOTLY_EASING},
    )

    st.plotly_chart(fig, use_container_width=True)
