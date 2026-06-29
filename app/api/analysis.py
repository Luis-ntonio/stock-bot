from fastapi import APIRouter, HTTPException, BackgroundTasks
from app.agents.workflow import analyze_ticker
from app.llm.schemas import StockSuggestion
import structlog

router = APIRouter(prefix="/analysis", tags=["analysis"])
logger = structlog.get_logger(__name__)

_running: set[str] = set()


@router.post("/{ticker}", response_model=StockSuggestion)
async def trigger_analysis(ticker: str, market: str = "US"):
    ticker = ticker.upper()

    if ticker in _running:
        raise HTTPException(status_code=409, detail=f"Analysis already running for {ticker}")

    _running.add(ticker)
    try:
        logger.info("Starting on-demand analysis", ticker=ticker, market=market)
        suggestion = await analyze_ticker(ticker, market=market)
        return suggestion
    except Exception as e:
        logger.error("Analysis failed", ticker=ticker, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _running.discard(ticker)
