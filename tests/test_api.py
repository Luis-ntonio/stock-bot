"""
Tests de FastAPI routers con TestClient y base de datos SQLite en memoria.
Ejecutar: pytest tests/test_api.py -v
"""
import pytest
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.session import get_db
from app.llm.schemas import (
    StockSuggestion, Signal, RiskLevel, FundamentalSnapshot, SentimentSummary,
)

# ── Test DB ───────────────────────────────────────────────────────────────────
# StaticPool es necesario para sqlite en memoria + TestClient: sin esto, cada
# conexión nueva (TestClient despacha requests en threads del pool de anyio)
# ve una base de datos :memory: VACÍA distinta — "no such table" en todo lo que
# toque la DB, pese a que reset_db() sí corrió create_all() correctamente.

_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
Base.metadata.create_all(bind=_engine)


def _override_get_db():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def _override_get_sync_db_session():
    """Reemplazo de app.db.session.get_sync_db_session para tests.
    app/jobs.py llama a get_sync_db_session() directo (no es un Depends de
    FastAPI, corre dentro de un BackgroundTask) — sin este override, los
    jobs de background en tests terminan escribiendo en la DB real del
    repo (stockbot.db) en vez de la de test en memoria."""
    db = _TestSession()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """
    TestClient with:
    - in-memory SQLite overriding get_db
    - lifespan startup (Redis + scheduler) patched out
    - app.jobs.get_sync_db_session patched so BackgroundTasks (análisis,
      revisión de posición) también usan la DB de test, no la real
    """
    from app.main import app
    app.dependency_overrides[get_db] = _override_get_db

    with patch("app.main.init_rate_limiter", new_callable=AsyncMock), \
         patch("app.main.scheduler"), \
         patch("app.jobs.get_sync_db_session", _override_get_sync_db_session):
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
        analysis_date=datetime.utcnow(),
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
    """POST /api/analysis/{ticker} encola un AnalysisJob y devuelve 202 de
    inmediato — no bloquea esperando el pipeline (ver app/jobs.py). Bajo
    TestClient, BackgroundTasks corre de forma síncrona antes de que
    client.post() retorne, así que para el momento en que llega la
    respuesta el job ya está en su estado terminal (done/failed) y se
    puede verificar directo vía GET /api/jobs/{job_id}."""

    def test_queues_job_and_returns_202(self, client):
        mock_sug = _make_suggestion()
        with patch("app.agents.workflow.analyze_ticker", new_callable=AsyncMock, return_value=mock_sug):
            r = client.post("/api/analysis/AAPL", params={"market": "US"})
        assert r.status_code == 202
        body = r.json()
        assert "job_id" in body
        assert body["status"] in ("queued", "running", "done")

    def test_ticker_normalized(self, client):
        mock_sug = _make_suggestion(ticker="MSFT", company_name="Microsoft")
        with patch("app.agents.workflow.analyze_ticker", new_callable=AsyncMock, return_value=mock_sug):
            r = client.post("/api/analysis/msft")
        job_id = r.json()["job_id"]
        job = client.get(f"/api/jobs/{job_id}").json()
        assert job["ticker"] == "MSFT"

    def test_duplicate_request_returns_existing_job(self, client):
        """Si ya hay un job queued/running para el mismo ticker, no se
        encola uno nuevo — se devuelve el existente (find_active_job)."""
        from app.db.crud import create_job
        db = _TestSession()
        existing = create_job(db, job_type="analysis", ticker="AAPL", market="US")
        db.close()

        r = client.post("/api/analysis/AAPL", params={"market": "US"})
        assert r.status_code == 202
        assert r.json()["job_id"] == existing.id

    def test_analysis_failure_marks_job_failed(self, client):
        with patch("app.agents.workflow.analyze_ticker", new_callable=AsyncMock,
                   side_effect=RuntimeError("LLM unavailable")):
            r = client.post("/api/analysis/AAPL")
        job_id = r.json()["job_id"]
        job = client.get(f"/api/jobs/{job_id}").json()
        assert job["status"] == "failed"
        assert "LLM unavailable" in job["error"]

    def test_response_has_disclaimer(self, client):
        mock_sug = _make_suggestion()
        with patch("app.agents.workflow.analyze_ticker", new_callable=AsyncMock, return_value=mock_sug):
            r = client.post("/api/analysis/AAPL")
        job = client.get(f"/api/jobs/{r.json()['job_id']}").json()
        assert "Not financial advice" in job["result"]["disclaimer"]

    def test_response_has_llm_model(self, client):
        mock_sug = _make_suggestion(llm_model_used="groq/llama-3.3-70b-versatile")
        with patch("app.agents.workflow.analyze_ticker", new_callable=AsyncMock, return_value=mock_sug):
            r = client.post("/api/analysis/AAPL")
        job = client.get(f"/api/jobs/{r.json()['job_id']}").json()
        llm = job["result"]["llm_model_used"]
        assert llm and llm not in ("unknown", "pending")

    def test_response_has_data_sources(self, client):
        mock_sug = _make_suggestion(data_sources=["yfinance", "finnhub"])
        with patch("app.agents.workflow.analyze_ticker", new_callable=AsyncMock, return_value=mock_sug):
            r = client.post("/api/analysis/AAPL")
        job = client.get(f"/api/jobs/{r.json()['job_id']}").json()
        assert len(job["result"]["data_sources"]) > 0

    def test_confidence_in_range(self, client):
        mock_sug = _make_suggestion(confidence=0.72)
        with patch("app.agents.workflow.analyze_ticker", new_callable=AsyncMock, return_value=mock_sug):
            r = client.post("/api/analysis/AAPL")
        job = client.get(f"/api/jobs/{r.json()['job_id']}").json()
        conf = job["result"]["confidence"]
        assert 0.0 <= conf <= 1.0


