"""
Tests de la capa de datos.
Ejecutar: pytest tests/test_data_providers.py -v

Estos tests son de integración liviana: verifican que los providers
retornan datos con la forma correcta sin exceder rate limits.
"""
import pytest
import asyncio
import pandas as pd
from unittest.mock import AsyncMock, patch, MagicMock
from app.llm.schemas import FundamentalSnapshot


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.pipeline.return_value.__aenter__ = AsyncMock(return_value=redis)
    redis.pipeline.return_value.__aexit__ = AsyncMock(return_value=None)
    pipe = AsyncMock()
    pipe.execute = AsyncMock(return_value=[1, 60])
    redis.pipeline.return_value = pipe
    redis.expire = AsyncMock()
    redis.get = AsyncMock(return_value="0")
    return redis


@pytest.fixture
def sample_ohlcv_df():
    import numpy as np
    dates = pd.date_range("2024-01-01", periods=250, freq="B")
    df = pd.DataFrame({
        "open":   np.random.uniform(100, 200, 250),
        "high":   np.random.uniform(100, 200, 250),
        "low":    np.random.uniform(100, 200, 250),
        "close":  np.random.uniform(100, 200, 250),
        "volume": np.random.randint(1_000_000, 10_000_000, 250),
    }, index=dates)
    return df


# ── RateLimiter ───────────────────────────────────────────────────────────────

class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_does_not_raise_when_under_limit(self):
        from app.data.rate_limiter import RateLimiter

        redis = AsyncMock()
        pipe = AsyncMock()
        pipe.execute = AsyncMock(return_value=[1, 60])
        redis.pipeline.return_value = pipe
        redis.expire = AsyncMock()

        rl = RateLimiter(redis)
        # No debería levantar excepción
        await rl.acquire("yfinance")

    @pytest.mark.asyncio
    async def test_ollama_has_no_limits(self):
        from app.data.rate_limiter import RateLimiter, RATE_LIMITS
        limits = RATE_LIMITS.get("ollama", {})
        assert limits.get("rpm") is None
        assert limits.get("rpd") is None

    def test_all_providers_defined(self):
        from app.data.rate_limiter import RATE_LIMITS
        expected = ["finnhub", "fmp", "alpha_vantage", "coingecko", "yfinance",
                    "sec_edgar", "groq_llama70b", "gemini_flash", "ollama"]
        for provider in expected:
            assert provider in RATE_LIMITS, f"Missing provider: {provider}"


# ── Schemas ───────────────────────────────────────────────────────────────────

class TestSchemas:
    def test_fundamental_snapshot_all_none(self):
        f = FundamentalSnapshot()
        assert f.pe_ratio is None
        assert f.pb_ratio is None

    def test_fundamental_snapshot_with_values(self):
        f = FundamentalSnapshot(pe_ratio=25.5, revenue_growth_yoy=0.12)
        assert f.pe_ratio == 25.5
        assert f.revenue_growth_yoy == 0.12

    def test_stock_suggestion_requires_fields(self):
        from app.llm.schemas import StockSuggestion, Signal, RiskLevel, Timeframe
        from datetime import datetime

        sug = StockSuggestion(
            ticker="AAPL",
            company_name="Apple Inc.",
            market="US",
            analysis_date=datetime.utcnow(),
            signal=Signal.BUY,
            confidence=0.75,
            risk_level=RiskLevel.MEDIUM,
            current_price=195.0,
            bull_case="Strong revenue growth",
            bear_case="High valuation",
            final_reasoning="BUY based on fundamentals",
            fundamentals=FundamentalSnapshot(pe_ratio=28.0),
            sentiment=__import__("app.llm.schemas", fromlist=["SentimentSummary"]).SentimentSummary(),
            llm_model_used="groq/llama-3.3-70b-versatile",
            data_sources=["yfinance", "finnhub"],
        )
        assert sug.ticker == "AAPL"
        assert sug.signal == Signal.BUY
        assert sug.confidence == 0.75
        assert "Not financial advice" in sug.disclaimer

    def test_confidence_bounds(self):
        from app.llm.schemas import StockSuggestion, Signal, RiskLevel, FundamentalSnapshot, SentimentSummary
        from datetime import datetime
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            StockSuggestion(
                ticker="AAPL", company_name="Apple", market="US",
                analysis_date=datetime.utcnow(), signal=Signal.BUY,
                confidence=1.5,  # inválido
                risk_level=RiskLevel.LOW, current_price=100.0,
                bull_case="x", bear_case="x", final_reasoning="x",
                fundamentals=FundamentalSnapshot(),
                sentiment=SentimentSummary(),
                llm_model_used="test", data_sources=[],
            )


