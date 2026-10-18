from datetime import datetime
from pydantic import BaseModel, Field
from app.llm.client import get_llm_client
from app.llm.prompts import BULL_RESEARCHER_SYSTEM, BEAR_RESEARCHER_SYSTEM, AGGREGATOR_SYSTEM
from app.llm.schemas import (
    StockSuggestion, Signal, RiskLevel, Timeframe,
    FundamentalSnapshot, SentimentSummary, PeerComparison,
)
import structlog

logger = structlog.get_logger(__name__)


class BullCase(BaseModel):
    arguments: list[str] = Field(max_length=3)
    bull_summary: str = Field(max_length=500)
    confidence_boost: float = Field(ge=0.0, le=0.5)


class BearCase(BaseModel):
    risks: list[str] = Field(max_length=3)
    bear_summary: str = Field(max_length=500)
    confidence_penalty: float = Field(ge=0.0, le=0.5)


class FinalDecision(BaseModel):
    signal: Signal
    confidence: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel
    target_price_low: float | None = None
    target_price_base: float | None = None
    target_price_high: float | None = None
    final_reasoning: str = Field(max_length=800)
    key_catalysts: list[str] = Field(default_factory=list, max_length=5)
    key_risks: list[str] = Field(default_factory=list, max_length=5)


async def run_aggregator_agent(state: dict) -> dict:
    ticker = state["ticker"]
    client = get_llm_client()

    analysis_summary = _build_analysis_summary(state)
    current_price = _extract_current_price(state)

    # Paso 1: Bull researcher
    bull_messages = [
        {"role": "system", "content": BULL_RESEARCHER_SYSTEM},
        {"role": "user", "content": f"Construye el caso bull para {ticker}:\n\n{analysis_summary}"},
    ]
    try:
        bull = await client.complete(bull_messages, BullCase)
        state = {**state, "bull_case": bull.bull_summary}
    except Exception as e:
        logger.error("Bull researcher failed", ticker=ticker, error=str(e))
        bull = BullCase(arguments=[], bull_summary="Análisis bull no disponible", confidence_boost=0.0)
        state = {**state, "bull_case": bull.bull_summary}

    # Paso 2: Bear researcher
    bear_messages = [
        {"role": "system", "content": BEAR_RESEARCHER_SYSTEM},
        {"role": "user", "content": f"Construye el caso bear para {ticker}:\n\n{analysis_summary}"},
    ]
    try:
        bear = await client.complete(bear_messages, BearCase)
        state = {**state, "bear_case": bear.bear_summary}
    except Exception as e:
        logger.error("Bear researcher failed", ticker=ticker, error=str(e))
        bear = BearCase(risks=[], bear_summary="Análisis bear no disponible", confidence_penalty=0.0)
        state = {**state, "bear_case": bear.bear_summary}

    # Paso 3: Aggregator — decisión final
    agg_content = f"""
TICKER: {ticker} | Precio actual: {current_price}
MERCADO: {state.get('market', 'US')}

CASO BULL:
{bull.bull_summary}

CASO BEAR:
{bear.bear_summary}

RESUMEN DE ANÁLISIS:
{analysis_summary}

Toma la decisión final de inversión para el próximo mes.
"""
    agg_messages = [
        {"role": "system", "content": AGGREGATOR_SYSTEM},
        {"role": "user", "content": agg_content},
    ]

    try:
        decision = await client.complete(agg_messages, FinalDecision)
    except Exception as e:
        logger.error("Aggregator failed", ticker=ticker, error=str(e))
        return {**state, "errors": state.get("errors", []) + [f"aggregator: {e}"]}

    _warn_if_confidence_diverges_from_scores(ticker, decision.confidence, state)

    # Construir StockSuggestion final
    fund_data = state.get("fundamentals") or {}
    sent_data = state.get("sentiment") or {}
    peers_raw = (state.get("peer_analysis") or {}).get("peers_assessed", [])

    # El cliente ya trackea el último proveedor/modelo usado en last_provider/last_model
    model_used = f"{client.last_provider}/{client.last_model}"

    suggestion = StockSuggestion(
        ticker=ticker,
        company_name=state.get("company_name", ticker),
        market=state.get("market", "US"),
        analysis_date=datetime.utcnow(),
        signal=decision.signal,
        confidence=decision.confidence,
        timeframe=Timeframe.ONE_MONTH,
        risk_level=decision.risk_level,
        current_price=current_price or 0.0,
        target_price_low=decision.target_price_low,
        target_price_base=decision.target_price_base,
        target_price_high=decision.target_price_high,
        bull_case=bull.bull_summary,
        bear_case=bear.bear_summary,
        final_reasoning=decision.final_reasoning,
        key_catalysts=decision.key_catalysts,
        key_risks=decision.key_risks,
        fundamentals=FundamentalSnapshot(**fund_data) if fund_data else FundamentalSnapshot(),
        peers=[PeerComparison(**p) for p in peers_raw[:5]] if peers_raw else [],
        sentiment=SentimentSummary(
            reddit_mentions_7d=sent_data.get("reddit_mentions_7d"),
            stocktwits_sentiment=sent_data.get("stocktwits_sentiment"),
            news_sentiment_score=sent_data.get("news_sentiment_score"),
            key_headlines=sent_data.get("key_headlines", [])[:3],
        ),
        chart_patterns=(state.get("technical_analysis") or {}).get("chart_patterns", []),
        upcoming_earnings=state.get("upcoming_earnings"),
        earnings_history=state.get("earnings") or [],
        sub_analyses={
            "fundamental": state.get("fundamental_analysis"),
            "technical": state.get("technical_analysis"),
            "sentiment": state.get("sentiment_analysis"),
            "macro": state.get("macro_analysis"),
            "peer": state.get("peer_analysis"),
            "bull_full": bull.model_dump(),
            "bear_full": bear.model_dump(),
        },
        llm_model_used=model_used,
        data_sources=state.get("data_sources", ["yfinance", "finnhub", "fmp"]),
    )

    logger.info("Aggregator complete", ticker=ticker, signal=decision.signal, confidence=decision.confidence)
    return {**state, "suggestion": suggestion}