# ── Positions ─────────────────────────────────────────────────────────────────

class TestPositions:
    def _seed_company(self, ticker="AAPL", market="US"):
        from app.db.crud import get_or_create_company
        db = _TestSession()
        get_or_create_company(db, ticker, "Apple Inc.", market)
        db.close()

    def test_add_requires_ticker_in_watchlist(self, client):
        r = client.post("/api/positions/", json={
            "ticker": "AAPL", "market": "US",
            "purchase_date": "2026-01-15", "purchase_price": 150.0, "quantity": 10,
        })
        assert r.status_code == 400
        assert "watchlist" in r.json()["detail"]

    def test_add_position_success(self, client):
        self._seed_company()
        r = client.post("/api/positions/", json={
            "ticker": "aapl", "market": "US",
            "purchase_date": "2026-01-15", "purchase_price": 150.0, "quantity": 10,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["ticker"] == "AAPL"
        assert body["purchase_price"] == 150.0
        assert body["active"] is True

    def test_add_rejects_non_positive_price(self, client):
        self._seed_company()
        r = client.post("/api/positions/", json={
            "ticker": "AAPL", "market": "US",
            "purchase_date": "2026-01-15", "purchase_price": 0, "quantity": 10,
        })
        assert r.status_code == 422

    def test_list_only_active_by_default(self, client):
        self._seed_company()
        r = client.post("/api/positions/", json={
            "ticker": "AAPL", "market": "US",
            "purchase_date": "2026-01-15", "purchase_price": 150.0, "quantity": 10,
        })
        pid = r.json()["id"]
        client.delete(f"/api/positions/{pid}")  # soft close

        active = client.get("/api/positions/").json()
        assert all(p["id"] != pid for p in active)

        all_positions = client.get("/api/positions/", params={"active_only": False}).json()
        assert any(p["id"] == pid for p in all_positions)

    def test_close_marks_inactive_not_deleted(self, client):
        self._seed_company()
        pid = client.post("/api/positions/", json={
            "ticker": "AAPL", "market": "US",
            "purchase_date": "2026-01-15", "purchase_price": 150.0, "quantity": 10,
        }).json()["id"]

        r = client.delete(f"/api/positions/{pid}")
        assert r.status_code == 200

        all_positions = client.get("/api/positions/", params={"active_only": False}).json()
        closed = next(p for p in all_positions if p["id"] == pid)
        assert closed["active"] is False
        assert closed["closed_at"] is not None

    def test_hard_delete_removes_row(self, client):
        self._seed_company()
        pid = client.post("/api/positions/", json={
            "ticker": "AAPL", "market": "US",
            "purchase_date": "2026-01-15", "purchase_price": 150.0, "quantity": 10,
        }).json()["id"]

        r = client.delete(f"/api/positions/{pid}", params={"hard": True})
        assert r.status_code == 200

        all_positions = client.get("/api/positions/", params={"active_only": False}).json()
        assert all(p["id"] != pid for p in all_positions)

    def test_remove_nonexistent_returns_404(self, client):
        r = client.delete("/api/positions/9999")
        assert r.status_code == 404


class TestPositionReview:
    """POST /api/positions/{id}/review también encola un job (igual
    patrón que /api/analysis/{ticker}) — mockea review_position, no
    analyze_ticker, porque la posición reusa analyze_ticker internamente
    pero eso ya está cubierto por TestAnalysis."""

    def _seed_position(self, client, ticker="AAPL", price=150.0):
        from app.db.crud import get_or_create_company
        db = _TestSession()
        get_or_create_company(db, ticker, "Apple Inc.", "US")
        db.close()
        r = client.post("/api/positions/", json={
            "ticker": ticker, "market": "US",
            "purchase_date": "2026-01-15", "purchase_price": price, "quantity": 10,
        })
        return r.json()["id"]

    def test_review_nonexistent_position_404(self, client):
        r = client.post("/api/positions/9999/review")
        assert r.status_code == 404

    def test_review_queues_and_completes(self, client):
        pid = self._seed_position(client)
        mock_result = {
            "ticker": "AAPL", "purchase_date": "2026-01-15", "purchase_price": 150.0,
            "quantity": 10, "current_price": 165.0, "holding_period_days": 30,
            "unrealized_pnl_pct": 10.0, "recommendation": "HOLD", "confidence": 0.7,
            "reasoning": "La tesis sigue intacta", "key_factors": ["Crecimiento estable"],
            "fresh_signal": "BUY", "fresh_confidence": 0.75, "reviewed_at": "2026-02-14T00:00:00",
        }
        with patch("app.agents.position_agent.review_position", new_callable=AsyncMock,
                   return_value=mock_result):
            r = client.post(f"/api/positions/{pid}/review")
        assert r.status_code == 202
        job_id = r.json()["job_id"]

        job = client.get(f"/api/jobs/{job_id}").json()
        assert job["status"] == "done"
        assert job["result"]["recommendation"] == "HOLD"
        assert job["result"]["unrealized_pnl_pct"] == 10.0

    def test_review_failure_marks_job_failed(self, client):
        pid = self._seed_position(client)
        with patch("app.agents.position_agent.review_position", new_callable=AsyncMock,
                   side_effect=RuntimeError("FreeToken unavailable")):
            r = client.post(f"/api/positions/{pid}/review")
        job = client.get(f"/api/jobs/{r.json()['job_id']}").json()
        assert job["status"] == "failed"
        assert "FreeToken unavailable" in job["error"]

    def test_review_duplicate_returns_existing_job(self, client):
        pid = self._seed_position(client)
        from app.db.crud import create_job
        db = _TestSession()
        existing = create_job(db, job_type="position_review", ticker="AAPL", position_id=pid)
        db.close()

        r = client.post(f"/api/positions/{pid}/review")
        assert r.status_code == 202
        assert r.json()["job_id"] == existing.id


# ── Jobs ──────────────────────────────────────────────────────────────────────

class TestJobs:
    def test_get_nonexistent_job_404(self, client):
        r = client.get("/api/jobs/9999")
        assert r.status_code == 404

    def test_get_job_returns_full_record(self, client):
        mock_sug = _make_suggestion()
        with patch("app.agents.workflow.analyze_ticker", new_callable=AsyncMock, return_value=mock_sug):
            job_id = client.post("/api/analysis/AAPL").json()["job_id"]

        job = client.get(f"/api/jobs/{job_id}").json()
        assert job["job_type"] == "analysis"
        assert job["ticker"] == "AAPL"
        assert job["started_at"] is not None
        assert job["finished_at"] is not None

    def test_list_filters_by_status(self, client):
        with patch("app.agents.workflow.analyze_ticker", new_callable=AsyncMock, return_value=_make_suggestion()):
            client.post("/api/analysis/AAPL")
        with patch("app.agents.workflow.analyze_ticker", new_callable=AsyncMock,
                   side_effect=RuntimeError("boom")):
            client.post("/api/analysis/MSFT")

        done = client.get("/api/jobs/", params={"status": "done"}).json()
        failed = client.get("/api/jobs/", params={"status": "failed"}).json()
        assert all(j["status"] == "done" for j in done)
        assert all(j["status"] == "failed" for j in failed)
        assert any(j["ticker"] == "AAPL" for j in done)
        assert any(j["ticker"] == "MSFT" for j in failed)
