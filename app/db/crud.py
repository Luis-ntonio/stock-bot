from sqlalchemy.orm import Session
from sqlalchemy import select, desc
from datetime import date, datetime
from app.db.models import Company, PriceHistory, FundamentalData, EarningsRecord, NewsItem, Suggestion
from app.llm.schemas import StockSuggestion


def get_or_create_company(db: Session, ticker: str, name: str, market: str, **kwargs) -> Company:
    company = db.get(Company, ticker)
    if not company:
        company = Company(ticker=ticker, name=name, market=market, **kwargs)
        db.add(company)
        db.commit()
        db.refresh(company)
    return company


def get_watchlist(db: Session, market: str | None = None) -> list[Company]:
    stmt = select(Company).where(Company.active == True)
    if market:
        stmt = stmt.where(Company.market == market)
    return list(db.scalars(stmt))


def upsert_price(db: Session, ticker: str, price_date: date, ohlcv: dict) -> PriceHistory:
    stmt = select(PriceHistory).where(
        PriceHistory.ticker == ticker,
        PriceHistory.date == price_date,
    )
    existing = db.scalar(stmt)
    if existing:
        for k, v in ohlcv.items():
            setattr(existing, k, v)
    else:
        existing = PriceHistory(ticker=ticker, date=price_date, **ohlcv)
        db.add(existing)
    db.commit()
    return existing


def save_fundamentals(db: Session, ticker: str, snapshot_date: date, data: dict) -> FundamentalData:
    record = FundamentalData(ticker=ticker, snapshot_date=snapshot_date, **data)
    db.add(record)
    db.commit()
    return record


def save_earnings(db: Session, ticker: str, records: list[dict]) -> list[EarningsRecord]:
    saved = []
    for rec in records:
        er = EarningsRecord(ticker=ticker, **rec)
        db.add(er)
        saved.append(er)
    db.commit()
    return saved


def save_news(db: Session, ticker: str, items: list[dict]) -> list[NewsItem]:
    saved = []
    for item in items:
        ni = NewsItem(ticker=ticker, **item)
        db.add(ni)
        saved.append(ni)
    db.commit()
    return saved


def save_suggestion(db: Session, suggestion: StockSuggestion) -> Suggestion:
    record = Suggestion(
        ticker=suggestion.ticker,
        signal=suggestion.signal.value,
        confidence=suggestion.confidence,
        timeframe=suggestion.timeframe.value,
        risk_level=suggestion.risk_level.value,
        current_price=suggestion.current_price,
        target_price_low=suggestion.target_price_low,
        target_price_base=suggestion.target_price_base,
        target_price_high=suggestion.target_price_high,
        bull_case=suggestion.bull_case,
        bear_case=suggestion.bear_case,
        final_reasoning=suggestion.final_reasoning,
        key_catalysts=suggestion.key_catalysts,
        key_risks=suggestion.key_risks,
        llm_model=suggestion.llm_model_used,
        data_sources=suggestion.data_sources,
        full_output=suggestion.model_dump(mode="json"),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_suggestions(db: Session, ticker: str, limit: int = 10) -> list[Suggestion]:
    stmt = (
        select(Suggestion)
        .where(Suggestion.ticker == ticker)
        .order_by(desc(Suggestion.created_at))
        .limit(limit)
    )
    return list(db.scalars(stmt))


def get_latest_suggestion(db: Session, ticker: str) -> Suggestion | None:
    stmt = (
        select(Suggestion)
        .where(Suggestion.ticker == ticker)
        .order_by(desc(Suggestion.created_at))
        .limit(1)
    )
    return db.scalar(stmt)