def _build_analysis_summary(state: dict) -> str:
    from datetime import date as _date
    parts = []
    if fa := state.get("fundamental_analysis"):
        fund_raw = state.get("fundamentals") or {}
        rev_g = fund_raw.get("revenue_growth_yoy")
        eps_g = fund_raw.get("earnings_growth_yoy")
        growth_str = ""
        if rev_g is not None or eps_g is not None:
            growth_str = (
                f" | Revenue YoY={rev_g*100:+.1f}%" if rev_g is not None else ""
            ) + (
                f" | Earnings YoY={eps_g*100:+.1f}%" if eps_g is not None else ""
            )
        parts.append(f"FUNDAMENTAL: Score={fa.get('score', 'N/A')} | {fa.get('valuation_verdict', '')}{growth_str}")
    if ta := state.get("technical_analysis"):
        patterns = ta.get("chart_patterns", [])
        pattern_str = f" | Patrones: {', '.join(patterns)}" if patterns else ""
        ind = ta.get("indicators") or {}
        rsi, macd = ind.get("rsi_14"), ind.get("macd")
        # Números reales calculados en Python, no lo que el LLM haya
        # transcripto en `momentum` — ancla el debate a los valores exactos.
        exact_str = ""
        if rsi is not None or macd is not None:
            exact_str = " | Exacto:" + (f" RSI={rsi:.1f}" if rsi is not None else "") + (f" MACD={macd:.2f}" if macd is not None else "")
        parts.append(
            f"TÉCNICO: Score={ta.get('score', 'N/A')} | Trend={ta.get('trend', '')} | "
            f"RSI/MACD={ta.get('momentum', '')}{exact_str}{pattern_str}"
        )
    if sa := state.get("sentiment_analysis"):
        sent_raw = state.get("sentiment") or {}
        missing = [
            k for k in ("reddit_mentions_7d", "stocktwits_sentiment", "news_sentiment_score")
            if sent_raw.get(k) is None
        ]
        gap_str = f" | DATOS FALTANTES: {', '.join(missing)}" if missing else ""
        contrarian = (sa.get("contrarian_signal") or "")[:200]
        contrarian_str = f" | Señal contraria: {contrarian}" if contrarian else ""
        parts.append(
            f"SENTIMIENTO: Score={sa.get('score', 'N/A')} | {sa.get('overall_sentiment', '')}"
            f"{gap_str}{contrarian_str}"
        )
    if ma := state.get("macro_analysis"):
        parts.append(f"MACRO: Score={ma.get('score', 'N/A')} | {ma.get('macro_verdict', '')}")
    if pa := state.get("peer_analysis"):
        parts.append(f"PEERS: {pa.get('peer_verdict', '')}")
    ue = state.get("upcoming_earnings") or {}
    earnings_alerted = False
    if ue.get("date"):
        try:
            days_away = (_date.fromisoformat(ue["date"]) - _date.today()).days
            if days_away <= 30:
                parts.append(f"EARNINGS ALERT: earnings en {days_away} días ({ue['date']}) — ELEVA INCERTIDUMBRE A CORTO PLAZO")
                earnings_alerted = True
        except Exception:
            pass

    # El calendario de earnings a veces no trae fecha (API vacía) aunque las
    # noticias del mismo ciclo ya estén hablando del reporte — sin esto, la
    # señal final se calcula ciega a un catalizador de volatilidad real que
    # el propio pipeline ya tenía en sus manos (visto con META: earnings "el
    # miércoles" mencionado en un titular, upcoming_earnings vacío, y el
    # resultado final sin ningún caveat de timing).
    if not earnings_alerted and _headlines_mention_earnings(state.get("ticker", ""), state.get("sentiment") or {}):
        parts.append(
            "EARNINGS ALERT (fecha no confirmada por el calendario): una noticia reciente "
            "menciona earnings próximos para este ticker — tratá esto como un catalizador de "
            "volatilidad real pese a no tener la fecha exacta. ELEVA INCERTIDUMBRE A CORTO PLAZO."
        )

    return "\n".join(parts) if parts else "No analysis data available"


