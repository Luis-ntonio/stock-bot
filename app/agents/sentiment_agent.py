from pydantic import BaseModel, Field
from typing import Literal
from app.llm.client import get_llm_client
from app.llm.prompts import SENTIMENT_ANALYST_SYSTEM
import structlog

logger = structlog.get_logger(__name__)


class SentimentAnalysis(BaseModel):
    overall_sentiment: Literal["very_bullish", "bullish", "neutral", "bearish", "very_bearish"]
    key_themes: list[str] = Field(default_factory=list, max_length=3)
    contrarian_signal: str = Field(description="¿Hay señal contraria? (euforia/pánico extremo)")
    news_impact: str = Field(description="Impacto de noticias recientes")
    score: float = Field(ge=0.0, le=1.0, description="Score sentimiento 0-1 (1=muy positivo)")


async def run_sentiment_agent(state: dict) -> dict:
    ticker = state["ticker"]
    news = state.get("news") or []
    sentiment_data = state.get("sentiment") or {}

    client = get_llm_client()

    news_summary = _summarize_news(news)

    user_content = f"""
Analiza el sentimiento de mercado para {ticker}:

DATOS DE REDES SOCIALES:
- Reddit menciones (7d): {sentiment_data.get('reddit_mentions_7d', 'N/A')}
- StockTwits sentimiento: {sentiment_data.get('stocktwits_sentiment', 'N/A')}
- News sentiment score: {sentiment_data.get('news_sentiment_score', 'N/A')}

MENSAJES DESTACADOS:
{chr(10).join(f"  - {m}" for m in sentiment_data.get('key_headlines', [])[:3])}

NOTICIAS RECIENTES:
{news_summary}
"""

    messages = [
        {"role": "system", "content": SENTIMENT_ANALYST_SYSTEM},
        {"role": "user", "content": user_content},
    ]

    try:
        analysis = await client.complete(messages, SentimentAnalysis)
        logger.info("Sentiment analysis complete", ticker=ticker, sentiment=analysis.overall_sentiment)
        return {"sentiment_analysis": analysis.model_dump()}
    except Exception as e:
        logger.error("Sentiment agent failed", ticker=ticker, error=str(e))
        return {"errors": [f"sentiment_agent: {e}"]}


def _summarize_news(news: list[dict]) -> str:
    if not news:
        return "No recent news available"
    return "\n".join(f"  - {n.get('headline', '')}" for n in news[:10])
