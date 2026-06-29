import streamlit as st

# ── Fonts + Global Typography + Sidebar ─────────────────────────────────────
_GLOBAL_STYLES = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Base font ── */
html, body, [data-testid="stAppViewContainer"],
[data-testid="stSidebar"], .stMarkdown, .stAlert,
.stSelectbox, .stTextInput, .stButton, .stCaption {
    font-family: 'Space Grotesk', system-ui, -apple-system, sans-serif !important;
}

/* ── Headings ── */
[data-testid="stAppViewContainer"] h1 {
    font-family: 'Space Grotesk', system-ui, sans-serif !important;
    font-size: 1.65rem !important;
    font-weight: 700 !important;
    letter-spacing: -0.03em !important;
    line-height: 1.2 !important;
}
[data-testid="stAppViewContainer"] h2,
[data-testid="stAppViewContainer"] h3 {
    font-family: 'Space Grotesk', system-ui, sans-serif !important;
    font-weight: 600 !important;
    letter-spacing: -0.02em !important;
    line-height: 1.3 !important;
}

/* ── Monospace: tickers, prices, code ── */
code, pre, [data-testid="stCode"],
.stCode, kbd {
    font-family: 'JetBrains Mono', 'Cascadia Code', monospace !important;
    font-size: 0.88em !important;
}

/* ── Sidebar container ── */
[data-testid="stSidebar"] {
    background: #0a0e14 !important;
    border-right: 1px solid #21262d !important;
}

/* ── Sidebar brand header (CSS-only) ── */
[data-testid="stSidebarNav"]::before {
    content: "StockBot";
    display: block;
    font-family: 'Space Grotesk', system-ui, sans-serif;
    font-size: 1.05rem;
    font-weight: 700;
    color: #e6edf3;
    letter-spacing: -0.03em;
    padding: 20px 12px 12px;
    border-bottom: 1px solid #21262d;
    margin-bottom: 4px;
}

/* ── Sidebar nav items ── */
[data-testid="stSidebarNavLink"] {
    border-radius: 6px !important;
    padding: 7px 10px !important;
    font-size: 0.875rem !important;
    font-weight: 500 !important;
    color: #8b949e !important;
    transition: color 140ms ease, background-color 140ms ease !important;
    text-decoration: none !important;
    margin: 1px 0 !important;
}

[data-testid="stSidebarNavLink"]:hover {
    background-color: #161b22 !important;
    color: #c9d1d9 !important;
}

[data-testid="stSidebarNavLink"][aria-current="page"] {
    background-color: rgba(0, 180, 216, 0.10) !important;
    color: #00b4d8 !important;
    font-weight: 600 !important;
}

/* ── Sidebar section (below auto-nav) ── */
[data-testid="stSidebarContent"] {
    padding-top: 0 !important;
}

/* ── Streamlit default caption improvements ── */
.stCaption, [data-testid="stCaptionContainer"] {
    font-size: 0.78rem !important;
    color: #6e7681 !important;
    letter-spacing: 0.005em !important;
}

/* ── Subheader size bump ── */
[data-testid="stAppViewContainer"] [data-testid="stHeadingWithActionElements"] h2 {
    font-size: 1.1rem !important;
}

@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
    }
    .sb-progress-bar { display: none !important; }
}
</style>
"""

# ── Keyframes + progress bar ─────────────────────────────────────────────────
_KEYFRAMES = """
<style>
@keyframes sb-fade-slide-up {
    from { opacity: 0; transform: translateY(20px); }
    to   { opacity: 1; transform: translateY(0); }
}
@keyframes sb-fade-in {
    from { opacity: 0; }
    to   { opacity: 1; }
}
@keyframes sb-earnings-glow {
    0%, 100% { box-shadow: 0 0 0 0 rgba(255, 187, 51, 0); }
    50%       { box-shadow: 0 0 12px 3px rgba(255, 187, 51, 0.30); }
}
@keyframes sb-progress-bar {
    0%   { transform: scaleX(0); }
    80%  { transform: scaleX(1); opacity: 1; }
    100% { transform: scaleX(1); opacity: 0; }
}
.sb-progress-bar {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 2px;
    background: #00b4d8;
    transform-origin: left center;
    animation: sb-progress-bar 420ms cubic-bezier(0.22, 1, 0.36, 1) both;
    z-index: 9999;
    pointer-events: none;
}
</style>
"""

EASING = "cubic-bezier(0.22, 1, 0.36, 1)"
PLOTLY_EASING = "cubic-out"

# Longer, more pronounced animation so it's visible even after API loading delay
SIGNAL_CARD_ANIM = f"sb-fade-slide-up 360ms 60ms {EASING} both"


def inject_animations() -> None:
    st.markdown(_KEYFRAMES, unsafe_allow_html=True)


def inject_page_transition() -> None:
    st.markdown(_GLOBAL_STYLES + _KEYFRAMES, unsafe_allow_html=True)
    st.markdown('<div class="sb-progress-bar"></div>', unsafe_allow_html=True)
    # Sidebar version/context footer
    st.sidebar.markdown(
        '<div style="position:absolute; bottom:16px; left:0; right:0; padding:0 12px;">'
        '<p style="font-size:0.72rem; color:#484f58; font-family:\'Space Grotesk\',sans-serif; margin:0;">'
        'v0.1 · Solo informativo</p></div>',
        unsafe_allow_html=True,
    )
