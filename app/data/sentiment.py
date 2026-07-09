import asyncio
import httpx
from typing import Any
from app.config import settings
from app.data.rate_limiter import get_rate_limiter
import structlog

logger = structlog.get_logger(__name__)

APEWISDOM_BASE = "https://apewisdom.io/api/v1.0"
STOCKTWITS_BASE = "https://api.stocktwits.com/api/2"


async def get_sentiment(ticker: str) -> dict[str, Any]:
    results: dict[str, Any] = {
        "reddit_mentions_7d": None,
        "stocktwits_sentiment": None,
        "news_sentiment_score": None,
        "key_headlines": [],
    }

    tasks = [
        _apewisdom_mentions(ticker),
        _stocktwits_sentiment(ticker),
        _reddit_mentions(ticker),
    ]
    ape_result, twits_result, reddit_result = await asyncio.gather(*tasks, return_exceptions=True)

    if isinstance(ape_result, dict):
        results["reddit_mentions_7d"] = ape_result.get("mentions")
    elif isinstance(reddit_result, dict):
        results["reddit_mentions_7d"] = reddit_result.get("mentions")

    if isinstance(twits_result, dict):
        results["stocktwits_sentiment"] = twits_result.get("sentiment")
        results["key_headlines"] = twits_result.get("messages", [])[:3]

    return results


async def _apewisdom_mentions(ticker: str) -> dict | None:
    """ApeWisdom: menciones pre-agregadas de WSB/Reddit. Sin auth."""
    rl = get_rate_limiter()
    await rl.acquire("apewisdom")

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{APEWISDOM_BASE}/filter/all-stocks/page/1",
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()

        results = data.get("results", [])
        for item in results:
            if item.get("ticker", "").upper() == ticker.upper():
                return {
                    "mentions": item.get("mentions"),
                    "rank": item.get("rank"),
                    "rank_24h_ago": item.get("rank_24h_ago"),
                }
    except Exception as e:
        logger.debug("ApeWisdom failed", ticker=ticker, error=str(e))

    return None


async def _stocktwits_sentiment(ticker: str) -> dict | None:
    """StockTwits: sentimiento bullish/bearish con tags."""
    rl = get_rate_limiter()
    await rl.acquire("stocktwits")

    try:
        from curl_cffi.requests import AsyncSession as CurlSession

        # StockTwits blocks httpx's default TLS fingerprint (403 via Cloudflare);
        # impersonating Chrome's TLS handshake gets through, same trick used for yfinance.
        async with CurlSession() as client:
            r = await client.get(
                f"{STOCKTWITS_BASE}/streams/symbol/{ticker}.json",
                impersonate="chrome",
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()

        messages = data.get("messages", [])
        if not messages:
            return None

        def _basic_sentiment(m: dict) -> str | None:
            entities = m.get("entities") or {}
            sentiment = entities.get("sentiment") or {}
            return sentiment.get("basic")

        bullish = sum(1 for m in messages if _basic_sentiment(m) == "Bullish")
        bearish = sum(1 for m in messages if _basic_sentiment(m) == "Bearish")
        total = bullish + bearish
        if total == 0:
            sentiment = "neutral"
        elif bullish / total > 0.6:
            sentiment = "bullish"
        elif bearish / total > 0.6:
            sentiment = "bearish"
        else:
            sentiment = "neutral"

        top_messages = [m.get("body", "") for m in messages[:3] if m.get("body")]

        return {"sentiment": sentiment, "messages": top_messages}
    except Exception as e:
        logger.debug("StockTwits failed", ticker=ticker, error=str(e))

    return None


async def _reddit_mentions(ticker: str) -> dict | None:
    """PRAW: menciones en r/wallstreetbets y r/stocks (últimos 7 días)."""
    if not settings.reddit_client_id or not settings.reddit_client_secret:
        return None

    loop = asyncio.get_event_loop()

    def _fetch():
        import praw
        reddit = praw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
        )
        count = 0
        for sub in ["wallstreetbets", "stocks"]:
            for post in reddit.subreddit(sub).search(ticker, time_filter="week", limit=25):
                if ticker.upper() in post.title.upper():
                    count += 1
        return {"mentions": count}

    try:
        return await loop.run_in_executor(None, _fetch)
    except Exception as e:
        logger.debug("Reddit PRAW failed", ticker=ticker, error=str(e))
    return None
