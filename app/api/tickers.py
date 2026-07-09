from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Literal
from app.db.session import get_db
from app.db.crud import get_or_create_company, get_watchlist, delete_company

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class TickerCreate(BaseModel):
    ticker: str
    name: str
    market: Literal["US", "CRYPTO", "LATAM", "EU"]
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


class TickerLookupResponse(BaseModel):
    name: str | None = None
    sector: str | None = None
    industry: str | None = None


@router.get("/", response_model=list[TickerResponse])
def list_watchlist(market: str | None = None, db: Session = Depends(get_db)):
    return get_watchlist(db, market=market)


@router.get("/lookup", response_model=TickerLookupResponse)
async def lookup_ticker(ticker: str, market: Literal["US", "CRYPTO", "LATAM", "EU"] = "US"):
    from app.data.provider import get_data_provider
    provider = get_data_provider()
    info = await provider.get_company_info(ticker.upper(), market=market)
    return TickerLookupResponse(**info)


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
    if not delete_company(db, ticker.upper()):
        raise HTTPException(status_code=404, detail="Ticker not found")
