"""
Tests de FastAPI routers con TestClient y base de datos SQLite en memoria.
Ejecutar: pytest tests/test_api.py -v
"""
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.db.session import get_db
from app.llm.schemas import (
    StockSuggestion, Signal, RiskLevel, FundamentalSnapshot, SentimentSummary,
)

# ── Test DB ───────────────────────────────────────────────────────────────────

_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
Base.metadata.create_all(bind=_engine)


def _override_get_db():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """
    TestClient with:
    - in-memory SQLite overriding get_db
    - lifespan startup (Redis + scheduler) patched out
    """
    from app.main import app
    app.dependency_overrides[get_db] = _override_get_db

    with patch("app.main.init_rate_limiter", new_callable=AsyncMock), \
         patch("app.main.scheduler"):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def reset_db():
    """Drop and recreate all tables before each test for isolation."""
    Base.metadata.drop_all(bind=_engine)
    Base.metadata.create_all(bind=_engine)


def _make_suggestion(**overrides) -> StockSuggestion:
    defaults = dict(
        ticker="AAPL",
        company_name="Apple Inc.",
        market="US",
        signal=Signal.BUY,
        confidence=0.75,
        risk_level=RiskLevel.MEDIUM,
        current_price=195.0,
        bull_case="Strong fundamentals and ecosystem lock-in",
        bear_case="Valuation stretched at current multiples",
        final_reasoning="Net positive — strong cash generation offsets valuation risk",
        fundamentals=FundamentalSnapshot(),
        peers=[],
        sentiment=SentimentSummary(),
        llm_model_used="groq/llama-3.3-70b-versatile",
        data_sources=["yfinance", "finnhub"],
    )
    defaults.update(overrides)
    return StockSuggestion(**defaults)


# ── Health ────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_returns_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_includes_timestamp(self, client):
        r = client.get("/api/health")
        assert "timestamp" in r.json()


# ── Watchlist ─────────────────────────────────────────────────────────────────

class TestWatchlist:
    def test_list_empty(self, client):
        r = client.get("/api/watchlist/")
        assert r.status_code == 200
        assert r.json() == []

    def test_add_ticker(self, client):
        r = client.post("/api/watchlist/", json={
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "market": "US",
            "sector": "Technology",
        })
        assert r.status_code == 201
        body = r.json()
        assert body["ticker"] == "AAPL"
        assert body["market"] == "US"
        assert body["active"] is True

    def test_ticker_normalized_to_uppercase(self, client):
        r = client.post("/api/watchlist/", json={"ticker": "msft", "name": "Microsoft", "market": "US"})
        assert r.status_code == 201
        assert r.json()["ticker"] == "MSFT"

    def test_add_and_list(self, client):
        client.post("/api/watchlist/", json={"ticker": "AAPL", "name": "Apple", "market": "US"})
        client.post("/api/watchlist/", json={"ticker": "BTC", "name": "Bitcoin", "market": "CRYPTO"})
        r = client.get("/api/watchlist/")
        assert r.status_code == 200
        tickers = {t["ticker"] for t in r.json()}
        assert "AAPL" in tickers
        assert "BTC" in tickers

    def test_filter_by_market(self, client):
        client.post("/api/watchlist/", json={"ticker": "AAPL", "name": "Apple", "market": "US"})
        client.post("/api/watchlist/", json={"ticker": "BTC", "name": "Bitcoin", "market": "CRYPTO"})
        r = client.get("/api/watchlist/", params={"market": "US"})
        assert r.status_code == 200
        assert all(t["market"] == "US" for t in r.json())

    def test_remove_ticker(self, client):
        client.post("/api/watchlist/", json={"ticker": "AAPL", "name": "Apple", "market": "US"})
        r = client.delete("/api/watchlist/AAPL")
        assert r.status_code == 204
        # Verify it's marked inactive (not returned)
        watchlist = client.get("/api/watchlist/").json()
        assert all(t["ticker"] != "AAPL" for t in watchlist)

    def test_remove_nonexistent_returns_404(self, client):
        r = client.delete("/api/watchlist/XXXX")
        assert r.status_code == 404

    def test_invalid_market_rejected(self, client):
        r = client.post("/api/watchlist/", json={"ticker": "XX", "name": "X", "market": "INVALID"})
        assert r.status_code == 422

    def test_add_same_ticker_twice_is_idempotent(self, client):
        client.post("/api/watchlist/", json={"ticker": "AAPL", "name": "Apple", "market": "US"})
        r = client.post("/api/watchlist/", json={"ticker": "AAPL", "name": "Apple", "market": "US"})
        assert r.status_code == 201  # get_or_create returns existing
        # Only one entry should appear
        watchlist = client.get("/api/watchlist/").json()
        assert len([t for t in watchlist if t["ticker"] == "AAPL"]) == 1


