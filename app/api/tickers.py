from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Literal
from app.db.session import get_db
from app.db.crud import get_or_create_company, get_watchlist
from app.db.models import Company

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class TickerCreate(BaseModel):
    ticker: str
    name: str
    market: Literal["US", "CRYPTO", "LATAM"]
    sector: str | None = None
    industry: str | None = None


class TickerResponse(BaseModel):
    ticker: str
    name: str
    market: str
    sector: str | None
    industry: str | None
    active: bool

    model_config = {"from_attributes": True}


@router.get("/", response_model=list[TickerResponse])
def list_watchlist(market: str | None = None, db: Session = Depends(get_db)):
    return get_watchlist(db, market=market)


@router.post("/", response_model=TickerResponse, status_code=201)
def add_ticker(payload: TickerCreate, db: Session = Depends(get_db)):
    company = get_or_create_company(
        db,
        ticker=payload.ticker.upper(),
        name=payload.name,
        market=payload.market,
        sector=payload.sector,
        industry=payload.industry,
    )
    return company


@router.delete("/{ticker}", status_code=204)
def remove_ticker(ticker: str, db: Session = Depends(get_db)):
    company = db.get(Company, ticker.upper())
    if not company:
        raise HTTPException(status_code=404, detail="Ticker not found")
    company.active = False
    db.commit()
