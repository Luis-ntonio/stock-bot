import asyncio
import httpx
import feedparser
from datetime import datetime, timedelta
from app.config import settings
from app.data.rate_limiter import get_rate_limiter
import structlog

logger = structlog.get_logger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"

YAHOO_RSS_TEMPLATE = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"


async def get_news(ticker: str, days: int = 30) -> list[dict]:
    results: list[dict] = []

    try:
        finnhub_news = await _finnhub_news(ticker, days)
        results.extend(finnhub_news)
    except Exception as e:
        logger.warning("Finnhub news failed", ticker=ticker, error=str(e))

    if len(results) < 5:
        try:
            rss_news = await _yahoo_rss(ticker)
            results.extend(rss_news)
        except Exception as e:
            logger.warning("Yahoo RSS failed", ticker=ticker, error=str(e))

    # Deduplicar por URL
    seen = set()
    unique = []
    for item in results:
        url = item.get("url", "")
        if url not in seen:
            seen.add(url)
            unique.append(item)

    return unique[:50]


async def _finnhub_news(ticker: str, days: int) -> list[dict]:
    if not settings.finnhub_api_key:
        return []

    rl = get_rate_limiter()
    await rl.acquire("finnhub")

    end = datetime.now()
    start = end - timedelta(days=days)

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{FINNHUB_BASE}/company-news",
            params={
                "symbol": ticker,
                "from": start.strftime("%Y-%m-%d"),
                "to": end.strftime("%Y-%m-%d"),
                "token": settings.finnhub_api_key,
            },
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

    return [
        {
            "headline": item.get("headline", ""),
            "url": item.get("url", ""),
            "source": item.get("source", ""),
            "published_at": datetime.fromtimestamp(item["datetime"]) if item.get("datetime") else None,
            "sentiment_score": None,
        }
        for item in data
        if item.get("headline")
    ]


async def _yahoo_rss(ticker: str) -> list[dict]:
    loop = asyncio.get_event_loop()

    def _parse():
        url = YAHOO_RSS_TEMPLATE.format(ticker=ticker)
        feed = feedparser.parse(url)
        return feed.entries

    entries = await loop.run_in_executor(None, _parse)
    results = []

    for entry in entries[:20]:
        try:
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                from time import mktime
                published = datetime.fromtimestamp(mktime(entry.published_parsed))

            results.append({
                "headline": entry.get("title", ""),
                "url": entry.get("link", ""),
                "source": "Yahoo Finance RSS",
                "published_at": published,
                "sentiment_score": None,
            })
        except Exception:
            continue

    return results
