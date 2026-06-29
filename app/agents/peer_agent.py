from pydantic import BaseModel, Field
from app.llm.client import get_llm_client
from app.llm.prompts import PEER_COMPARISON_PROMPT
from app.llm.schemas import PeerComparison, Signal
import structlog

logger = structlog.get_logger(__name__)


class PeerAnalysis(BaseModel):
    relative_valuation: str = Field(description="¿Caro o barato vs peers en P/E?")
    growth_ranking: str = Field(description="Ranking de crecimiento vs peers")
    momentum_comparison: str = Field(description="¿Mejor o peor momentum técnico vs peers?")
    peer_verdict: str = Field(description="¿Es {ticker} relativamente atractivo vs peers?")
    peers_assessed: list[PeerComparison] = Field(default_factory=list)


async def run_peer_agent(state: dict) -> dict:
    ticker = state["ticker"]
    peers_data = state.get("peers_data") or {}

    client = get_llm_client()

    peers_list = peers_data.get("peers", [])
    if not peers_list:
        logger.warning("No peers data", ticker=ticker)
        return {**state, "peer_analysis": None}

    peers_formatted = _format_peers(peers_data)

    prompt = PEER_COMPARISON_PROMPT.format(
        ticker=ticker,
        n=len(peers_list),
        peers_data=peers_formatted,
    )

    messages = [
        {"role": "user", "content": prompt},
    ]

    try:
        analysis = await client.complete(messages, PeerAnalysis)
        logger.info("Peer analysis complete", ticker=ticker, peers=len(peers_list))
        return {**state, "peer_analysis": analysis.model_dump()}
    except Exception as e:
        logger.error("Peer agent failed", ticker=ticker, error=str(e))
        return {**state, "errors": state.get("errors", []) + [f"peer_agent: {e}"]}


def _format_peers(peers_data: dict) -> str:
    lines = []
    ticker = peers_data.get("ticker", "")
    main = peers_data.get("main_fundamentals", {})
    lines.append(f"TICKER ANALIZADO: {ticker}")
    lines.append(f"  P/E: {main.get('pe_ratio', 'N/A')}  Revenue Growth: {main.get('revenue_growth_yoy', 'N/A')}")
    lines.append("")
    lines.append("PEERS:")
    for p in peers_data.get("peers", []):
        f = p.get("fundamentals", {})
        lines.append(f"  {p['ticker']}: P/E={f.get('pe_ratio', 'N/A')} RevGrowth={f.get('revenue_growth_yoy', 'N/A')}")
    return "\n".join(lines)
