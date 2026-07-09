import asyncio
import time
from redis.asyncio import Redis
from app.config import settings
import structlog

logger = structlog.get_logger(__name__)

RATE_LIMITS: dict[str, dict[str, int | None]] = {
    "finnhub":        {"rpm": 60,     "rpd": None},
    "fmp":            {"rpm": None,   "rpd": 250},
    "alpha_vantage":  {"rpm": 5,      "rpd": 25},
    "coingecko":      {"rpm": 30,     "rpd": 10_000},
    "yfinance":       {"rpm": 60,     "rpd": None},
    "sec_edgar":      {"rpm": 10,     "rpd": None},
    "smv":            {"rpm": 5,      "rpd": None},
    "groq_llama70b":  {"rpm": 30,     "rpd": 1_000},
    "groq_llama8b":   {"rpm": 30,     "rpd": 14_400},
    "gemini_flash":   {"rpm": 10,     "rpd": 20},
    "ollama":         {"rpm": None,   "rpd": None},
    "binance":        {"rpm": 1_200,  "rpd": None},
    "stocktwits":     {"rpm": 60,     "rpd": None},
    "apewisdom":      {"rpm": 10,     "rpd": None},
}


class RateLimiter:
    def __init__(self, redis_client: Redis):
        self._redis = redis_client

    async def acquire(self, provider: str) -> None:
        limits = RATE_LIMITS.get(provider, {})
        rpm = limits.get("rpm")
        rpd = limits.get("rpd")

        if rpm is not None:
            await self._check_and_wait(f"rl:{provider}:rpm", rpm, 60)
        if rpd is not None:
            await self._check_and_wait(f"rl:{provider}:rpd", rpd, self._seconds_until_midnight())

    async def _check_and_wait(self, key: str, limit: int, window_secs: int) -> None:
        while True:
            pipe = self._redis.pipeline()
            pipe.incr(key)
            pipe.ttl(key)
            count, ttl = await pipe.execute()

            if count == 1:
                await self._redis.expire(key, window_secs)

            if count <= limit:
                return

            wait = ttl if ttl > 0 else window_secs
            logger.warning("Rate limit reached, waiting", key=key, limit=limit, count=count, wait_secs=min(wait, 5))
            await asyncio.sleep(min(wait, 5))

    @staticmethod
    def _seconds_until_midnight() -> int:
        now = time.gmtime()
        return (23 - now.tm_hour) * 3600 + (59 - now.tm_min) * 60 + (60 - now.tm_sec)

    async def mark_exhausted(self, provider: str, retry_after_secs: int | None = None) -> None:
        """Flag a provider as out of quota (e.g. a server-side 429 with a daily
        limit) so subsequent calls skip it immediately instead of re-hitting
        the network and waiting on a response we already know will fail."""
        ttl = retry_after_secs if retry_after_secs and retry_after_secs > 0 else self._seconds_until_midnight()
        await self._redis.setex(f"rl:{provider}:exhausted", ttl, "1")

    async def is_exhausted(self, provider: str) -> bool:
        return bool(await self._redis.get(f"rl:{provider}:exhausted"))

    async def get_remaining(self, provider: str) -> dict[str, int | None]:
        limits = RATE_LIMITS.get(provider, {})
        result: dict[str, int | None] = {}

        if limits.get("rpm") is not None:
            used = await self._redis.get(f"rl:{provider}:rpm")
            result["rpm_remaining"] = limits["rpm"] - int(used or 0)

        if limits.get("rpd") is not None:
            used = await self._redis.get(f"rl:{provider}:rpd")
            result["rpd_remaining"] = limits["rpd"] - int(used or 0)

        return result


_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        raise RuntimeError("RateLimiter not initialized. Call init_rate_limiter() first.")
    return _limiter


async def init_rate_limiter() -> RateLimiter:
    global _limiter
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    _limiter = RateLimiter(redis)
    return _limiter
