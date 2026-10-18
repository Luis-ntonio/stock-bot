import pandas as pd
from pydantic import BaseModel, Field
from app.llm.client import get_llm_client
from app.llm.prompts import TECHNICAL_ANALYST_SYSTEM
import structlog

logger = structlog.get_logger(__name__)


class TechnicalAnalysis(BaseModel):
    trend: str = Field(description="Tendencia primaria: alcista/bajista/lateral")
    momentum: str = Field(description="Estado del momentum (RSI, MACD)")
    support_resistance: str = Field(description="Niveles clave de soporte/resistencia")
    volume_assessment: str = Field(description="Análisis de volumen relativo")
    cross_signal: str = Field(description="Golden cross, death cross, o ninguno")
    technical_verdict: str = Field(description="Resumen técnico: positivo/negativo/neutro")
    chart_patterns: list[str] = Field(default_factory=list, description="Patrones detectados en los últimos 60 días OHLCV")
    score: float = Field(ge=0.0, le=1.0, description="Score técnico 0-1 (1=muy positivo)")


async def run_technical_agent(state: dict) -> dict:
    ticker = state["ticker"]
    price_data = state.get("price_data")

    client = get_llm_client()

    if price_data is None:
        logger.warning("No price data for technical analysis", ticker=ticker)
        return {"errors": ["technical_agent: no price data"]}

    # Obtener últimas métricas del DataFrame (o dict serializado)
    tech_summary = _extract_technical_summary(price_data, ticker)

    messages = [
        {"role": "system", "content": TECHNICAL_ANALYST_SYSTEM},
        {"role": "user", "content": f"Analiza los indicadores técnicos de {ticker}:\n\n{tech_summary}"},
    ]

    try:
        analysis = await client.complete(messages, TechnicalAnalysis)
        result = analysis.model_dump()
        # Los valores numéricos vienen de los datos ya calculados, no del LLM
        # — pedirle que transcriba un número exacto en prosa es una fuente
        # de error innecesaria cuando ya lo tenemos calculado en Python.
        # Esto queda disponible para usuarios avanzados vía sub_analyses.
        result["indicators"] = _extract_numeric_indicators(price_data)
        logger.info("Technical analysis complete", ticker=ticker, score=analysis.score)
        return {"technical_analysis": result}
    except Exception as e:
        logger.error("Technical agent failed", ticker=ticker, error=str(e))
        return {"errors": [f"technical_agent: {e}"]}


def _extract_numeric_indicators(price_data: list[dict]) -> dict:
    """Valores numéricos reales del último día disponible, para auditoría/
    usuarios avanzados — independientes de lo que el LLM haya escrito en
    los campos de texto (trend/momentum/etc)."""
    if not price_data:
        return {}
    last = price_data[-1]

    def _num(*keys) -> float | None:
        for k in keys:
            v = last.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
        return None

    return {
        "current_price": _num("close"),
        "sma_50": _num("SMA_50", "sma_50"),
        "sma_200": _num("SMA_200", "sma_200"),
        "rsi_14": _num("RSI_14", "rsi_14"),
        "macd": _num("MACD_12_26_9", "macd"),
        "volume": last.get("volume"),
    }


def _extract_technical_summary(price_data: dict | list, ticker: str) -> str:
    try:
        if not (isinstance(price_data, list) and price_data):
            return "No technical data available"

        last = price_data[-1]
        recent_60 = price_data[-60:]

        ohlcv_rows = []
        for row in recent_60:
            d = str(row.get("date", ""))[:10]
            ohlcv_rows.append(
                f"{d},{float(row.get('open') or 0):.2f},{float(row.get('high') or 0):.2f},"
                f"{float(row.get('low') or 0):.2f},{float(row.get('close') or 0):.2f},{int(row.get('volume') or 0)}"
            )
        ohlcv_csv = "date,open,high,low,close,volume\n" + "\n".join(ohlcv_rows)

        indicators = "\n".join([
            f"Ticker: {ticker}",
            f"Precio actual: {last.get('close', 'N/A')}",
            f"SMA50: {last.get('SMA_50', last.get('sma_50', 'N/A'))}",
            f"SMA200: {last.get('SMA_200', last.get('sma_200', 'N/A'))}",
            f"RSI(14): {last.get('RSI_14', last.get('rsi_14', 'N/A'))}",
            f"MACD: {last.get('MACD_12_26_9', last.get('macd', 'N/A'))}",
            f"Golden Cross: {last.get('golden_cross', 'N/A')}",
            f"Volumen: {last.get('volume', 'N/A')}",
        ])
        return f"{indicators}\n\nULTIMOS 60 DIAS OHLCV (para deteccion de patrones):\n{ohlcv_csv}"
    except Exception:
        return "Technical data parsing error"
