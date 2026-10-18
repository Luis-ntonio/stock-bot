from datetime import date, datetime
from pydantic import BaseModel, Field
from typing import Literal
from app.llm.client import get_llm_client
from app.llm.prompts import POSITION_REVIEW_SYSTEM
from app.llm.schemas import StockSuggestion
import structlog

logger = structlog.get_logger(__name__)


class PositionReview(BaseModel):
    recommendation: Literal["HOLD", "SELL"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(max_length=600)
    key_factors: list[str] = Field(default_factory=list, max_length=5)


async def review_position(
    ticker: str,
    purchase_date: date,
    purchase_price: float,
    quantity: float = 1.0,
    market: str = "US",
    fresh_suggestion: StockSuggestion | None = None,
) -> dict:
    """Decide si conviene mantener o vender una posición ya comprada,
    combinando un análisis fresco del ticker (reutilizando el pipeline
    normal de agentes) con los datos propios de la posición: hace cuánto
    se compró y cuánto ganó/perdió desde entonces.

    Si no se pasa `fresh_suggestion`, corre `analyze_ticker()` para conseguir
    uno (esto también persiste esa Suggestion en la tabla `suggestions`,
    como cualquier análisis normal).
    """
    if fresh_suggestion is None:
        from app.agents.workflow import analyze_ticker
        fresh_suggestion = await analyze_ticker(ticker, market=market)

    current_price = fresh_suggestion.current_price
    holding_period_days = (date.today() - purchase_date).days
    unrealized_pnl_pct = (
        (current_price - purchase_price) / purchase_price * 100
        if purchase_price else 0.0
    )

    user_content = f"""
POSICIÓN:
- Ticker: {ticker} ({fresh_suggestion.company_name})
- Precio de compra: ${purchase_price:.2f}
- Fecha de compra: {purchase_date.isoformat()} ({holding_period_days} días en cartera)
- Cantidad: {quantity}
- Precio actual: ${current_price:.2f}
- Ganancia/pérdida no realizada: {unrealized_pnl_pct:+.2f}%

ANÁLISIS FRESCO DEL TICKER (hoy):
- Señal: {fresh_suggestion.signal.value} (confianza {fresh_suggestion.confidence:.2f})
- Nivel de riesgo: {fresh_suggestion.risk_level.value}
- Precio objetivo base: {fresh_suggestion.target_price_base}
- Bull case: {fresh_suggestion.bull_case}
- Bear case: {fresh_suggestion.bear_case}
- Razonamiento: {fresh_suggestion.final_reasoning}

Decide: ¿conviene MANTENER o VENDER esta posición?
"""

    messages = [
        {"role": "system", "content": POSITION_REVIEW_SYSTEM},
        {"role": "user", "content": user_content},
    ]

    client = get_llm_client()
    try:
        review = await client.complete(messages, PositionReview)
    except Exception as e:
        logger.error("Position review failed", ticker=ticker, error=str(e))
        raise

    logger.info(
        "Position review complete",
        ticker=ticker,
        recommendation=review.recommendation,
        pnl_pct=round(unrealized_pnl_pct, 2),
        holding_days=holding_period_days,
    )

    return {
        "ticker": ticker,
        "purchase_date": purchase_date.isoformat(),
        "purchase_price": purchase_price,
        "quantity": quantity,
        "current_price": current_price,
        "holding_period_days": holding_period_days,
        "unrealized_pnl_pct": round(unrealized_pnl_pct, 2),
        "recommendation": review.recommendation,
        "confidence": review.confidence,
        "reasoning": review.reasoning,
        "key_factors": review.key_factors,
        "fresh_signal": fresh_suggestion.signal.value,
        "fresh_confidence": fresh_suggestion.confidence,
        "reviewed_at": datetime.utcnow().isoformat(),
    }