# ── Technical indicators ──────────────────────────────────────────────────────

class TestTechnicalIndicators:
    def test_add_indicators_creates_sma_columns(self, sample_ohlcv_df):
        from app.data.us_stocks import add_technical_indicators
        result = add_technical_indicators(sample_ohlcv_df)
        assert "SMA_50" in result.columns
        assert "SMA_200" in result.columns
        assert "RSI_14" in result.columns
        assert "golden_cross" in result.columns

    def test_golden_cross_is_boolean(self, sample_ohlcv_df):
        from app.data.us_stocks import add_technical_indicators
        result = add_technical_indicators(sample_ohlcv_df)
        non_null = result["golden_cross"].dropna()
        assert non_null.dtype == bool or set(non_null.unique()).issubset({True, False})


# ── DataProvider ──────────────────────────────────────────────────────────────

class TestDataProvider:
    def test_get_data_provider_returns_singleton(self):
        from app.data.provider import get_data_provider
        p1 = get_data_provider()
        p2 = get_data_provider()
        assert p1 is p2

    @pytest.mark.asyncio
    async def test_provider_calls_correct_module_for_crypto(self):
        from app.data.provider import DataProvider
        provider = DataProvider()

        mock_df = pd.DataFrame({"close": [50000.0]})
        with patch("app.data.crypto.get_price_history", new_callable=AsyncMock) as mock:
            mock.return_value = mock_df
            result = await provider.get_price_history("BTC", market="CRYPTO")
            mock.assert_called_once_with("BTC", "1y")

    @pytest.mark.asyncio
    async def test_provider_calls_correct_module_for_latam(self):
        from app.data.provider import DataProvider
        provider = DataProvider()

        mock_df = pd.DataFrame({"close": [10.0]})
        with patch("app.data.latam.get_price_history", new_callable=AsyncMock) as mock:
            mock.return_value = mock_df
            result = await provider.get_price_history("BAP", market="LATAM")
            mock.assert_called_once_with("BAP", "1y")


# ── SMV (LATAM fundamentals) ─────────────────────────────────────────────────

SMV_FIXTURE_ROWS = [
    # Empresa objetivo (RUC coincide) — ingresos y utilidad neta
    {"RUC": "20100055237", "NombreEmpresa": "ALICORP S.A.A.", "Cuenta": "2D01ST",
     "DescripcionCuenta": "Ingresos de Actividades Ordinarias", "Monto1": 6685002, "Monto2": 7319192},
    {"RUC": "20100055237", "NombreEmpresa": "ALICORP S.A.A.", "Cuenta": "2D07ST",
     "DescripcionCuenta": "Ganancia (Perdida) Neta del Ejercicio", "Monto1": 188369, "Monto2": 524143},
    # Fila de ruido: misma cuenta, otra empresa (RUC distinto) — no debe mezclarse
    {"RUC": "99999999999", "NombreEmpresa": "OTRA EMPRESA S.A.", "Cuenta": "2D01ST",
     "DescripcionCuenta": "Ingresos de Actividades Ordinarias", "Monto1": 1, "Monto2": 1},
    # Fila de ruido: misma empresa, cuenta irrelevante — no debe afectar el cálculo
    {"RUC": "20100055237", "NombreEmpresa": "ALICORP S.A.A.", "Cuenta": "2D0201",
     "DescripcionCuenta": "Costo de Ventas", "Monto1": -5093073, "Monto2": -5979200},
]


