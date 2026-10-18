from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from app.api import health, tickers, analysis, suggestions, price, latam, positions, jobs
from app.scheduler import scheduler
from app.data.rate_limiter import init_rate_limiter

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting StockBot API")
    await init_rate_limiter()
    scheduler.start()
    logger.info("Scheduler started")
    yield
    scheduler.shutdown()
    logger.info("StockBot API stopped")


app = FastAPI(
    title="StockBot API",
    description="Monthly AI Stock Suggestion Bot — suggestion only, never executes trades",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(tickers.router, prefix="/api")
app.include_router(analysis.router, prefix="/api")
app.include_router(suggestions.router, prefix="/api")
app.include_router(price.router, prefix="/api")
app.include_router(latam.router, prefix="/api")
app.include_router(positions.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
