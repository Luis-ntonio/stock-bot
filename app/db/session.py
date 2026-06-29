from contextlib import asynccontextmanager, contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import settings


def _make_async_url(url: str) -> str:
    """Convierte DATABASE_URL a variante async."""
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


# ── Async engine (FastAPI + agentes) ────────────────────────────────────────
async_engine = create_async_engine(
    _make_async_url(settings.database_url),
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

AsyncSessionLocal = async_sessionmaker(
    async_engine, class_=AsyncSession, expire_on_commit=False
)


@asynccontextmanager
async def get_db_session():
    """Context manager async para uso en agentes y tasks en background."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db_async() -> AsyncSession:
    """Dependency para FastAPI con AsyncSession."""
    async with AsyncSessionLocal() as session:
        yield session


# ── Sync engine (APScheduler corre en thread separado, no event loop) ────────
_sync_url = settings.database_url
sync_engine = create_engine(
    _sync_url,
    connect_args={"check_same_thread": False} if "sqlite" in _sync_url else {},
)

SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


@contextmanager
def get_sync_db_session():
    """Context manager síncrono para APScheduler y scripts CLI."""
    db = SyncSessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Session:
    """Dependency FastAPI síncrona (usar solo en routers que no son async críticos)."""
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()
