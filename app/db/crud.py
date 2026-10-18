from sqlalchemy.orm import Session
from sqlalchemy import select, desc, delete
from datetime import date, datetime
from app.db.models import (
    Company, PriceHistory, FundamentalData, EarningsRecord, NewsItem, Suggestion, Position, AnalysisJob,
)
from app.llm.schemas import StockSuggestion


def get_or_create_company(db: Session, ticker: str, name: str, market: str, **kwargs) -> Company:
    company = db.get(Company, ticker)
    if not company:
        company = Company(ticker=ticker, name=name, market=market, **kwargs)
        db.add(company)
        db.commit()
        db.refresh(company)
    return company


def delete_company(db: Session, ticker: str) -> bool:
    """Hard delete a company and all rows referencing it (price history,
    fundamentals, earnings, news, suggestions). Returns False if the ticker
    doesn't exist."""
    company = db.get(Company, ticker)
    if not company:
        return False

    for model in (PriceHistory, FundamentalData, EarningsRecord, NewsItem, Suggestion):
        db.execute(delete(model).where(model.ticker == ticker))

    db.delete(company)
    db.commit()
    return True


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


# ── Positions (holdings a revisar: ¿mantener o vender?) ──────────────────────

def create_position(
    db: Session,
    ticker: str,
    purchase_date: date,
    purchase_price: float,
    quantity: float = 1.0,
    notes: str | None = None,
) -> Position:
    position = Position(
        ticker=ticker,
        purchase_date=purchase_date,
        purchase_price=purchase_price,
        quantity=quantity,
        notes=notes,
    )
    db.add(position)
    db.commit()
    db.refresh(position)
    return position


def get_positions(db: Session, active_only: bool = True) -> list[Position]:
    stmt = select(Position).order_by(desc(Position.purchase_date))
    if active_only:
        stmt = stmt.where(Position.active == True)
    return list(db.scalars(stmt))


def get_position(db: Session, position_id: int) -> Position | None:
    return db.get(Position, position_id)


def close_position(db: Session, position_id: int) -> Position | None:
    position = db.get(Position, position_id)
    if not position:
        return None
    position.active = False
    position.closed_at = datetime.utcnow()
    db.commit()
    db.refresh(position)
    return position


def delete_position(db: Session, position_id: int) -> bool:
    position = db.get(Position, position_id)
    if not position:
        return False
    db.delete(position)
    db.commit()
    return True


# ── Analysis jobs (análisis/revisión de posición en background) ─────────────

def find_active_job(
    db: Session, job_type: str, ticker: str, position_id: int | None = None
) -> AnalysisJob | None:
    """Evita encolar un duplicado si ya hay un job queued/running para el
    mismo ticker (y, si aplica, la misma posición)."""
    stmt = select(AnalysisJob).where(
        AnalysisJob.job_type == job_type,
        AnalysisJob.ticker == ticker,
        AnalysisJob.status.in_(["queued", "running"]),
    )
    if position_id is not None:
        stmt = stmt.where(AnalysisJob.position_id == position_id)
    return db.scalar(stmt.order_by(desc(AnalysisJob.created_at)))


def create_job(
    db: Session, job_type: str, ticker: str, market: str | None = None, position_id: int | None = None
) -> AnalysisJob:
    job = AnalysisJob(job_type=job_type, ticker=ticker, market=market, position_id=position_id)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: int) -> AnalysisJob | None:
    return db.get(AnalysisJob, job_id)


def list_jobs(db: Session, status: str | None = None, limit: int = 50) -> list[AnalysisJob]:
    stmt = select(AnalysisJob).order_by(desc(AnalysisJob.created_at)).limit(limit)
    if status:
        stmt = stmt.where(AnalysisJob.status == status)
    return list(db.scalars(stmt))


def mark_job_running(db: Session, job_id: int) -> None:
    job = db.get(AnalysisJob, job_id)
    if job:
        job.status = "running"
        job.started_at = datetime.utcnow()
        db.commit()


def mark_job_done(db: Session, job_id: int, result: dict) -> None:
    job = db.get(AnalysisJob, job_id)
    if job:
        job.status = "done"
        job.result = result
        job.finished_at = datetime.utcnow()
        db.commit()


def mark_job_failed(db: Session, job_id: int, error: str) -> None:
    job = db.get(AnalysisJob, job_id)
    if job:
        job.status = "failed"
        job.error = error
        job.finished_at = datetime.utcnow()
        db.commit()
