import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import streamlit as st
from dashboard.constants import CHART_COLORS, SIGNAL_COLORS
from dashboard.components.animations import PLOTLY_EASING


def render_price_chart(price_data: list[dict], ticker: str):
    df = pd.DataFrame(price_data)
    if df.empty or "close" not in df.columns:
        st.info("No hay datos de precio disponibles.")
        return

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df.get("date", df.index), y=df["close"],
        name="Precio", line={"color": CHART_COLORS["price"], "width": 2}
    ))

    if "SMA_50" in df.columns or "sma_50" in df.columns:
        sma50_col = "SMA_50" if "SMA_50" in df.columns else "sma_50"
        fig.add_trace(go.Scatter(
            x=df.get("date", df.index), y=df[sma50_col],
            name="SMA 50", line={"color": CHART_COLORS["sma50"], "width": 1, "dash": "dot"}
        ))

    if "SMA_200" in df.columns or "sma_200" in df.columns:
        sma200_col = "SMA_200" if "SMA_200" in df.columns else "sma_200"
        fig.add_trace(go.Scatter(
            x=df.get("date", df.index), y=df[sma200_col],
            name="SMA 200", line={"color": CHART_COLORS["sma200"], "width": 1, "dash": "dot"}
        ))

    fig.update_layout(
        title=f"{ticker} — Precio + SMA50/200",
        xaxis_title="Fecha", yaxis_title="Precio (USD)",
        height=400, paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "white"},
        legend={"bgcolor": "rgba(0,0,0,0)"},
        transition={"duration": 500, "easing": PLOTLY_EASING},
    )
    st.plotly_chart(fig, use_container_width=True)


def render_candlestick_chart(price_data: list[dict], ticker: str):
    df = pd.DataFrame(price_data)
    if df.empty or not {"open", "high", "low", "close"}.issubset(df.columns):
        st.info("No hay datos OHLC disponibles.")
        return

    date_col = "date" if "date" in df.columns else df.columns[0]
    x = df[date_col]

    from plotly.subplots import make_subplots
    has_volume = "volume" in df.columns and df["volume"].sum() > 0

    row_heights = [0.7, 0.3] if has_volume else [1]
    rows = 2 if has_volume else 1
    fig = make_subplots(
        rows=rows, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=row_heights,
    )

    # Velas
    fig.add_trace(go.Candlestick(
        x=x,
        open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name=ticker,
        increasing_line_color="#00C851",
        decreasing_line_color="#ff4444",
        increasing_fillcolor="rgba(0,200,81,0.7)",
        decreasing_fillcolor="rgba(255,68,68,0.7)",
    ), row=1, col=1)

    # Bollinger Bands
    if "BBU_20_2.0" in df.columns:
        fig.add_trace(go.Scatter(
            x=x, y=df["BBU_20_2.0"], name="BB Superior",
            line={"color": "rgba(100,180,255,0.4)", "width": 1, "dash": "dot"},
            showlegend=True,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=x, y=df["BBL_20_2.0"], name="BB Inferior",
            line={"color": "rgba(100,180,255,0.4)", "width": 1, "dash": "dot"},
            fill="tonexty",
            fillcolor="rgba(100,180,255,0.05)",
            showlegend=True,
        ), row=1, col=1)

    # SMA 50 y 200
    if "SMA_50" in df.columns:
        fig.add_trace(go.Scatter(
            x=x, y=df["SMA_50"], name="SMA 50",
            line={"color": CHART_COLORS["sma50"], "width": 1, "dash": "dot"},
        ), row=1, col=1)
    if "SMA_200" in df.columns:
        fig.add_trace(go.Scatter(
            x=x, y=df["SMA_200"], name="SMA 200",
            line={"color": CHART_COLORS["sma200"], "width": 1, "dash": "dot"},
        ), row=1, col=1)

    # Volumen
    if has_volume:
        colors = [
            "#00C851" if row["close"] >= row["open"] else "#ff4444"
            for _, row in df.iterrows()
        ]
        fig.add_trace(go.Bar(
            x=x, y=df["volume"], name="Volumen",
            marker_color=colors, showlegend=False, opacity=0.6,
        ), row=2, col=1)

    fig.update_layout(
        title=f"{ticker} — Gráfica de Velas",
        height=520,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "white"},
        legend={"bgcolor": "rgba(0,0,0,0)"},
        xaxis_rangeslider_visible=False,
        transition={"duration": 400, "easing": PLOTLY_EASING},
    )
    fig.update_xaxes(showgrid=False, color="white")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)", color="white")
    st.plotly_chart(fig, use_container_width=True)


def render_revenue_chart(earnings: list[dict], ticker: str):
    if not earnings:
        st.info("No hay datos de earnings disponibles.")
        return

    df = pd.DataFrame(earnings).dropna(subset=["eps_actual"])
    df["surprise_pct"] = df["surprise_pct"].fillna(0)
    df["color"] = df["surprise_pct"].apply(lambda x: SIGNAL_COLORS["BUY"] if x >= 0 else SIGNAL_COLORS["SELL"])

    fig = go.Figure(go.Bar(
        x=df["quarter_end"].astype(str),
        y=df["eps_actual"],
        marker_color=df["color"],
        text=df["surprise_pct"].apply(lambda x: f"{x:+.1f}%"),
        textposition="outside",
        name="EPS Actual",
    ))

    if "eps_estimate" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["quarter_end"].astype(str), y=df["eps_estimate"],
            name="EPS Estimado", mode="markers+lines",
            line={"color": "#aaa", "dash": "dot"}
        ))

    fig.update_layout(
        title=f"{ticker} — EPS Actual vs Estimado (últimos quarters)",
        height=350, paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "white"},
        transition={"duration": 500, "easing": PLOTLY_EASING},
    )
    st.plotly_chart(fig, use_container_width=True)


def render_peers_radar(peers_data: list[dict], ticker: str):
    if not peers_data:
        st.info("No hay datos de peers disponibles.")
        return

    categories = ["P/E", "Rev Growth", "Debt/Eq"]
    all_tickers = [ticker] + [p.get("ticker", "") for p in peers_data[:4]]
    values_map = {}

    # Ticker principal (placeholder — en producción vendría del estado)
    values_map[ticker] = [0.5, 0.5, 0.5]

    for p in peers_data[:4]:
        f = p.get("fundamentals", {})
        pe = min(float(f.get("pe_ratio") or 0) / 50, 1.0)
        rg = min(float(f.get("revenue_growth_yoy") or 0) + 0.5, 1.0)
        de = max(1 - min(float(f.get("debt_to_equity") or 0) / 200, 1.0), 0)
        values_map[p["ticker"]] = [pe, rg, de]

    fig = go.Figure()
    colors = CHART_COLORS["peers"]
    for i, (t, vals) in enumerate(values_map.items()):
        fig.add_trace(go.Scatterpolar(
            r=vals + [vals[0]],
            theta=categories + [categories[0]],
            fill="toself", name=t,
            line={"color": colors[i % len(colors)]},
        ))

    fig.update_layout(
        polar={"radialaxis": {"visible": True, "range": [0, 1]}},
        title=f"{ticker} vs Peers — Radar",
        height=400, paper_bgcolor="rgba(0,0,0,0)",
        font={"color": "white"},
        transition={"duration": 400, "easing": PLOTLY_EASING},
    )
    st.plotly_chart(fig, use_container_width=True)
