from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from datetime import date, datetime
from app.db.session import get_db
from app.db.crud import (
    create_position, get_positions, get_position, close_position, delete_position,
    create_job, find_active_job,
)
from app.db.models import Company
from app.jobs import execute_job
import structlog

router = APIRouter(prefix="/positions", tags=["positions"])
logger = structlog.get_logger(__name__)


class PositionCreate(BaseModel):
    ticker: str
    market: str = "US"
    purchase_date: date
    purchase_price: float = Field(gt=0)
    quantity: float = Field(gt=0, default=1.0)
    notes: str | None = None


class PositionResponse(BaseModel):
    id: int
    ticker: str
    purchase_date: date
    purchase_price: float
    quantity: float
    notes: str | None
    active: bool
    created_at: datetime | None
    closed_at: datetime | None

    model_config = {"from_attributes": True}


@router.post("/", response_model=PositionResponse)
def add_position(body: PositionCreate, db: Session = Depends(get_db)):
    ticker = body.ticker.upper()
    if not db.get(Company, ticker):
        raise HTTPException(
            status_code=400,
            detail=f"{ticker} no está en el watchlist — agrégalo primero con POST /api/watchlist/",
        )

    position = create_position(
        db,
        ticker=ticker,
        purchase_date=body.purchase_date,
        purchase_price=body.purchase_price,
        quantity=body.quantity,
        notes=body.notes,
    )
    return position


@router.get("/", response_model=list[PositionResponse])
def list_positions(active_only: bool = True, db: Session = Depends(get_db)):
    return get_positions(db, active_only=active_only)


@router.delete("/{position_id}")
def remove_position(position_id: int, hard: bool = False, db: Session = Depends(get_db)):
    if hard:
        ok = delete_position(db, position_id)
    else:
        ok = close_position(db, position_id) is not None
    if not ok:
        raise HTTPException(status_code=404, detail="Position not found")
    return {"ok": True}


@router.post("/{position_id}/review", status_code=202)
def review_position_endpoint(
    position_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """Encola la revisión HOLD/SELL de la posición y devuelve de inmediato
    — no bloquea esperando el pipeline completo. El resultado se consulta
    vía GET /api/jobs/{job_id}."""
    position = get_position(db, position_id)
    if not position:
        raise HTTPException(status_code=404, detail="Position not found")

    existing = find_active_job(db, job_type="position_review", ticker=position.ticker, position_id=position_id)
    if existing:
        return {"job_id": existing.id, "status": existing.status}

    job = create_job(
        db,
        job_type="position_review",
        ticker=position.ticker,
        market=position.company.market if position.company else "US",
        position_id=position_id,
    )
    background_tasks.add_task(execute_job, job.id)
    logger.info("Position review job queued", job_id=job.id, position_id=position_id)
    return {"job_id": job.id, "status": job.status}
