"""
Tests de los agentes LLM.
Ejecutar: pytest tests/test_agents.py -v
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.llm.schemas import (
    FundamentalSnapshot, SentimentSummary, Signal, RiskLevel,
    StockSuggestion, Timeframe,
)


# ── LLM Client ───────────────────────────────────────────────────────────────

class TestLLMClient:
    def test_get_provider_order_groq_first(self):
        from app.llm.client import LLMClient
        with patch("app.llm.client.settings") as mock_settings:
            mock_settings.primary_llm = "groq"
            mock_settings.fallback_llm = "ollama"
            mock_settings.groq_model = "llama-3.3-70b-versatile"
            mock_settings.gemini_model = "gemini-2.5-flash"
            mock_settings.ollama_model = "qwen2.5:32b"
            client = LLMClient()
            order = client._get_provider_order()
            assert order[0][0] == "groq"

    def test_get_provider_order_long_context_gemini_first(self):
        from app.llm.client import LLMClient
        with patch("app.llm.client.settings") as mock_settings:
            mock_settings.primary_llm = "groq"
            mock_settings.fallback_llm = "ollama"
            mock_settings.groq_model = "llama-3.3-70b-versatile"
            mock_settings.gemini_model = "gemini-2.5-flash"
            mock_settings.ollama_model = "qwen2.5:32b"
            client = LLMClient()
            order = client._get_provider_order(prefer_long_context=True)
            assert order[0][0] == "gemini"

    def test_strip_think_tags(self):
        from app.llm.client import _strip_think_tags
        text = "<think>internal reasoning</think>{\"signal\": \"BUY\"}"
        result = _strip_think_tags(text)
        assert "<think>" not in result
        assert "BUY" in result

    def test_extract_json_from_markdown(self):
        from app.llm.client import _extract_json
        text = "```json\n{\"signal\": \"BUY\"}\n```"
        result = _extract_json(text)
        assert result.strip() == '{"signal": "BUY"}'

    def test_last_provider_defaults_to_unknown(self):
        from app.llm.client import LLMClient
        client = LLMClient()
        assert client.last_provider == "unknown"
        assert client.last_model == "unknown"


# ── Fundamental Agent ─────────────────────────────────────────────────────────

class TestFundamentalAgent:
    @pytest.mark.asyncio
    async def test_fundamental_agent_returns_analysis(self):
        from app.agents.fundamental_agent import run_fundamental_agent, FundamentalAnalysis

        mock_analysis = FundamentalAnalysis(
            pe_assessment="P/E de 28x está en línea con el sector tech",
            revenue_trend="Revenue creciendo 8% YoY últimos 4Q",
            earnings_quality="Beat en 3 de los últimos 4Q",
            balance_strength="Deuda/equity bajo, FCF robusto",
            valuation_verdict="Justo",
            catalysts=["Lanzamiento iOS 19", "Expansión India"],
            risks=["Regulación antimonopolio EU"],
            score=0.72,
        )

        state = {
            "ticker": "AAPL",
            "market": "US",
            "fundamentals": {"pe_ratio": 28.0, "revenue_growth_yoy": 0.08},
            "earnings": [{"quarter_end": "2024-06-30", "eps_estimate": 1.35, "eps_actual": 1.40, "surprise_pct": 3.7}],
            "errors": [],
        }

        with patch("app.agents.fundamental_agent.get_llm_client") as mock_get:
            mock_client = MagicMock()
            mock_client.complete = AsyncMock(return_value=mock_analysis)
            mock_get.return_value = mock_client

            result = await run_fundamental_agent(state)

        assert "fundamental_analysis" in result
        fa = result["fundamental_analysis"]
        assert fa["score"] == 0.72
        assert 0.0 <= fa["score"] <= 1.0, "Score must be in [0, 1]"
        assert "catalysts" in fa
        assert isinstance(fa["catalysts"], list)
        assert "risks" in fa
        assert isinstance(fa["risks"], list)


# ── Aggregator Agent ──────────────────────────────────────────────────────────

class TestAggregatorAgent:
    @pytest.mark.asyncio
    async def test_aggregator_produces_stock_suggestion(self):
        from app.agents.aggregator_agent import run_aggregator_agent, BullCase, BearCase, FinalDecision

        state = {
            "ticker": "AAPL",
            "market": "US",
            "company_name": "Apple Inc.",
            "price_data": [{"close": 195.0, "volume": 50_000_000}],
            "fundamentals": {"pe_ratio": 28.0},
            "sentiment": {"stocktwits_sentiment": "bullish"},
            "fundamental_analysis": {"score": 0.7, "valuation_verdict": "Justo"},
            "technical_analysis": {"score": 0.6, "trend": "alcista", "momentum": "RSI 55"},
            "sentiment_analysis": {"score": 0.65, "overall_sentiment": "bullish"},
            "macro_analysis": {"score": 0.5, "macro_verdict": "Entorno neutral"},
            "peer_analysis": {"peer_verdict": "Atractivo vs peers"},
            "data_sources": ["yfinance", "finnhub"],
            "llm_model_used": "pending",
            "errors": [],
        }

        mock_bull = BullCase(arguments=["Arg1"], bull_summary="Bull summary test", confidence_boost=0.1)
        mock_bear = BearCase(risks=["Risk1"], bear_summary="Bear summary test", confidence_penalty=0.05)
        mock_decision = FinalDecision(
            signal=Signal.BUY,
            confidence=0.72,
            risk_level=RiskLevel.MEDIUM,
            target_price_base=205.0,
            final_reasoning="Buy based on strong fundamentals",
            key_catalysts=["Earnings beat"],
            key_risks=["Macro uncertainty"],
        )

        with patch("app.agents.aggregator_agent.get_llm_client") as mock_get:
            mock_client = MagicMock()
            mock_client.complete = AsyncMock(side_effect=[mock_bull, mock_bear, mock_decision])
            mock_client.last_provider = "groq"
            mock_client.last_model = "llama-3.3-70b-versatile"
            mock_get.return_value = mock_client

            with patch("app.agents.aggregator_agent.save_suggestion"):
                result = await run_aggregator_agent(state)

        assert "suggestion" in result
        sug: StockSuggestion = result["suggestion"]
        assert isinstance(sug, StockSuggestion)

        # Signal must be a valid enum value
        assert sug.signal in (Signal.BUY, Signal.HOLD, Signal.SELL)
        assert sug.ticker == "AAPL"

        # Confidence must be in [0, 1]
        assert 0.0 <= sug.confidence <= 1.0, f"Confidence {sug.confidence} out of range [0, 1]"

        # Disclaimer must always be present (security constraint)
        assert sug.disclaimer, "Disclaimer must not be empty"
        assert "Not financial advice" in sug.disclaimer or "informational" in sug.disclaimer.lower()

        # LLM model must be set by aggregator (not "pending" or "unknown")
        assert sug.llm_model_used, "llm_model_used must not be empty"
        assert sug.llm_model_used != "pending", "llm_model_used must be updated from 'pending'"
        assert sug.llm_model_used != "unknown", "llm_model_used must not be 'unknown'"

        # Data sources must be populated
        assert len(sug.data_sources) > 0, "data_sources must not be empty"

        # Risk level must be set
        assert sug.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH)

    @pytest.mark.asyncio
    async def test_aggregator_confidence_clamped_to_range(self):
        """Aggregator must not produce confidence > 1.0 even if scores are high."""
        from app.agents.aggregator_agent import run_aggregator_agent, BullCase, BearCase, FinalDecision

        state = {
            "ticker": "TSLA",
            "market": "US",
            "company_name": "Tesla Inc.",
            "price_data": [{"close": 300.0, "volume": 80_000_000}],
            "fundamentals": {},
            "sentiment": {},
            "fundamental_analysis": {"score": 0.99},
            "technical_analysis": {"score": 0.99},
            "sentiment_analysis": {"score": 0.99},
            "macro_analysis": {"score": 0.99},
            "peer_analysis": {},
            "data_sources": ["yfinance"],
            "llm_model_used": "pending",
            "errors": [],
        }

        mock_bull = BullCase(arguments=["Max bull"], bull_summary="Extreme bull", confidence_boost=0.5)
        mock_bear = BearCase(risks=["Low risk"], bear_summary="Mild bear", confidence_penalty=0.0)
        mock_decision = FinalDecision(
            signal=Signal.BUY,
            confidence=0.99,
            risk_level=RiskLevel.HIGH,
            target_price_base=400.0,
            final_reasoning="Extreme buy",
            key_catalysts=["Everything"],
            key_risks=[],
        )

        with patch("app.agents.aggregator_agent.get_llm_client") as mock_get:
            mock_client = MagicMock()
            mock_client.complete = AsyncMock(side_effect=[mock_bull, mock_bear, mock_decision])
            mock_client.last_provider = "groq"
            mock_client.last_model = "llama-3.3-70b-versatile"
            mock_get.return_value = mock_client

            with patch("app.agents.aggregator_agent.save_suggestion"):
                result = await run_aggregator_agent(state)

        sug = result["suggestion"]
        assert 0.0 <= sug.confidence <= 1.0, f"Confidence {sug.confidence} exceeds bounds"


# ── Workflow ──────────────────────────────────────────────────────────────────

EXPECTED_NODES = {"fetch_data", "fundamental_agent", "technical_agent", "sentiment_agent",
                  "macro_agent", "validate_analyses", "peer_agent", "aggregator_agent", "save_suggestion"}

FORBIDDEN_NODES = {"execute_trade", "place_order", "buy_order", "sell_order",
                   "trade", "order", "execute", "submit_order"}


class TestWorkflow:
    def test_workflow_compiles(self):
        from app.agents.workflow import build_workflow
        graph = build_workflow()
        compiled = graph.compile()
        assert compiled is not None

    def test_no_trade_execution_node(self):
        """CRITICAL: system must never contain a trade execution node."""
        from app.agents.workflow import build_workflow
        workflow = build_workflow()
        node_names = set(workflow.nodes.keys()) if hasattr(workflow, "nodes") else set()

        # Workflow must actually have nodes (not trivially empty)
        assert len(node_names) > 0, "Workflow has no nodes — graph not built correctly"

        for name in node_names:
            name_lower = name.lower()
            for forbidden in FORBIDDEN_NODES:
                assert forbidden not in name_lower, (
                    f"Trade execution node found: '{name}' — system must be suggestion-only"
                )

    def test_expected_nodes_present(self):
        """All required analysis nodes must exist in the workflow."""
        from app.agents.workflow import build_workflow
        workflow = build_workflow()
        node_names = set(workflow.nodes.keys()) if hasattr(workflow, "nodes") else set()

        for expected in EXPECTED_NODES:
            assert expected in node_names, (
                f"Required node '{expected}' missing from workflow"
            )

    def test_workflow_state_has_disclaimer_field(self):
        """The AnalysisState dict must carry the disclaimer to every downstream node."""
        from app.agents.workflow import AnalysisState
        import typing
        hints = typing.get_type_hints(AnalysisState)
        # StockSuggestion carries the disclaimer; the state holds 'suggestion'
        assert "suggestion" in hints or "disclaimer" in hints, (
            "AnalysisState must have a 'suggestion' field to carry disclaimer"
        )


# ── StockSuggestion contract ─────────────────────────────────────────────────

class TestStockSuggestionContract:
    """Verifies the Pydantic contract enforced by StockSuggestion itself."""

    def _make_suggestion(self, **overrides) -> StockSuggestion:
        defaults = dict(
            ticker="AAPL",
            company_name="Apple Inc.",
            market="US",
            signal=Signal.BUY,
            confidence=0.75,
            risk_level=RiskLevel.MEDIUM,
            current_price=195.0,
            bull_case="Strong fundamentals",
            bear_case="Valuation stretched",
            final_reasoning="Overall positive outlook",
            fundamentals=FundamentalSnapshot(),
            peers=[],
            sentiment=SentimentSummary(),
            llm_model_used="groq/llama-3.3-70b-versatile",
            data_sources=["yfinance", "finnhub"],
        )
        defaults.update(overrides)
        return StockSuggestion(**defaults)

    def test_default_disclaimer_present(self):
        sug = self._make_suggestion()
        assert sug.disclaimer
        assert "Not financial advice" in sug.disclaimer

    def test_confidence_must_be_in_range(self):
        sug = self._make_suggestion(confidence=0.0)
        assert sug.confidence == 0.0
        sug = self._make_suggestion(confidence=1.0)
        assert sug.confidence == 1.0

    def test_confidence_out_of_range_raises(self):
        with pytest.raises(Exception):
            self._make_suggestion(confidence=1.1)
        with pytest.raises(Exception):
            self._make_suggestion(confidence=-0.1)

    def test_signal_is_valid_enum(self):
        for sig in (Signal.BUY, Signal.HOLD, Signal.SELL):
            sug = self._make_suggestion(signal=sig)
            assert sug.signal == sig

    def test_market_is_valid_literal(self):
        for market in ("US", "CRYPTO", "LATAM"):
            sug = self._make_suggestion(market=market)
            assert sug.market == market

    def test_invalid_market_raises(self):
        with pytest.raises(Exception):
            self._make_suggestion(market="INVALID")

    def test_bull_bear_case_max_length(self):
        long_text = "x" * 501
        with pytest.raises(Exception):
            self._make_suggestion(bull_case=long_text)
        with pytest.raises(Exception):
            self._make_suggestion(bear_case=long_text)

    def test_final_reasoning_max_length(self):
        long_text = "x" * 801
        with pytest.raises(Exception):
            self._make_suggestion(final_reasoning=long_text)
