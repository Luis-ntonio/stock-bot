from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.crud import create_job, find_active_job
from app.jobs import execute_job
import structlog

router = APIRouter(prefix="/analysis", tags=["analysis"])
logger = structlog.get_logger(__name__)


@router.post("/{ticker}", status_code=202)
def trigger_analysis(
    ticker: str,
    background_tasks: BackgroundTasks,
    market: str = "US",
    db: Session = Depends(get_db),
):
    """Encola un análisis completo del ticker y devuelve de inmediato — no
    bloquea esperando el pipeline (puede tardar 20+ minutos contra un LLM
    local). El resultado se consulta vía GET /api/jobs/{job_id}."""
    ticker = ticker.upper()

    existing = find_active_job(db, job_type="analysis", ticker=ticker)
    if existing:
        return {"job_id": existing.id, "status": existing.status}

    job = create_job(db, job_type="analysis", ticker=ticker, market=market)
    background_tasks.add_task(execute_job, job.id)
    logger.info("Analysis job queued", job_id=job.id, ticker=ticker)
    return {"job_id": job.id, "status": job.status}
