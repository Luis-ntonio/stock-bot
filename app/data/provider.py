import asyncio
import pandas as pd
from datetime import datetime, timedelta, date
from typing import Any
from app.data.rate_limiter import get_rate_limiter
from app.llm.schemas import FundamentalSnapshot
import structlog

logger = structlog.get_logger(__name__)

PRICE_CACHE_TTL = timedelta(minutes=15)
# Freshness threshold for DB cache: data older than this is re-fetched from API
DB_CACHE_MAX_STALENESS_DAYS = 5  # covers weekends + holidays


class DataProvider:
    """
    Abstracción de datos con fallback chain por tipo de mercado.

    US: Finnhub → FMP → yfinance → cache DB
    Crypto: CoinGecko → Binance
    LATAM: Yahoo .LM → NYSE ADR → SMV WebService
    EU: Yahoo (XETRA .DE y otras bolsas europeas)
    SEC filings: edgartools exclusivamente

    Cache layers (get_price_history):
      1. In-memory TTL (15 min) — avoids repeated API calls in same run
      2. DB PriceHistory — survives server restarts, checked on memory-cache miss
      3. External API — source of truth, writes back to both caches
    """

    def __init__(self):
        self._rl = None
        self._price_cache: dict[str, tuple[datetime, pd.DataFrame]] = {}

    @property
    def rl(self):
        if self._rl is None:
            self._rl = get_rate_limiter()
        return self._rl

    async def get_price_history(
        self,
        ticker: str,
        period: str = "1y",
        interval: str = "1d",
        market: str = "US",
    ) -> pd.DataFrame:
        cache_key = f"{market}:{ticker}:{period}:{interval}"

        # Layer 1 — in-memory TTL cache
        if cache_key in self._price_cache:
            cached_at, cached_df = self._price_cache[cache_key]
            if datetime.utcnow() - cached_at < PRICE_CACHE_TTL:
                logger.debug("Price cache hit (memory)", ticker=ticker)
                return cached_df

        # Layer 2 — DB cache (persists across restarts)
        db_df = await self._get_db_price_history(ticker)
        if db_df is not None and not db_df.empty:
            self._price_cache[cache_key] = (datetime.utcnow(), db_df)
            logger.debug("Price cache hit (DB)", ticker=ticker, rows=len(db_df))
            return db_df

        # Layer 3 — external API
        from app.data import us_stocks, crypto, latam, europe
        if market == "CRYPTO":
            df = await crypto.get_price_history(ticker, period)
        elif market == "LATAM":
            df = await latam.get_price_history(ticker, period)
        elif market == "EU":
            df = await europe.get_price_history(ticker, period)
        else:
            df = await us_stocks.get_price_history(ticker, period, interval)

        # Write back to caches
        self._price_cache[cache_key] = (datetime.utcnow(), df)
        asyncio.create_task(self._upsert_price_history(ticker, df))

        return df

    async def _get_db_price_history(self, ticker: str) -> pd.DataFrame | None:
        """Read PriceHistory rows from DB and reconstruct a DataFrame."""
        def _sync_read():
            from app.db.session import get_sync_db_session
            from app.db.models import PriceHistory
            from sqlalchemy import select

            cutoff = date.today() - timedelta(days=365 + 10)
            with get_sync_db_session() as db:
                stmt = (
                    select(PriceHistory)
                    .where(PriceHistory.ticker == ticker, PriceHistory.date >= cutoff)
                    .order_by(PriceHistory.date)
                )
                # Extract plain values while the session is still open — the
                # context manager commits on exit, which expires ORM attributes
                # and makes them unreadable afterwards (DetachedInstanceError).
                return [
                    {
                        "date": r.date,
                        "open": r.open,
                        "high": r.high,
                        "low": r.low,
                        "close": r.close,
                        "volume": r.volume,
                    }
                    for r in db.scalars(stmt)
                ]

        try:
            loop = asyncio.get_event_loop()
            rows = await loop.run_in_executor(None, _sync_read)

            if not rows:
                return None

            latest_date = rows[-1]["date"]
            if (date.today() - latest_date).days > DB_CACHE_MAX_STALENESS_DAYS:
                logger.debug("DB price data stale", ticker=ticker, latest=str(latest_date))
                return None

            df = pd.DataFrame(rows).set_index("date")
            return df

        except Exception as e:
            logger.debug("DB price cache read failed", ticker=ticker, error=str(e))
            return None

    async def _upsert_price_history(self, ticker: str, df: pd.DataFrame) -> None:
        """Persist fetched price data to DB (fire-and-forget, called via create_task)."""
        if df is None or df.empty:
            return

        def _sync_write():
            from app.db.session import get_sync_db_session
            from app.db import crud

            with get_sync_db_session() as db:
                for idx_val, row in df.iterrows():
                    row_date = (
                        idx_val if isinstance(idx_val, date)
                        else idx_val.date() if hasattr(idx_val, "date")
                        else idx_val
                    )
                    ohlcv = {
                        "open": float(row.get("open") or 0),
                        "high": float(row.get("high") or 0),
                        "low": float(row.get("low") or 0),
                        "close": float(row.get("close") or 0),
                        "volume": int(row.get("volume") or 0),
                    }
                    try:
                        crud.upsert_price(db, ticker, row_date, ohlcv)
                    except Exception:
                        pass

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _sync_write)
            logger.debug("Price history persisted to DB", ticker=ticker, rows=len(df))
        except Exception as e:
            logger.warning("Failed to persist price history to DB", ticker=ticker, error=str(e))

    async def get_fundamentals(self, ticker: str, market: str = "US") -> FundamentalSnapshot:
        from app.data import us_stocks, crypto, latam, europe

        if market == "CRYPTO":
            return await crypto.get_fundamentals(ticker)
        elif market == "LATAM":
            return await latam.get_fundamentals(ticker)
        elif market == "EU":
            return await europe.get_fundamentals(ticker)
        else:
            return await us_stocks.get_fundamentals(ticker)

    async def get_earnings_history(self, ticker: str, quarters: int = 8) -> list[dict]:
        from app.data import us_stocks
        return await us_stocks.get_earnings_history(ticker, quarters)

    async def get_upcoming_earnings(self, ticker: str) -> dict | None:
        from app.data import us_stocks
        return await us_stocks.get_upcoming_earnings(ticker)

    async def get_peers(self, ticker: str, n: int = 5, market: str = "US") -> list[str]:
        if market == "EU":
            from app.data import europe
            return await europe.get_peers(ticker, n)
        elif market == "LATAM":
            from app.data import latam
            return await latam.get_peers(ticker, n)
        elif market == "CRYPTO":
            return []
        from app.data import us_stocks
        return await us_stocks.get_peers(ticker, n)

    async def get_sec_filing(self, ticker: str, form_type: str = "10-K") -> str:
        from app.data import sec_edgar
        return await sec_edgar.get_filing_text(ticker, form_type)

    async def get_news(self, ticker: str, days: int = 30) -> list[dict]:
        from app.data import news
        return await news.get_news(ticker, days)

    async def get_sentiment(self, ticker: str) -> dict[str, Any]:
        from app.data import sentiment
        return await sentiment.get_sentiment(ticker)

    async def get_company_name(self, ticker: str, market: str = "US") -> str | None:
        """Resolve human-readable company name."""
        info = await self.get_company_info(ticker, market=market)
        return info.get("name")

    async def get_company_info(self, ticker: str, market: str = "US") -> dict[str, str | None]:
        """Resolve name/sector/industry for watchlist autofill and analysis."""
        empty = {"name": None, "sector": None, "industry": None}

        if market == "CRYPTO":
            from app.data import crypto
            try:
                return await crypto.get_company_info(ticker)
            except Exception as e:
                logger.debug("Company info lookup failed (crypto)", ticker=ticker, error=str(e))
                return empty

        yf_ticker = ticker
        if market == "EU":
            from app.data.europe import _resolve_ticker
            yf_ticker = _resolve_ticker(ticker)
        elif market == "LATAM":
            from app.data.latam import _resolve_ticker
            yf_ticker = _resolve_ticker(ticker)

        def _fetch():
            import yfinance as yf
            from curl_cffi.requests import Session as CurlSession
            with CurlSession(impersonate="chrome") as session:
                t = yf.Ticker(yf_ticker, session=session)
                info = t.info or {}
                return {
                    "name": info.get("longName") or info.get("shortName"),
                    "sector": info.get("sector"),
                    "industry": info.get("industry"),
                }

        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _fetch)
        except Exception as e:
            logger.debug("Company info lookup failed", ticker=ticker, market=market, error=str(e))
            return empty


_provider: DataProvider | None = None


def get_data_provider() -> DataProvider:
    global _provider
    if _provider is None:
        _provider = DataProvider()
    return _provider