class TestSmvFundamentals:
    def test_extract_filters_by_ruc_and_computes_yoy_growth(self):
        from app.data.latam import _extract_smv_fundamentals

        snap = _extract_smv_fundamentals(SMV_FIXTURE_ROWS, ruc="20100055237")

        assert snap.revenue_growth_yoy == pytest.approx((6685002 - 7319192) / abs(7319192))
        assert snap.earnings_growth_yoy == pytest.approx((188369 - 524143) / abs(524143))

    def test_extract_returns_empty_snapshot_for_unknown_ruc(self):
        from app.data.latam import _extract_smv_fundamentals

        snap = _extract_smv_fundamentals(SMV_FIXTURE_ROWS, ruc="00000000000")

        assert snap.revenue_growth_yoy is None
        assert snap.earnings_growth_yoy is None

    @pytest.mark.asyncio
    async def test_smv_fundamentals_skips_soap_call_when_ruc_unknown(self):
        from app.data.latam import _smv_fundamentals

        with patch("app.data.latam._fetch_smv_dataset", new_callable=AsyncMock) as mock_fetch:
            snap = await _smv_fundamentals("SOME_TICKER_WITHOUT_RUC")
            mock_fetch.assert_not_called()
            assert snap.revenue_growth_yoy is None

    @pytest.mark.asyncio
    async def test_fetch_smv_dataset_uses_cache_within_ttl(self):
        from app.data import latam

        latam._smv_cache.clear()

        with patch("app.data.latam.get_rate_limiter") as mock_get_rl, \
             patch("zeep.Client") as mock_zeep_client:
            mock_rl = AsyncMock()
            mock_get_rl.return_value = mock_rl

            mock_soap = MagicMock()
            mock_soap.service.obtener_GanciaPerdida.return_value = "[]"
            mock_zeep_client.return_value = mock_soap

            await latam._fetch_smv_dataset("2025")
            await latam._fetch_smv_dataset("2025")

            assert mock_soap.service.obtener_GanciaPerdida.call_count == 1

    def test_ticker_to_ruc_uses_real_soap_signature(self):
        """Guards against regressing to the old broken kwargs (ruc/nemonic/
        periodo/tipo_periodo) — the real WSDL signature is Ejercicio/Periodo/Tipo."""
        import inspect
        from app.data import latam

        source = inspect.getsource(latam._fetch_smv_dataset)
        assert "Ejercicio=" in source
        assert "Periodo=" in source
        assert "Tipo=" in source
        assert "nemonic=" not in source
        assert "tipo_periodo=" not in source


# ── Alpha Vantage fallback (LATAM ADRs) ──────────────────────────────────────

def _mock_av_response(json_data: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=json_data)
    return resp


class TestAlphaVantageFundamentals:
    @pytest.mark.asyncio
    async def test_computes_debt_to_equity_from_balance_sheet(self):
        from app.data import latam

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_av_response({
            "annualReports": [{"totalLiabilities": "230004962000", "totalShareholderEquity": "36604559000"}]
        }))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_rl = AsyncMock()
        mock_rl.is_exhausted = AsyncMock(return_value=False)

        with patch("app.data.latam.settings") as mock_settings, \
             patch("httpx.AsyncClient", return_value=mock_client), \
             patch("app.data.latam.get_rate_limiter", return_value=mock_rl):
            mock_settings.alpha_vantage_key = "fake_key"
            result = await latam._alpha_vantage_fundamentals("BAP")

        assert result == {"debt_to_equity": pytest.approx(230004962000 / 36604559000)}

    @pytest.mark.asyncio
    async def test_marks_exhausted_on_quota_message(self):
        from app.data import latam

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_av_response({
            "Information": "Thank you for using Alpha Vantage! ... 25 requests per day"
        }))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_rl = AsyncMock()
        mock_rl.is_exhausted = AsyncMock(return_value=False)

        with patch("app.data.latam.settings") as mock_settings, \
             patch("httpx.AsyncClient", return_value=mock_client), \
             patch("app.data.latam.get_rate_limiter", return_value=mock_rl):
            mock_settings.alpha_vantage_key = "fake_key"
            result = await latam._alpha_vantage_fundamentals("BAP")

        assert result is None
        mock_rl.mark_exhausted.assert_called_once_with("alpha_vantage")

    @pytest.mark.asyncio
    async def test_skips_network_call_when_already_exhausted(self):
        from app.data import latam

        mock_rl = AsyncMock()
        mock_rl.is_exhausted = AsyncMock(return_value=True)

        with patch("app.data.latam.settings") as mock_settings, \
             patch("httpx.AsyncClient") as mock_client_cls, \
             patch("app.data.latam.get_rate_limiter", return_value=mock_rl):
            mock_settings.alpha_vantage_key = "fake_key"
            result = await latam._alpha_vantage_fundamentals("BAP")

        assert result is None
        mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_peru_adr_fundamentals_skips_av_when_yfinance_has_debt_to_equity(self):
        from app.data import latam
        from app.llm.schemas import FundamentalSnapshot

        with patch("app.data.us_stocks.get_fundamentals", new_callable=AsyncMock) as mock_us, \
             patch("app.data.latam._alpha_vantage_fundamentals", new_callable=AsyncMock) as mock_av:
            mock_us.return_value = FundamentalSnapshot(debt_to_equity=1.5)
            snap = await latam.get_fundamentals("BAP")

        mock_av.assert_not_called()
        assert snap.debt_to_equity == 1.5
