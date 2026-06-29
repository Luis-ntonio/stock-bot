import asyncio
import operator
from typing import TypedDict, Any, Annotated
from langgraph.graph import StateGraph, END
from app.llm.schemas import StockSuggestion
import structlog

logger = structlog.get_logger(__name__)


class AnalysisState(TypedDict, total=False):
    ticker: str
    market: str
    company_name: str
    # Raw data
    price_data: list[dict] | None
    fundamentals: dict | None
    earnings: list[dict] | None
    upcoming_earnings: dict | None
    news: list[dict] | None
    sentiment: dict | None
    peers_data: dict | None
    macro_context: dict | None
    # Agent analyses
    fundamental_analysis: dict | None
    technical_analysis: dict | None
    sentiment_analysis: dict | None
    macro_analysis: dict | None
    peer_analysis: dict | None
    # Debate
    bull_case: str | None
    bear_case: str | None
    # Final output
    suggestion: StockSuggestion | None
    llm_model_used: str
    data_sources: list[str]
    errors: Annotated[list[str], operator.add]


# ── Nodo de datos ─────────────────────────────────────────────────────────────

async def fetch_data_node(state: AnalysisState) -> AnalysisState:
    ticker = state["ticker"]
    market = state.get("market", "US")

    from app.data.provider import get_data_provider
    provider = get_data_provider()
    errors = list(state.get("errors", []))
    data_sources = []

    # Company name resolution (when caller passes empty string or just the ticker)
    company_name = state.get("company_name", "") or ""
    if not company_name or company_name == ticker:
        try:
            name = await provider.get_company_name(ticker, market=market)
            if name:
                company_name = name
                logger.info("Company name resolved", ticker=ticker, name=name)
        except Exception as e:
            errors.append(f"company_name: {e}")

    # Precio + indicadores técnicos
    price_data = None
    try:
        df = await provider.get_price_history(ticker, period="1y", market=market)
        if df is not None and not df.empty:
            price_data = df.reset_index().to_dict("records")
            data_sources.append("price_history")
    except Exception as e:
        errors.append(f"price_data: {e}")

    # Fundamentales
    fundamentals = None
    try:
        f = await provider.get_fundamentals(ticker, market=market)
        fundamentals = f.model_dump()
        data_sources.append("fundamentals")
    except Exception as e:
        errors.append(f"fundamentals: {e}")

    # Earnings (solo US)
    earnings = []
    upcoming_earnings = None
    if market == "US":
        try:
            earnings = await provider.get_earnings_history(ticker)
            if earnings:
                data_sources.append("earnings")
        except Exception as e:
            errors.append(f"earnings: {e}")

        try:
            upcoming_earnings = await provider.get_upcoming_earnings(ticker)
            if upcoming_earnings:
                data_sources.append("upcoming_earnings")
        except Exception as e:
            errors.append(f"upcoming_earnings: {e}")

    # News
    news = []
    try:
        news = await provider.get_news(ticker, days=30)
        if news:
            data_sources.append("news")
    except Exception as e:
        errors.append(f"news: {e}")

    # Sentimiento
    sentiment = {}
    try:
        sentiment = await provider.get_sentiment(ticker)
        data_sources.append("sentiment")
    except Exception as e:
        errors.append(f"sentiment: {e}")

    # Peers + sus fundamentales (solo US)
    peers_data = {}
    if market == "US":
        try:
            peers = await provider.get_peers(ticker)
            peer_fundamentals = []
            for p_ticker in peers[:5]:
                try:
                    pf = await provider.get_fundamentals(p_ticker, market="US")
                    peer_fundamentals.append({"ticker": p_ticker, "fundamentals": pf.model_dump()})
                except Exception:
                    peer_fundamentals.append({"ticker": p_ticker, "fundamentals": {}})

            peers_data = {
                "ticker": ticker,
                "peers": peer_fundamentals,
                "main_fundamentals": fundamentals or {},
            }
            data_sources.append("peers")
        except Exception as e:
            errors.append(f"peers: {e}")

    logger.info("Data fetch complete", ticker=ticker, sources=data_sources, errors=len(errors))

    return {
        **state,
        "company_name": company_name,
        "price_data": price_data,
        "fundamentals": fundamentals,
        "earnings": earnings,
        "upcoming_earnings": upcoming_earnings,
        "news": news,
        "sentiment": sentiment,
        "peers_data": peers_data,
        "data_sources": data_sources,
        "errors": errors,
    }


# ── Nodos de análisis (envuelven los agentes) ────────────────────────────────

async def fundamental_node(state: AnalysisState) -> AnalysisState:
    from app.agents.fundamental_agent import run_fundamental_agent
    return await run_fundamental_agent(state)


async def technical_node(state: AnalysisState) -> AnalysisState:
    from app.agents.technical_agent import run_technical_agent
    return await run_technical_agent(state)


