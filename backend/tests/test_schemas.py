"""Tests for Pydantic schemas: validation, serialization, defaults.

These tests are synchronous since Pydantic schema operations do not
require async database access.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

# Stock schemas
from schemas.stock import (
    StockBase,
    StockCreate,
    StockResponse,
    StockListResponse,
    PriceHistoryResponse,
)

# Insight schemas
from schemas.insight import (
    InsightBase,
    InsightResponse,
    InsightListResponse,
    AnnotationCreate,
    AnnotationUpdate,
    AnnotationResponse,
)

# Deep insight schemas
from schemas.deep_insight import (
    DeepInsightBase,
    DeepInsightCreate,
    DeepInsightResponse,
    DeepInsightListResponse,
    AnalystEvidence,
    InsightAction,
    InsightType,
)

# Analysis schemas
from schemas.analysis import (
    IndicatorDetail,
    TechnicalAnalysisResponse,
    PatternDetail,
    AnomalyDetail,
    AnomalyResponse,
    AnalysisRunRequest,
    AnalysisRunResponse,
    AnalysisSummaryResponse,
)

# Base schema
from schemas.base import BaseResponse


# ---------------------------------------------------------------------------
# BaseResponse
# ---------------------------------------------------------------------------


class TestBaseResponse:
    """Tests for the BaseResponse schema."""

    def test_defaults(self):
        resp = BaseResponse()
        assert resp.success is True
        assert resp.message is None

    def test_custom_values(self):
        resp = BaseResponse(success=False, message="Something went wrong")
        assert resp.success is False
        assert resp.message == "Something went wrong"


# ---------------------------------------------------------------------------
# Stock schemas
# ---------------------------------------------------------------------------


class TestStockSchemas:
    """Tests for Stock-related Pydantic schemas."""

    def test_stock_base_valid(self):
        s = StockBase(symbol="AAPL", name="Apple Inc.")
        assert s.symbol == "AAPL"
        assert s.name == "Apple Inc."
        assert s.sector is None
        assert s.industry is None

    def test_stock_base_with_optionals(self):
        s = StockBase(
            symbol="MSFT",
            name="Microsoft",
            sector="Technology",
            industry="Software",
        )
        assert s.sector == "Technology"
        assert s.industry == "Software"

    def test_stock_base_missing_required(self):
        with pytest.raises(ValidationError):
            StockBase(symbol="AAPL")  # missing name

    def test_stock_create_inherits_base(self):
        sc = StockCreate(symbol="GOOG", name="Alphabet Inc.")
        assert sc.symbol == "GOOG"
        assert sc.name == "Alphabet Inc."

    def test_stock_response_from_attributes(self):
        """StockResponse can be constructed via model_validate with from_attributes."""

        class FakeORM:
            id = 1
            symbol = "AAPL"
            name = "Apple Inc."
            sector = "Technology"
            industry = "Consumer Electronics"
            market_cap = 3e12
            is_active = True
            created_at = datetime(2026, 1, 1, 12, 0, 0)

        resp = StockResponse.model_validate(FakeORM(), from_attributes=True)
        assert resp.id == 1
        assert resp.symbol == "AAPL"
        assert resp.is_active is True
        assert resp.created_at == datetime(2026, 1, 1, 12, 0, 0)

    def test_stock_response_defaults(self):
        resp = StockResponse(
            id=1,
            symbol="XYZ",
            name="Unknown",
            is_active=False,
            created_at=datetime(2026, 1, 1),
        )
        assert resp.market_cap is None
        assert resp.sector is None

    def test_stock_list_response(self):
        items = [
            StockResponse(
                id=i,
                symbol=f"S{i}",
                name=f"Stock {i}",
                is_active=True,
                created_at=datetime(2026, 1, 1),
            )
            for i in range(3)
        ]
        lst = StockListResponse(stocks=items, total=3)
        assert lst.total == 3
        assert len(lst.stocks) == 3

    def test_price_history_response_valid(self):
        p = PriceHistoryResponse(
            date=date(2026, 1, 5),
            open=180.0,
            high=185.0,
            low=179.0,
            close=184.0,
            volume=50_000_000,
        )
        assert p.date == date(2026, 1, 5)
        assert p.adjusted_close is None

    def test_price_history_response_with_adjusted_close(self):
        p = PriceHistoryResponse(
            date=date(2026, 1, 5),
            open=180.0,
            high=185.0,
            low=179.0,
            close=184.0,
            volume=50_000_000,
            adjusted_close=183.5,
        )
        assert p.adjusted_close == 183.5

    def test_price_history_missing_required(self):
        with pytest.raises(ValidationError):
            PriceHistoryResponse(
                date=date(2026, 1, 5),
                open=180.0,
                high=185.0,
                # missing low, close, volume
            )


# ---------------------------------------------------------------------------
# Insight schemas
# ---------------------------------------------------------------------------


class TestInsightSchemas:
    """Tests for Insight-related Pydantic schemas."""

    def test_insight_base_valid(self):
        i = InsightBase(
            insight_type="pattern",
            title="Golden Cross",
            description="50-day SMA crossed above 200-day SMA",
            severity="info",
            confidence=0.85,
        )
        assert i.insight_type == "pattern"
        assert i.confidence == 0.85

    def test_insight_base_missing_fields(self):
        with pytest.raises(ValidationError):
            InsightBase(
                insight_type="pattern",
                title="Missing Description",
                severity="info",
                confidence=0.5,
                # missing description
            )

    def test_insight_response_from_attributes(self):
        class FakeORM:
            id = 10
            stock_id = 1
            insight_type = "anomaly"
            title = "Volume Spike"
            description = "Unusual trading volume"
            severity = "warning"
            confidence = 0.72
            is_active = True
            created_at = datetime(2026, 1, 15, 9, 30, 0)
            expires_at = None

        resp = InsightResponse.model_validate(FakeORM(), from_attributes=True)
        assert resp.id == 10
        assert resp.stock_id == 1
        assert resp.is_active is True
        assert resp.expires_at is None

    def test_insight_response_nullable_stock_id(self):
        """Market-wide insights have stock_id=None."""
        resp = InsightResponse(
            id=1,
            stock_id=None,
            insight_type="sector",
            title="Sector Rotation",
            description="Capital moving to value",
            severity="info",
            confidence=0.6,
            is_active=True,
            created_at=datetime(2026, 1, 1),
            expires_at=None,
        )
        assert resp.stock_id is None

    def test_insight_list_response(self):
        items = [
            InsightResponse(
                id=1,
                stock_id=None,
                insight_type="pattern",
                title="Test",
                description="Desc",
                severity="info",
                confidence=0.5,
                is_active=True,
                created_at=datetime(2026, 1, 1),
                expires_at=None,
            )
        ]
        lst = InsightListResponse(insights=items, total=1)
        assert lst.total == 1

    def test_annotation_create(self):
        a = AnnotationCreate(note="This looks interesting")
        assert a.note == "This looks interesting"

    def test_annotation_create_missing_note(self):
        with pytest.raises(ValidationError):
            AnnotationCreate()  # type: ignore[call-arg]

    def test_annotation_update(self):
        a = AnnotationUpdate(note="Updated note")
        assert a.note == "Updated note"

    def test_annotation_response_from_attributes(self):
        class FakeORM:
            id = 5
            insight_id = 10
            note = "Confirmed"
            created_at = datetime(2026, 1, 1)
            updated_at = datetime(2026, 1, 2)

        resp = AnnotationResponse.model_validate(FakeORM(), from_attributes=True)
        assert resp.id == 5
        assert resp.insight_id == 10
        assert resp.updated_at == datetime(2026, 1, 2)

    def test_annotation_response_updated_at_optional(self):
        resp = AnnotationResponse(
            id=1,
            insight_id=2,
            note="Test",
            created_at=datetime(2026, 1, 1),
        )
        assert resp.updated_at is None


# ---------------------------------------------------------------------------
# DeepInsight schemas
# ---------------------------------------------------------------------------


class TestDeepInsightSchemas:
    """Tests for DeepInsight-related Pydantic schemas."""

    @staticmethod
    def _make_base_kwargs(**overrides):
        defaults = {
            "insight_type": InsightType.OPPORTUNITY,
            "action": InsightAction.BUY,
            "title": "Test Insight",
            "thesis": "Test thesis.",
            "confidence": 0.8,
            "time_horizon": "3 months",
        }
        defaults.update(overrides)
        return defaults

    def test_deep_insight_base_valid(self):
        di = DeepInsightBase(**self._make_base_kwargs())
        assert di.insight_type == InsightType.OPPORTUNITY
        assert di.action == InsightAction.BUY
        assert di.related_symbols == []
        assert di.risk_factors == []

    def test_deep_insight_base_all_fields(self):
        di = DeepInsightBase(
            **self._make_base_kwargs(
                primary_symbol="NVDA",
                related_symbols=["AMD", "AVGO"],
                supporting_evidence=[
                    AnalystEvidence(analyst="technical", finding="Breakout")
                ],
                risk_factors=["Valuation"],
                invalidation_trigger="Below $780",
                historical_precedent="Similar to 2020 rally",
                analysts_involved=["technical", "macro"],
                data_sources=["yfinance"],
            )
        )
        assert di.primary_symbol == "NVDA"
        assert len(di.related_symbols) == 2
        assert len(di.supporting_evidence) == 1

    def test_deep_insight_base_missing_required(self):
        with pytest.raises(ValidationError):
            DeepInsightBase(
                insight_type=InsightType.OPPORTUNITY,
                action=InsightAction.BUY,
                # missing title, thesis, confidence, time_horizon
            )

    def test_deep_insight_base_confidence_too_high(self):
        """Confidence above 1.0 is rejected."""
        with pytest.raises(ValidationError):
            DeepInsightBase(**self._make_base_kwargs(confidence=1.5))

    def test_deep_insight_base_confidence_too_low(self):
        """Confidence below 0.0 is rejected."""
        with pytest.raises(ValidationError):
            DeepInsightBase(**self._make_base_kwargs(confidence=-0.1))

    def test_deep_insight_base_confidence_edge_values(self):
        """Confidence at 0.0 and 1.0 are valid."""
        di_zero = DeepInsightBase(**self._make_base_kwargs(confidence=0.0))
        assert di_zero.confidence == 0.0

        di_one = DeepInsightBase(**self._make_base_kwargs(confidence=1.0))
        assert di_one.confidence == 1.0

    def test_deep_insight_create(self):
        dc = DeepInsightCreate(**self._make_base_kwargs())
        assert dc.title == "Test Insight"

    def test_deep_insight_response_from_attributes(self):
        class FakeORM:
            id = 1
            insight_type = "opportunity"
            action = "BUY"
            title = "NVDA Play"
            thesis = "Strong demand"
            primary_symbol = "NVDA"
            related_symbols = ["AMD"]
            supporting_evidence = [{"analyst": "tech", "finding": "breakout"}]
            confidence = 0.88
            time_horizon = "3 months"
            risk_factors = ["valuation"]
            invalidation_trigger = "Below $780"
            historical_precedent = None
            analysts_involved = ["technical"]
            data_sources = ["yfinance"]
            created_at = datetime(2026, 1, 1)
            updated_at = None
            parent_insight_id = None
            source_conversation_id = None
            entry_zone = "$880-$920"
            target_price = "$1100"
            stop_loss = "$780"
            timeframe = "position"
            discovery_context = None

        resp = DeepInsightResponse.model_validate(FakeORM(), from_attributes=True)
        assert resp.id == 1
        assert resp.entry_zone == "$880-$920"
        assert resp.parent_insight_id is None

    def test_deep_insight_response_optional_trading_fields(self):
        resp = DeepInsightResponse(
            id=1,
            insight_type=InsightType.RISK,
            action=InsightAction.SELL,
            title="Risk Alert",
            thesis="Rising rates",
            confidence=0.7,
            time_horizon="1 month",
            created_at=datetime(2026, 1, 1),
        )
        assert resp.entry_zone is None
        assert resp.target_price is None
        assert resp.stop_loss is None
        assert resp.timeframe is None
        assert resp.discovery_context is None

    def test_deep_insight_list_response(self):
        item = DeepInsightResponse(
            id=1,
            insight_type=InsightType.OPPORTUNITY,
            action=InsightAction.BUY,
            title="Test",
            thesis="Test thesis",
            confidence=0.5,
            time_horizon="1 month",
            created_at=datetime(2026, 1, 1),
        )
        lst = DeepInsightListResponse(items=[item], total=1)
        assert lst.total == 1
        assert len(lst.items) == 1

    def test_insight_action_enum(self):
        assert InsightAction.STRONG_BUY == "STRONG_BUY"
        assert InsightAction.WATCH == "WATCH"

    def test_insight_type_enum(self):
        assert InsightType.OPPORTUNITY == "opportunity"
        assert InsightType.CORRELATION == "correlation"

    def test_analyst_evidence_valid(self):
        e = AnalystEvidence(analyst="technical", finding="Golden cross")
        assert e.analyst == "technical"
        assert e.confidence is None

    def test_analyst_evidence_with_confidence(self):
        e = AnalystEvidence(analyst="macro", finding="Rising rates", confidence=0.75)
        assert e.confidence == 0.75


# ---------------------------------------------------------------------------
# Analysis schemas
# ---------------------------------------------------------------------------


class TestAnalysisSchemas:
    """Tests for analysis-related Pydantic schemas."""

    def test_indicator_detail_valid(self):
        ind = IndicatorDetail(
            indicator="RSI_14",
            value=65.0,
            signal="bullish",
            strength=0.7,
        )
        assert ind.indicator == "RSI_14"
        assert ind.strength == 0.7

    def test_indicator_detail_strength_bounds(self):
        """Strength must be between 0.0 and 1.0."""
        with pytest.raises(ValidationError):
            IndicatorDetail(
                indicator="RSI",
                value=50.0,
                signal="neutral",
                strength=1.5,
            )

    def test_technical_analysis_response(self):
        resp = TechnicalAnalysisResponse(
            symbol="AAPL",
            analyzed_at=datetime(2026, 1, 1),
            overall_signal="bullish",
            confidence=0.8,
            bullish_count=5,
            bearish_count=2,
            neutral_count=1,
            indicators=[],
        )
        assert resp.symbol == "AAPL"
        assert resp.crossovers == []  # default

    def test_pattern_detail_valid(self):
        p = PatternDetail(
            pattern_type="head_and_shoulders",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 15),
            confidence=0.75,
            price_target=200.0,
            stop_loss=170.0,
            description="H&S pattern detected",
        )
        assert p.pattern_type == "head_and_shoulders"
        assert p.supporting_data == {}

    def test_pattern_detail_nullable_fields(self):
        p = PatternDetail(
            pattern_type="double_top",
            start_date=None,
            end_date=None,
            confidence=0.5,
            price_target=None,
            stop_loss=None,
            description="Potential double top",
        )
        assert p.start_date is None
        assert p.price_target is None

    def test_anomaly_detail_valid(self):
        a = AnomalyDetail(
            anomaly_type="volume_spike",
            detected_at=datetime(2026, 1, 10, 14, 30),
            severity="warning",
            value=150_000_000.0,
            expected_range=(40_000_000.0, 60_000_000.0),
            z_score=4.5,
            description="Volume 3x above average",
        )
        assert a.anomaly_type == "volume_spike"
        assert a.expected_range == (40_000_000.0, 60_000_000.0)

    def test_anomaly_response(self):
        resp = AnomalyResponse(
            symbol="TSLA",
            analyzed_at=datetime(2026, 1, 1),
            total_anomalies=0,
            anomalies_by_severity={},
            anomalies=[],
        )
        assert resp.total_anomalies == 0

    def test_analysis_run_request_defaults(self):
        req = AnalysisRunRequest()
        assert req.symbols is None

    def test_analysis_run_request_with_symbols(self):
        req = AnalysisRunRequest(symbols=["AAPL", "MSFT"])
        assert req.symbols == ["AAPL", "MSFT"]

    def test_analysis_run_response(self):
        resp = AnalysisRunResponse(
            status="started",
            message="Analysis triggered",
            symbols=["AAPL"],
            started_at=datetime(2026, 1, 1),
        )
        assert resp.status == "started"

    def test_analysis_run_response_all_symbols(self):
        resp = AnalysisRunResponse(
            status="started",
            message="Analysis triggered for all",
            symbols="all",
            started_at=datetime(2026, 1, 1),
        )
        assert resp.symbols == "all"

    def test_analysis_summary_response(self):
        resp = AnalysisSummaryResponse(
            last_run=datetime(2026, 1, 1),
            stocks_analyzed=10,
            patterns_detected=5,
            anomalies_detected=2,
            insights_generated=8,
            patterns_by_type={"golden_cross": 3, "head_and_shoulders": 2},
            anomalies_by_severity={"warning": 1, "alert": 1},
            insights_by_type={"pattern": 5, "anomaly": 3},
        )
        assert resp.stocks_analyzed == 10
        assert resp.patterns_by_type["golden_cross"] == 3

    def test_analysis_summary_response_no_last_run(self):
        resp = AnalysisSummaryResponse(
            last_run=None,
            stocks_analyzed=0,
            patterns_detected=0,
            anomalies_detected=0,
            insights_generated=0,
            patterns_by_type={},
            anomalies_by_severity={},
            insights_by_type={},
        )
        assert resp.last_run is None


# ---------------------------------------------------------------------------
# Schema serialization round-trip
# ---------------------------------------------------------------------------


class TestSchemaSerialization:
    """Ensure model_dump / model_validate round-trips work correctly."""

    def test_stock_response_round_trip(self):
        original = StockResponse(
            id=1,
            symbol="AAPL",
            name="Apple Inc.",
            sector="Technology",
            industry="Consumer Electronics",
            market_cap=3e12,
            is_active=True,
            created_at=datetime(2026, 1, 1),
        )
        data = original.model_dump()
        restored = StockResponse.model_validate(data)
        assert restored == original

    def test_deep_insight_response_round_trip(self):
        original = DeepInsightResponse(
            id=1,
            insight_type=InsightType.OPPORTUNITY,
            action=InsightAction.BUY,
            title="NVDA Play",
            thesis="Strong demand for GPUs",
            confidence=0.88,
            time_horizon="3-6 months",
            primary_symbol="NVDA",
            related_symbols=["AMD"],
            created_at=datetime(2026, 1, 1),
        )
        data = original.model_dump()
        restored = DeepInsightResponse.model_validate(data)
        assert restored.id == original.id
        assert restored.primary_symbol == "NVDA"

    def test_insight_response_json_round_trip(self):
        original = InsightResponse(
            id=1,
            stock_id=5,
            insight_type="pattern",
            title="Test",
            description="Test insight",
            severity="info",
            confidence=0.5,
            is_active=True,
            created_at=datetime(2026, 1, 1),
            expires_at=None,
        )
        json_str = original.model_dump_json()
        restored = InsightResponse.model_validate_json(json_str)
        assert restored == original
