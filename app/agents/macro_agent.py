import httpx
import asyncio
import io
import pandas as pd
from pydantic import BaseModel, Field
from typing import Literal
from app.llm.client import get_llm_client
from app.llm.prompts import MACRO_ANALYST_SYSTEM
import structlog

logger = structlog.get_logger(__name__)

FRED_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="

MACRO_SERIES = {
    "DFF":      "Federal Funds Rate",
    "T10Y2Y":   "10Y-2Y Yield Spread",
    "UNRATE":   "Unemployment Rate",
    "CPIAUCSL": "CPI (inflation)",
    "VIXCLS":   "VIX (volatility index)",
}


class MacroAnalysis(BaseModel):
    rate_environment: Literal["easing", "neutral", "tightening"]
    recession_risk: Literal["low", "moderate", "high"]
    inflation_trend: Literal["falling", "stable", "rising"]
    market_stress: Literal["low", "moderate", "high"]
    sector_rotation_signal: str = Field(description="Qué sectores favorece el entorno macro actual")
    macro_verdict: str = Field(description="Impacto macro en renta variable próximos 1-3 meses")
    score: float = Field(ge=0.0, le=1.0, description="Score macro 0-1 (1=entorno muy favorable para RV)")


async def run_macro_agent(state: dict) -> dict:
    macro_data = await _fetch_macro_data()
    client = get_llm_client()

    user_content = f"""
Analiza el entorno macroeconómico actual para invertir en renta variable:

{_format_macro_data(macro_data)}

Considera el impacto sobre {state.get('market', 'US')} específicamente.
"""

    messages = [
        {"role": "system", "content": MACRO_ANALYST_SYSTEM},
        {"role": "user", "content": user_content},
    ]

    try:
        analysis = await client.complete(messages, MacroAnalysis)
        logger.info("Macro analysis complete", score=analysis.score, risk=analysis.recession_risk)
        return {"macro_analysis": analysis.model_dump(), "macro_context": macro_data}
    except Exception as e:
        logger.error("Macro agent failed", error=str(e))
        return {"errors": [f"macro_agent: {e}"]}


async def _fetch_macro_data() -> dict[str, list[dict]]:
    results = {}

    async def fetch_series(series_id: str) -> tuple[str, list[dict]]:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{FRED_BASE}{series_id}", timeout=15)
                r.raise_for_status()
                df = pd.read_csv(io.StringIO(r.text))
                df = df.dropna()
                last_6 = df.tail(6).to_dict("records")
                return series_id, last_6
        except Exception as e:
            logger.warning("FRED fetch failed", series=series_id, error=str(e))
            return series_id, []

    tasks = [fetch_series(sid) for sid in MACRO_SERIES]
    fetched = await asyncio.gather(*tasks, return_exceptions=True)

    for item in fetched:
        if isinstance(item, tuple):
            sid, data = item
            results[sid] = data

    return results


def _format_macro_data(data: dict[str, list]) -> str:
    lines = []
    for series_id, name in MACRO_SERIES.items():
        records = data.get(series_id, [])
        if records:
            latest = records[-1]
            prev = records[-2] if len(records) > 1 else latest
            cols = [c for c in latest if c != "DATE"]
            if cols:
                col = cols[0]
                current_val = latest.get(col, "N/A")
                prev_val = prev.get(col, "N/A")
                lines.append(f"  {name} ({series_id}): {current_val} (anterior: {prev_val})")
        else:
            lines.append(f"  {name} ({series_id}): datos no disponibles")
    return "\n".join(lines)
