from pydantic import BaseModel, Field
from app.llm.client import get_llm_client
from app.llm.prompts import FUNDAMENTAL_ANALYST_SYSTEM
import structlog

logger = structlog.get_logger(__name__)


class FundamentalAnalysis(BaseModel):
    pe_assessment: str = Field(description="Evaluación del P/E vs sector")
    revenue_trend: str = Field(description="Tendencia de revenue últimos 4Q")
    earnings_quality: str = Field(description="Calidad de earnings, EPS surprises")
    balance_strength: str = Field(description="Fortaleza del balance, deuda/equity, FCF")
    valuation_verdict: str = Field(description="Caro, justo o barato vs peers")
    catalysts: list[str] = Field(default_factory=list, max_length=3)
    risks: list[str] = Field(default_factory=list, max_length=3)
    score: float = Field(ge=0.0, le=1.0, description="Score fundamental 0-1 (1=muy positivo)")


async def run_fundamental_agent(state: dict) -> dict:
    ticker = state["ticker"]
    fundamentals = state.get("fundamentals") or {}
    earnings = state.get("earnings") or []
    upcoming_earnings = state.get("upcoming_earnings")

    client = get_llm_client()

    market = state.get('market', 'US')
    user_content = f"""
Analiza los fundamentales de {ticker}:
{_market_data_note(market)}
MÉTRICAS ACTUALES:
- P/E Ratio: {fundamentals.get('pe_ratio', 'N/A')}
- P/B Ratio: {fundamentals.get('pb_ratio', 'N/A')}
- Revenue Growth YoY: {fundamentals.get('revenue_growth_yoy', 'N/A')}
- Earnings Growth YoY: {fundamentals.get('earnings_growth_yoy', 'N/A')}
- Debt/Equity: {fundamentals.get('debt_to_equity', 'N/A')}
- FCF Yield: {fundamentals.get('free_cash_flow_yield', 'N/A')}
- EPS Surprise último Q: {fundamentals.get('eps_surprise_last_q', 'N/A')}%
- EPS Surprise avg 4Q: {fundamentals.get('eps_surprise_avg_4q', 'N/A')}%

HISTORIAL EARNINGS (últimos quarters):
{_format_earnings(earnings)}

PRÓXIMO EARNINGS:
{_format_upcoming_earnings(upcoming_earnings)}

Mercado: {market}
"""

    messages = [
        {"role": "system", "content": FUNDAMENTAL_ANALYST_SYSTEM},
        {"role": "user", "content": user_content},
    ]

    try:
        analysis = await client.complete(messages, FundamentalAnalysis)
        logger.info("Fundamental analysis complete", ticker=ticker, score=analysis.score)
        return {"fundamental_analysis": analysis.model_dump()}
    except Exception as e:
        logger.error("Fundamental agent failed", ticker=ticker, error=str(e))
        return {"errors": [f"fundamental_agent: {e}"]}


def _market_data_note(market: str) -> str:
    if market in ("EU", "LATAM"):
        return (
            "NOTA: Para mercados EU/LATAM es normal que Debt/Equity, FCF Yield o "
            "EPS Surprise histórico aparezcan como N/A por limitaciones de cobertura "
            "de datos (no de la compañía) — NO lo interpretes como señal negativa, "
            "evalúa solo con los campos disponibles.\n"
        )
    if market == "CRYPTO":
        return (
            "NOTA: P/E, P/B, Debt/Equity y EPS Surprise NO APLICAN a criptoactivos "
            "por diseño — ignóralos, no son 'datos faltantes'.\n"
        )
    return ""


def _format_earnings(earnings: list[dict]) -> str:
    if not earnings:
        return "No earnings data available"
    lines = []
    for e in earnings[:4]:
        surprise = e.get("surprise_pct")
        s = f"{surprise:+.1f}%" if surprise is not None else "N/A"
        lines.append(f"  Q{e.get('quarter_end', '?')}: EPS est={e.get('eps_estimate', '?')} actual={e.get('eps_actual', '?')} surprise={s}")
    return "\n".join(lines)


def _format_upcoming_earnings(ue: dict | None) -> str:
    if not ue or not ue.get("date"):
        return "Sin earnings próximos en los siguientes 60 días"
    from datetime import date
    days_away = (date.fromisoformat(ue["date"]) - date.today()).days
    hour_map = {"BMO": "antes de apertura", "AMC": "después de cierre", "DMH": "durante mercado"}
    hour = hour_map.get(ue.get("hour", ""), "")
    return (
        f"Fecha: {ue['date']} ({days_away} días) {hour} | "
        f"EPS est: {ue.get('eps_estimate', 'N/A')} | Revenue est: {ue.get('revenue_estimate', 'N/A')}"
    )