def _headlines_mention_earnings(ticker: str, sentiment_data: dict) -> bool:
    """Heurística barata: ¿algún titular menciona a la vez el ticker y la
    palabra 'earnings'/'reports'? No intenta extraer la fecha — solo decidir
    si hay que prender la alerta aunque el calendario oficial esté vacío."""
    if not ticker:
        return False
    markers = (f"${ticker.upper()}", ticker.upper())
    for headline in sentiment_data.get("key_headlines", []):
        h = headline.upper()
        if any(m in h for m in markers) and ("EARNINGS" in h or "REPORTS" in h):
            return True
    return False


def _extract_current_price(state: dict) -> float | None:
    price_data = state.get("price_data")
    if isinstance(price_data, list) and price_data:
        return price_data[-1].get("close")
    if isinstance(price_data, dict) and "close" in price_data:
        return price_data.get("close")
    return None


def _warn_if_confidence_diverges_from_scores(ticker: str, confidence: float, state: dict) -> None:
    """Log-only sanity check: flag when the LLM's self-reported confidence is
    far from what the sub-agent scores would suggest. Does not clamp or
    override the LLM's decision — purely for visibility into calibration drift."""
    scores = [
        v.get("score")
        for key in ("fundamental_analysis", "technical_analysis", "sentiment_analysis", "macro_analysis")
        if (v := state.get(key)) and isinstance(v.get("score"), (int, float))
    ]
    if not scores:
        return

    avg_score = sum(scores) / len(scores)
    divergence = abs(avg_score - confidence)
    if divergence > 0.35:
        logger.warning(
            "Aggregator confidence diverges from sub-agent scores",
            ticker=ticker,
            confidence=confidence,
            avg_sub_score=round(avg_score, 3),
            divergence=round(divergence, 3),
        )
