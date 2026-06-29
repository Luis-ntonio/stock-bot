import pytest
from unittest.mock import AsyncMock, MagicMock
from app.data.rate_limiter import RateLimiter, RATE_LIMITS


class TestRateLimiterLimits:
    def test_finnhub_has_rpm_limit(self):
        assert RATE_LIMITS["finnhub"]["rpm"] == 60
        assert RATE_LIMITS["finnhub"]["rpd"] is None

    def test_fmp_has_rpd_limit(self):
        assert RATE_LIMITS["fmp"]["rpd"] == 250
        assert RATE_LIMITS["fmp"]["rpm"] is None

    def test_alpha_vantage_has_both_limits(self):
        assert RATE_LIMITS["alpha_vantage"]["rpm"] == 5
        assert RATE_LIMITS["alpha_vantage"]["rpd"] == 25

    def test_groq_has_strict_rpd(self):
        assert RATE_LIMITS["groq_llama70b"]["rpd"] == 1_000
        assert RATE_LIMITS["groq_llama70b"]["rpm"] == 30

    def test_gemini_has_rpd_limit(self):
        assert RATE_LIMITS["gemini_flash"]["rpd"] == 1_500

    @pytest.mark.asyncio
    async def test_acquire_rpm_increments_counter(self):
        redis = AsyncMock()
        pipe = AsyncMock()
        pipe.execute = AsyncMock(return_value=[5, 30])  # count=5, ttl=30
        redis.pipeline.return_value = pipe
        redis.expire = AsyncMock()

        rl = RateLimiter(redis)
        await rl.acquire("yfinance")  # count 5 < 60 rpm — debería pasar sin wait

    @pytest.mark.asyncio
    async def test_acquire_ollama_skips_redis(self):
        redis = AsyncMock()
        pipe = AsyncMock()
        redis.pipeline.return_value = pipe

        rl = RateLimiter(redis)
        await rl.acquire("ollama")
        # Ollama no tiene límites — pipeline no debería ser llamado
        pipe.execute.assert_not_called()
