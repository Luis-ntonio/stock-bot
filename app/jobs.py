"""Ejecución en background de análisis de ticker y revisión de posición.

Disparado vía FastAPI BackgroundTasks desde app/api/analysis.py y
app/api/positions.py — corre DESPUÉS de que la respuesta HTTP ya fue
enviada, así que el cliente (Streamlit) nunca queda bloqueado esperando
los ~20+ minutos que puede tardar el pipeline completo contra FreeToken.

Cada paso abre su propia sesión de DB sync (get_sync_db_session) en vez de
reusar una sesión de request — para cuando esto corre, la request original
ya terminó y su sesión pudo haberse cerrado.
"""
from app.db.session import get_sync_db_session
from app.db.crud import get_job, get_position, mark_job_running, mark_job_done, mark_job_failed
import structlog

logger = structlog.get_logger(__name__)


async def execute_job(job_id: int) -> None:
    with get_sync_db_session() as db:
        job = get_job(db, job_id)
        if not job:
            logger.error("Job not found at execution time", job_id=job_id)
            return
        job_type, ticker, market, position_id = job.job_type, job.ticker, job.market, job.position_id
        mark_job_running(db, job_id)

    logger.info("Job started", job_id=job_id, job_type=job_type, ticker=ticker)

    try:
        if job_type == "analysis":
            from app.agents.workflow import analyze_ticker
            suggestion = await analyze_ticker(ticker, market=market or "US")
            result = suggestion.model_dump(mode="json")

        elif job_type == "position_review":
            from app.agents.position_agent import review_position
            with get_sync_db_session() as db:
                position = get_position(db, position_id) if position_id else None
                if not position:
                    raise ValueError(f"Position {position_id} not found")
                # Extraer los campos ACÁ ADENTRO: get_sync_db_session hace
                # commit() al salir (incluso en una lectura pura), lo que
                # expira los atributos del objeto — acceder a ellos después
                # de cerrado el bloque revienta con "not bound to a Session".
                pos_ticker = position.ticker
                pos_purchase_date = position.purchase_date
                pos_purchase_price = position.purchase_price
                pos_quantity = position.quantity
            result = await review_position(
                ticker=pos_ticker,
                purchase_date=pos_purchase_date,
                purchase_price=pos_purchase_price,
                quantity=pos_quantity,
                market=market or "US",
            )

        else:
            raise ValueError(f"Unknown job_type: {job_type}")

        with get_sync_db_session() as db:
            mark_job_done(db, job_id, result)
        logger.info("Job finished", job_id=job_id, ticker=ticker)

    except Exception as e:
        logger.error("Job failed", job_id=job_id, ticker=ticker, error=str(e))
        with get_sync_db_session() as db:
            mark_job_failed(db, job_id, str(e))