# ── Suggestions ───────────────────────────────────────────────────────────────

class TestSuggestions:
    def _seed(self, **overrides):
        from app.db.crud import get_or_create_company, save_suggestion
        db = _TestSession()
        ticker = overrides.get("ticker", "AAPL")
        get_or_create_company(db, ticker, "Apple Inc.", "US")
        sug = _make_suggestion(**overrides)
        save_suggestion(db, sug)
        db.close()

    def test_list_empty(self, client):
        r = client.get("/api/suggestions/AAPL")
        assert r.status_code == 200
        assert r.json() == []

    def test_latest_not_found(self, client):
        r = client.get("/api/suggestions/AAPL/latest")
        assert r.status_code == 404

    def test_list_after_save(self, client):
        self._seed()
        r = client.get("/api/suggestions/AAPL")
        assert r.status_code == 200
        assert len(r.json()) == 1
        body = r.json()[0]
        assert body["ticker"] == "AAPL"
        assert body["signal"] == "BUY"
        assert 0.0 <= body["confidence"] <= 1.0

    def test_latest_returns_most_recent(self, client):
        self._seed(signal=Signal.HOLD, confidence=0.50)
        self._seed(signal=Signal.BUY, confidence=0.80)
        r = client.get("/api/suggestions/AAPL/latest")
        assert r.status_code == 200
        # The second suggestion (BUY, 0.80) is latest by created_at ordering
        assert r.json()["signal"] == "BUY"

    def test_limit_param(self, client):
        for i in range(5):
            self._seed(confidence=round(0.5 + i * 0.05, 2))
        r = client.get("/api/suggestions/AAPL", params={"limit": 3})
        assert r.status_code == 200
        assert len(r.json()) == 3

    def test_suggestion_has_required_fields(self, client):
        self._seed()
        body = client.get("/api/suggestions/AAPL/latest").json()
        required = {"ticker", "signal", "confidence", "current_price", "risk_level"}
        for field in required:
            assert field in body, f"Missing field: {field}"


# ── Analysis ──────────────────────────────────────────────────────────────────

class TestAnalysis:
    def test_success_returns_suggestion(self, client):
        mock_sug = _make_suggestion()
        with patch("app.api.analysis.analyze_ticker", new_callable=AsyncMock, return_value=mock_sug):
            r = client.post("/api/analysis/AAPL", params={"market": "US"})
        assert r.status_code == 200
        body = r.json()
        assert body["ticker"] == "AAPL"
        assert body["signal"] == "BUY"

    def test_ticker_normalized(self, client):
        mock_sug = _make_suggestion(ticker="MSFT", company_name="Microsoft")
        with patch("app.api.analysis.analyze_ticker", new_callable=AsyncMock, return_value=mock_sug):
            r = client.post("/api/analysis/msft")
        assert r.status_code == 200

    def test_concurrent_request_returns_409(self, client):
        with patch("app.api.analysis._running", {"AAPL"}):
            r = client.post("/api/analysis/AAPL")
        assert r.status_code == 409

    def test_analysis_failure_returns_500(self, client):
        with patch("app.api.analysis.analyze_ticker", new_callable=AsyncMock,
                   side_effect=RuntimeError("LLM unavailable")):
            r = client.post("/api/analysis/AAPL")
        assert r.status_code == 500
        assert "LLM unavailable" in r.json()["detail"]

    def test_response_has_disclaimer(self, client):
        mock_sug = _make_suggestion()
        with patch("app.api.analysis.analyze_ticker", new_callable=AsyncMock, return_value=mock_sug):
            r = client.post("/api/analysis/AAPL")
        assert "Not financial advice" in r.json()["disclaimer"]

    def test_response_has_llm_model(self, client):
        mock_sug = _make_suggestion(llm_model_used="groq/llama-3.3-70b-versatile")
        with patch("app.api.analysis.analyze_ticker", new_callable=AsyncMock, return_value=mock_sug):
            r = client.post("/api/analysis/AAPL")
        llm = r.json()["llm_model_used"]
        assert llm and llm not in ("unknown", "pending")

    def test_response_has_data_sources(self, client):
        mock_sug = _make_suggestion(data_sources=["yfinance", "finnhub"])
        with patch("app.api.analysis.analyze_ticker", new_callable=AsyncMock, return_value=mock_sug):
            r = client.post("/api/analysis/AAPL")
        assert len(r.json()["data_sources"]) > 0

    def test_confidence_in_range(self, client):
        mock_sug = _make_suggestion(confidence=0.72)
        with patch("app.api.analysis.analyze_ticker", new_callable=AsyncMock, return_value=mock_sug):
            r = client.post("/api/analysis/AAPL")
        conf = r.json()["confidence"]
        assert 0.0 <= conf <= 1.0
