from apscheduler.schedulers.asyncio import AsyncIOScheduler
import structlog

logger = structlog.get_logger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")


@scheduler.scheduled_job("cron", day_of_week="sun", hour=23, minute=0)
async def weekly_analysis_job():
    """Análisis batch semanal de todos los tickers del watchlist."""
    from app.db.session import get_db_session
    from app.db.crud import get_watchlist
    from app.agents.workflow import analyze_ticker
    from app.db.crud import save_suggestion

    logger.info("Starting weekly batch analysis")
    async with get_db_session() as db:
        tickers = get_watchlist(db)

    for company in tickers:
        try:
            suggestion = await analyze_ticker(company.ticker, company.market)
            async with get_db_session() as db:
                save_suggestion(db, suggestion)
            logger.info("Suggestion saved", ticker=company.ticker, signal=suggestion.signal)
        except Exception as e:
            logger.error("Analysis failed", ticker=company.ticker, error=str(e))


@scheduler.scheduled_job("cron", day_of_week="mon-fri", hour=22, minute=0)
async def eod_price_refresh():
    """Descarga precios EOD del día para todos los tickers."""
    from app.db.session import get_db_session
    from app.db.crud import get_watchlist
    from app.data.provider import get_data_provider
    from datetime import date

    logger.info("Starting EOD price refresh")
    provider = get_data_provider()

    async with get_db_session() as db:
        tickers = get_watchlist(db)

    for company in tickers:
        try:
            df = await provider.get_price_history(company.ticker, period="5d", market=company.market)
            if df is not None and not df.empty:
                logger.info("Prices updated", ticker=company.ticker, rows=len(df))
        except Exception as e:
            logger.error("EOD price refresh failed", ticker=company.ticker, error=str(e))


@scheduler.scheduled_job("cron", hour=8, minute=0)
async def daily_news_refresh():
    """Actualiza noticias y sentimiento para el watchlist activo."""
    from app.db.session import get_db_session
    from app.db.crud import get_watchlist, save_news
    from app.data.provider import get_data_provider

    logger.info("Starting daily news refresh")
    provider = get_data_provider()

    async with get_db_session() as db:
        tickers = get_watchlist(db)

    for company in tickers:
        try:
            news_items = await provider.get_news(company.ticker, days=1)
            if news_items:
                async with get_db_session() as db:
                    save_news(db, company.ticker, news_items)
                logger.info("News updated", ticker=company.ticker, count=len(news_items))
        except Exception as e:
            logger.error("News refresh failed", ticker=company.ticker, error=str(e))
