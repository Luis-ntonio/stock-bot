from pydantic import BaseModel, Field, field_validator
from pydantic import confloat
from enum import Enum
from datetime import datetime
from typing import Literal


class Signal(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"


class Timeframe(str, Enum):
    ONE_MONTH = "1M"
    THREE_MONTHS = "3M"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class FundamentalSnapshot(BaseModel):
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    revenue_growth_yoy: float | None = None
    earnings_growth_yoy: float | None = None
    debt_to_equity: float | None = None
    free_cash_flow_yield: float | None = None
    eps_surprise_last_q: float | None = None
    eps_surprise_avg_4q: float | None = None


class PeerComparison(BaseModel):
    ticker: str
    pe_ratio: float | None = None
    revenue_growth_yoy: float | None = None
    signal: Signal | None = None


class SentimentSummary(BaseModel):
    reddit_mentions_7d: int | None = None
    stocktwits_sentiment: Literal["bullish", "bearish", "neutral"] | None = None
    news_sentiment_score: float | None = None
    key_headlines: list[str] = Field(default_factory=list, max_length=3)


class StockSuggestion(BaseModel):
    # Identificación
    ticker: str
    company_name: str
    market: Literal["US", "CRYPTO", "LATAM"]
    analysis_date: datetime

    # Sugerencia central
    signal: Signal
    confidence: float = Field(ge=0.0, le=1.0)
    timeframe: Timeframe = Timeframe.ONE_MONTH
    risk_level: RiskLevel

    # Precios de referencia
    current_price: float
    target_price_low: float | None = None
    target_price_base: float | None = None
    target_price_high: float | None = None

    # Tesis explicada (texto generado por LLM)
    bull_case: str = Field(max_length=500)
    bear_case: str = Field(max_length=500)
    final_reasoning: str = Field(max_length=800)
    key_catalysts: list[str] = Field(default_factory=list, max_length=5)
    key_risks: list[str] = Field(default_factory=list, max_length=5)

    # Datos de soporte
    fundamentals: FundamentalSnapshot
    peers: list[PeerComparison] = Field(default_factory=list, max_length=5)
    sentiment: SentimentSummary

    # Features extra
    chart_patterns: list[str] = Field(default_factory=list)
    upcoming_earnings: dict | None = None
    earnings_history: list[dict] = Field(default_factory=list)

    # Metadatos
    llm_model_used: str
    data_sources: list[str]
    disclaimer: str = "Not financial advice. For informational purposes only."

    @field_validator("bull_case", "bear_case", mode="before")
    @classmethod
    def truncate_text(cls, v: str) -> str:
        return v[:500] if isinstance(v, str) else v

    @field_validator("final_reasoning", mode="before")
    @classmethod
    def truncate_reasoning(cls, v: str) -> str:
        return v[:800] if isinstance(v, str) else v
