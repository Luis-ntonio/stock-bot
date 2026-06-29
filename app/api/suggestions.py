from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from app.db.session import get_db
from app.db.crud import get_suggestions, get_latest_suggestion

router = APIRouter(prefix="/suggestions", tags=["suggestions"])


class SuggestionResponse(BaseModel):
    id: int
    ticker: str
    created_at: datetime | None
    signal: str
    confidence: float
    timeframe: str
    risk_level: str | None
    current_price: float
    target_price_base: float | None
    bull_case: str | None
    bear_case: str | None
    final_reasoning: str | None
    llm_model: str | None
    data_sources: list | None
    full_output: dict | None = None

    model_config = {"from_attributes": True}


@router.get("/{ticker}", response_model=list[SuggestionResponse])
def get_ticker_suggestions(ticker: str, limit: int = 10, db: Session = Depends(get_db)):
    return get_suggestions(db, ticker.upper(), limit=limit)


@router.get("/{ticker}/latest", response_model=SuggestionResponse)
def get_latest(ticker: str, db: Session = Depends(get_db)):
    s = get_latest_suggestion(db, ticker.upper())
    if not s:
        raise HTTPException(status_code=404, detail="No suggestions found")
    return s