async def sentiment_node(state: AnalysisState) -> AnalysisState:
    from app.agents.sentiment_agent import run_sentiment_agent
    return await run_sentiment_agent(state)


async def macro_node(state: AnalysisState) -> AnalysisState:
    from app.agents.macro_agent import run_macro_agent
    return await run_macro_agent(state)


async def validate_analyses_node(state: AnalysisState) -> AnalysisState:
    """
    Checks that at least one of the 4 parallel analysis agents produced output.
    Aborts early if none succeeded — there is nothing to aggregate.
    Logs a warning when only a subset succeeded so the aggregator knows the context is partial.
    """
    analyses = {
        "fundamental": state.get("fundamental_analysis"),
        "technical": state.get("technical_analysis"),
        "sentiment": state.get("sentiment_analysis"),
        "macro": state.get("macro_analysis"),
    }
    succeeded = [k for k, v in analyses.items() if v is not None]
    ticker = state.get("ticker", "?")

    if not succeeded:
        raise RuntimeError(
            f"All 4 analysis agents failed for {ticker}. "
            f"Errors: {state.get('errors', [])}"
        )

    if len(succeeded) < 4:
        failed = [k for k in analyses if k not in succeeded]
        logger.warning(
            "Partial analysis — some agents failed",
            ticker=ticker,
            succeeded=succeeded,
            failed=failed,
        )

    return state


async def peer_node(state: AnalysisState) -> AnalysisState:
    from app.agents.peer_agent import run_peer_agent
    return await run_peer_agent(state)


async def aggregator_node(state: AnalysisState) -> AnalysisState:
    from app.agents.aggregator_agent import run_aggregator_agent
    return await run_aggregator_agent(state)


async def save_suggestion_node(state: AnalysisState) -> AnalysisState:
    suggestion = state.get("suggestion")
    if suggestion is None:
        logger.warning("No suggestion to save", ticker=state.get("ticker"))
        return state

    try:
        from app.db.session import get_sync_db_session
        from app.db.crud import save_suggestion
        with get_sync_db_session() as db:
            save_suggestion(db, suggestion)
        logger.info("Suggestion saved to DB", ticker=state["ticker"])
    except Exception as e:
        logger.error("Failed to save suggestion", ticker=state.get("ticker"), error=str(e))

    return state


# ── Construcción del grafo ────────────────────────────────────────────────────

def build_workflow() -> StateGraph:
    workflow = StateGraph(AnalysisState)

    workflow.add_node("fetch_data", fetch_data_node)
    workflow.add_node("fundamental_agent", fundamental_node)
    workflow.add_node("technical_agent", technical_node)
    workflow.add_node("sentiment_agent", sentiment_node)
    workflow.add_node("macro_agent", macro_node)
    workflow.add_node("validate_analyses", validate_analyses_node)
    workflow.add_node("peer_agent", peer_node)
    workflow.add_node("aggregator_agent", aggregator_node)
    workflow.add_node("save_suggestion", save_suggestion_node)

    workflow.set_entry_point("fetch_data")

    # Paralelos post-fetch
    for agent in ["fundamental_agent", "technical_agent", "sentiment_agent", "macro_agent"]:
        workflow.add_edge("fetch_data", agent)

    # Merge con validación antes de peer_agent
    for agent in ["fundamental_agent", "technical_agent", "sentiment_agent", "macro_agent"]:
        workflow.add_edge(agent, "validate_analyses")
    workflow.add_edge("validate_analyses", "peer_agent")

    # Debate + decisión
    workflow.add_edge("peer_agent", "aggregator_agent")
    workflow.add_edge("aggregator_agent", "save_suggestion")
    workflow.add_edge("save_suggestion", END)

    return workflow


_app_graph = None


def get_workflow():
    global _app_graph
    if _app_graph is None:
        _app_graph = build_workflow().compile()
    return _app_graph


async def analyze_ticker(ticker: str, market: str = "US", company_name: str = "") -> StockSuggestion:
    graph = get_workflow()

    initial_state: AnalysisState = {
        "ticker": ticker,
        "market": market,
        "company_name": company_name or ticker,
        "price_data": None,
        "fundamentals": None,
        "earnings": None,
        "upcoming_earnings": None,
        "news": None,
        "sentiment": None,
        "peers_data": None,
        "macro_context": None,
        "fundamental_analysis": None,
        "technical_analysis": None,
        "sentiment_analysis": None,
        "macro_analysis": None,
        "peer_analysis": None,
        "bull_case": None,
        "bear_case": None,
        "suggestion": None,
        "llm_model_used": "pending",
        "data_sources": [],
        "errors": [],
    }

    result = await graph.ainvoke(initial_state)

    if result.get("suggestion") is None:
        raise RuntimeError(
            f"Analysis failed for {ticker}. Errors: {result.get('errors', [])}"
        )

    return result["suggestion"]
