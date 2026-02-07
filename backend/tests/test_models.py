"""Tests for SQLAlchemy models: Stock, PriceHistory, Insight, DeepInsight, AnalysisTask.

All tests are async and use the ``db_session`` fixture from conftest.py
which provides an in-memory SQLite database with the full schema.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest
from sqlalchemy import select

from models.stock import Stock
from models.price import PriceHistory
from models.insight import Insight, InsightAnnotation
from models.deep_insight import DeepInsight, InsightAction, InsightType
from models.analysis_task import (
    AnalysisTask,
    AnalysisTaskStatus,
    PHASE_PROGRESS,
    PHASE_NAMES,
)


# ---------------------------------------------------------------------------
# Stock model
# ---------------------------------------------------------------------------


class TestStockModel:
    """Tests for the Stock model."""

    async def test_create_stock_basic(self, db_session):
        """A Stock with only required fields can be persisted and read back."""
        stock = Stock(symbol="MSFT", name="Microsoft Corporation")
        db_session.add(stock)
        await db_session.commit()
        await db_session.refresh(stock)

        assert stock.id is not None
        assert stock.symbol == "MSFT"
        assert stock.name == "Microsoft Corporation"
        assert stock.is_active is True  # default

    async def test_create_stock_all_fields(self, db_session, sample_stock_data):
        """A Stock with all optional fields round-trips correctly."""
        stock = Stock(**sample_stock_data)
        db_session.add(stock)
        await db_session.commit()
        await db_session.refresh(stock)

        assert stock.symbol == "AAPL"
        assert stock.name == "Apple Inc."
        assert stock.sector == "Technology"
        assert stock.industry == "Consumer Electronics"
        assert stock.market_cap == 3_000_000_000_000.0
        assert stock.is_active is True

    async def test_stock_nullable_fields(self, db_session):
        """Sector, industry, and market_cap may be None."""
        stock = Stock(symbol="XYZ", name="Unknown Corp")
        db_session.add(stock)
        await db_session.commit()
        await db_session.refresh(stock)

        assert stock.sector is None
        assert stock.industry is None
        assert stock.market_cap is None

    async def test_stock_unique_symbol(self, db_session):
        """Inserting two stocks with the same symbol raises an integrity error."""
        from sqlalchemy.exc import IntegrityError

        db_session.add(Stock(symbol="DUP", name="First"))
        await db_session.commit()

        db_session.add(Stock(symbol="DUP", name="Second"))
        with pytest.raises(IntegrityError):
            await db_session.commit()

    async def test_stock_repr(self, db_session):
        """__repr__ includes symbol and name."""
        stock = Stock(symbol="GOOG", name="Alphabet Inc.")
        assert "GOOG" in repr(stock)
        assert "Alphabet Inc." in repr(stock)

    async def test_stock_relationships_empty(self, db_session):
        """A freshly-created stock has empty relationship lists."""
        stock = Stock(symbol="TSLA", name="Tesla Inc.")
        db_session.add(stock)
        await db_session.commit()
        await db_session.refresh(stock)

        assert stock.price_history == []
        assert stock.technical_indicators == []
        assert stock.insights == []


# ---------------------------------------------------------------------------
# PriceHistory model
# ---------------------------------------------------------------------------


class TestPriceHistoryModel:
    """Tests for the PriceHistory model."""

    async def test_create_price_history(self, db_session, sample_stock):
        """A PriceHistory row is created with correct fields."""
        ph = PriceHistory(
            stock_id=sample_stock.id,
            date=date(2026, 1, 5),
            open=180.0,
            high=185.0,
            low=179.0,
            close=184.0,
            volume=50_000_000,
        )
        db_session.add(ph)
        await db_session.commit()
        await db_session.refresh(ph)

        assert ph.id is not None
        assert ph.stock_id == sample_stock.id
        assert ph.date == date(2026, 1, 5)
        assert ph.open == 180.0
        assert ph.close == 184.0
        assert ph.volume == 50_000_000
        assert ph.adjusted_close is None  # optional

    async def test_price_history_with_adjusted_close(self, db_session, sample_stock):
        """adjusted_close stores a value when provided."""
        ph = PriceHistory(
            stock_id=sample_stock.id,
            date=date(2026, 1, 5),
            open=180.0,
            high=185.0,
            low=179.0,
            close=184.0,
            volume=50_000_000,
            adjusted_close=183.5,
        )
        db_session.add(ph)
        await db_session.commit()
        await db_session.refresh(ph)

        assert ph.adjusted_close == 183.5

    async def test_price_history_stock_relationship(self, db_session, sample_stock_with_prices):
        """Price rows are accessible through the stock.price_history relationship."""
        await db_session.refresh(sample_stock_with_prices)
        assert len(sample_stock_with_prices.price_history) == 5

    async def test_price_history_unique_stock_date(self, db_session, sample_stock):
        """Duplicate (stock_id, date) pair violates the unique constraint."""
        from sqlalchemy.exc import IntegrityError

        for i in range(2):
            db_session.add(
                PriceHistory(
                    stock_id=sample_stock.id,
                    date=date(2026, 2, 1),
                    open=100.0,
                    high=105.0,
                    low=99.0,
                    close=103.0,
                    volume=10_000_000,
                )
            )
        with pytest.raises(IntegrityError):
            await db_session.commit()

    async def test_price_history_repr(self, db_session, sample_stock):
        """__repr__ contains stock_id, date, close."""
        ph = PriceHistory(
            stock_id=sample_stock.id,
            date=date(2026, 3, 1),
            open=100.0,
            high=105.0,
            low=99.0,
            close=103.0,
            volume=10_000_000,
        )
        r = repr(ph)
        assert str(sample_stock.id) in r
        assert "103.0" in r


# ---------------------------------------------------------------------------
# Insight model
# ---------------------------------------------------------------------------


class TestInsightModel:
    """Tests for the Insight model."""

    async def test_create_insight_with_stock(self, db_session, sample_insight):
        """An insight linked to a stock round-trips correctly."""
        assert sample_insight.id is not None
        assert sample_insight.insight_type == "pattern"
        assert sample_insight.title == "Golden Cross Detected"
        assert sample_insight.severity == "info"
        assert sample_insight.confidence == 0.85
        assert sample_insight.is_active is True

    async def test_create_market_wide_insight(self, db_session):
        """An insight with no stock_id represents a market-wide insight."""
        insight = Insight(
            stock_id=None,
            insight_type="sector",
            title="Tech Sector Rotation",
            description="Capital rotating from growth to value sectors",
            severity="warning",
            confidence=0.72,
        )
        db_session.add(insight)
        await db_session.commit()
        await db_session.refresh(insight)

        assert insight.stock_id is None
        assert insight.stock is None
        assert insight.insight_type == "sector"

    async def test_insight_default_severity(self, db_session, sample_stock):
        """severity defaults to 'info' when not explicitly set."""
        insight = Insight(
            stock_id=sample_stock.id,
            insight_type="anomaly",
            title="Volume Spike",
            description="Unusual volume detected",
            confidence=0.6,
        )
        db_session.add(insight)
        await db_session.commit()
        await db_session.refresh(insight)

        assert insight.severity == "info"

    async def test_insight_data_json(self, db_session, sample_stock):
        """data_json stores supporting data as text."""
        insight = Insight(
            stock_id=sample_stock.id,
            insight_type="technical",
            title="RSI Divergence",
            description="Bearish divergence detected on RSI",
            confidence=0.78,
            data_json='{"rsi": 72, "price_trend": "up"}',
        )
        db_session.add(insight)
        await db_session.commit()
        await db_session.refresh(insight)

        assert '"rsi": 72' in insight.data_json

    async def test_insight_expires_at(self, db_session, sample_stock):
        """expires_at can store a future datetime."""
        future = datetime(2026, 12, 31, 23, 59, 59)
        insight = Insight(
            stock_id=sample_stock.id,
            insight_type="pattern",
            title="Temporary Pattern",
            description="Short-lived pattern",
            confidence=0.5,
            expires_at=future,
        )
        db_session.add(insight)
        await db_session.commit()
        await db_session.refresh(insight)

        assert insight.expires_at == future

    async def test_insight_stock_relationship(self, db_session, sample_stock, sample_insight):
        """The insight.stock relationship navigates to the parent stock."""
        await db_session.refresh(sample_insight)
        assert sample_insight.stock.symbol == "AAPL"

    async def test_insight_annotations_relationship(self, db_session, sample_insight):
        """Annotations can be attached to insights and cascade-loaded."""
        ann = InsightAnnotation(
            insight_id=sample_insight.id,
            note="Confirmed by manual review",
        )
        db_session.add(ann)
        await db_session.commit()
        await db_session.refresh(sample_insight)

        assert len(sample_insight.annotations) == 1
        assert sample_insight.annotations[0].note == "Confirmed by manual review"

    async def test_insight_repr(self, db_session, sample_insight):
        """__repr__ includes type and title."""
        r = repr(sample_insight)
        assert "pattern" in r
        assert "Golden Cross Detected" in r


# ---------------------------------------------------------------------------
# InsightAnnotation model
# ---------------------------------------------------------------------------


class TestInsightAnnotationModel:
    """Tests for the InsightAnnotation model."""

    async def test_create_annotation(self, db_session, sample_insight):
        """An annotation stores its note and insight_id."""
        ann = InsightAnnotation(insight_id=sample_insight.id, note="Worth monitoring")
        db_session.add(ann)
        await db_session.commit()
        await db_session.refresh(ann)

        assert ann.id is not None
        assert ann.insight_id == sample_insight.id
        assert ann.note == "Worth monitoring"

    async def test_annotation_repr(self, db_session, sample_insight):
        """__repr__ includes id and insight_id."""
        ann = InsightAnnotation(insight_id=sample_insight.id, note="Test")
        db_session.add(ann)
        await db_session.commit()
        await db_session.refresh(ann)

        r = repr(ann)
        assert str(ann.id) in r
        assert str(sample_insight.id) in r


# ---------------------------------------------------------------------------
# DeepInsight model
# ---------------------------------------------------------------------------


class TestDeepInsightModel:
    """Tests for the DeepInsight model."""

    async def test_create_deep_insight(self, db_session, sample_deep_insight):
        """A DeepInsight row round-trips with all fields."""
        di = sample_deep_insight
        assert di.id is not None
        assert di.insight_type == "opportunity"
        assert di.action == "BUY"
        assert di.title == "NVDA AI Infrastructure Play"
        assert di.primary_symbol == "NVDA"
        assert di.confidence == 0.88
        assert di.time_horizon == "3-6 months"
        assert "AMD" in di.related_symbols
        assert len(di.supporting_evidence) == 2
        assert len(di.risk_factors) == 2

    async def test_deep_insight_trading_levels(self, db_session, sample_deep_insight):
        """Trading level fields (entry_zone, target_price, stop_loss, timeframe)."""
        di = sample_deep_insight
        assert di.entry_zone == "$880-$920"
        assert di.target_price == "$1100 within 6 months"
        assert di.stop_loss == "$780 (-13%)"
        assert di.timeframe == "position"

    async def test_deep_insight_nullable_fields(self, db_session):
        """Optional fields default to None or empty list."""
        di = DeepInsight(
            insight_type="risk",
            action="SELL",
            title="Minimal Insight",
            thesis="Brief thesis.",
            confidence=0.5,
            time_horizon="1 month",
        )
        db_session.add(di)
        await db_session.commit()
        await db_session.refresh(di)

        assert di.primary_symbol is None
        assert di.invalidation_trigger is None
        assert di.historical_precedent is None
        assert di.entry_zone is None
        assert di.target_price is None
        assert di.parent_insight_id is None
        assert di.source_conversation_id is None

    @pytest.mark.skip(reason="async SQLite limitation: lazy-loaded self-referential relationship triggers MissingGreenlet")
    async def test_deep_insight_self_referential_relationship(self, db_session, sample_deep_insight):
        """A child insight can reference a parent insight."""
        child = DeepInsight(
            insight_type="opportunity",
            action="BUY",
            title="Follow-up on NVDA",
            thesis="Continued bullish momentum.",
            confidence=0.82,
            time_horizon="1-3 months",
            parent_insight_id=sample_deep_insight.id,
        )
        db_session.add(child)
        await db_session.commit()
        await db_session.refresh(child)
        await db_session.refresh(sample_deep_insight)

        assert child.parent_insight_id == sample_deep_insight.id
        assert child.parent_insight is not None
        assert child.parent_insight.id == sample_deep_insight.id
        assert any(c.id == child.id for c in sample_deep_insight.child_insights)

    async def test_deep_insight_repr(self, db_session, sample_deep_insight):
        """__repr__ includes type, action, title."""
        r = repr(sample_deep_insight)
        assert "opportunity" in r
        assert "BUY" in r
        assert "NVDA AI Infrastructure Play" in r

    async def test_insight_action_enum(self):
        """InsightAction enum contains the expected members."""
        assert InsightAction.STRONG_BUY.value == "STRONG_BUY"
        assert InsightAction.BUY.value == "BUY"
        assert InsightAction.HOLD.value == "HOLD"
        assert InsightAction.SELL.value == "SELL"
        assert InsightAction.STRONG_SELL.value == "STRONG_SELL"
        assert InsightAction.WATCH.value == "WATCH"

    async def test_insight_type_enum(self):
        """InsightType enum contains the expected members."""
        assert InsightType.OPPORTUNITY.value == "opportunity"
        assert InsightType.RISK.value == "risk"
        assert InsightType.ROTATION.value == "rotation"
        assert InsightType.MACRO.value == "macro"
        assert InsightType.DIVERGENCE.value == "divergence"
        assert InsightType.CORRELATION.value == "correlation"


# ---------------------------------------------------------------------------
# AnalysisTask model
# ---------------------------------------------------------------------------


class TestAnalysisTaskModel:
    """Tests for the AnalysisTask model."""

    async def test_create_analysis_task(self, db_session, sample_analysis_task):
        """An AnalysisTask persists with correct defaults."""
        t = sample_analysis_task
        assert t.id is not None
        assert t.status == AnalysisTaskStatus.PENDING.value
        assert t.progress == 0
        assert t.max_insights == 5
        assert t.deep_dive_count == 7

    async def test_analysis_task_string_id(self, db_session):
        """AnalysisTask uses a string (UUID) primary key."""
        task_id = str(uuid.uuid4())
        task = AnalysisTask(
            id=task_id,
            status=AnalysisTaskStatus.PENDING.value,
            progress=0,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)

        assert task.id == task_id

    async def test_analysis_task_update_status(self, db_session, sample_analysis_task):
        """Task status and progress can be updated."""
        sample_analysis_task.status = AnalysisTaskStatus.MACRO_SCAN.value
        sample_analysis_task.progress = 10
        sample_analysis_task.current_phase = "Scanning macro environment"
        await db_session.commit()
        await db_session.refresh(sample_analysis_task)

        assert sample_analysis_task.status == "macro_scan"
        assert sample_analysis_task.progress == 10

    async def test_analysis_task_completed(self, db_session, sample_analysis_task):
        """Task can be marked completed with results."""
        now = datetime.utcnow()
        sample_analysis_task.status = AnalysisTaskStatus.COMPLETED.value
        sample_analysis_task.progress = 100
        sample_analysis_task.completed_at = now
        sample_analysis_task.result_insight_ids = [1, 2, 3]
        sample_analysis_task.market_regime = "bullish"
        sample_analysis_task.top_sectors = ["Technology", "Healthcare"]
        sample_analysis_task.phases_completed = ["macro_scan", "synthesis"]
        await db_session.commit()
        await db_session.refresh(sample_analysis_task)

        assert sample_analysis_task.status == "completed"
        assert sample_analysis_task.progress == 100
        assert sample_analysis_task.result_insight_ids == [1, 2, 3]
        assert sample_analysis_task.top_sectors == ["Technology", "Healthcare"]

    async def test_analysis_task_failed(self, db_session, sample_analysis_task):
        """Task can be marked failed with an error message."""
        sample_analysis_task.status = AnalysisTaskStatus.FAILED.value
        sample_analysis_task.progress = -1
        sample_analysis_task.error_message = "Connection timeout"
        await db_session.commit()
        await db_session.refresh(sample_analysis_task)

        assert sample_analysis_task.status == "failed"
        assert sample_analysis_task.error_message == "Connection timeout"

    async def test_analysis_task_to_dict(self, db_session, sample_analysis_task):
        """to_dict() returns a dictionary with all expected keys."""
        d = sample_analysis_task.to_dict()

        assert d["id"] == sample_analysis_task.id
        assert d["status"] == AnalysisTaskStatus.PENDING.value
        assert d["progress"] == 0
        assert d["max_insights"] == 5
        assert d["deep_dive_count"] == 7
        assert d["result_insight_ids"] is None
        assert d["error_message"] is None
        assert "started_at" in d
        assert "completed_at" in d
        assert "created_at" in d

    async def test_analysis_task_to_dict_with_dates(self, db_session, sample_analysis_task):
        """to_dict() serialises datetime values as ISO strings."""
        now = datetime.utcnow()
        sample_analysis_task.started_at = now
        sample_analysis_task.completed_at = now
        await db_session.commit()
        await db_session.refresh(sample_analysis_task)

        d = sample_analysis_task.to_dict()
        assert d["started_at"] == now.isoformat()
        assert d["completed_at"] == now.isoformat()

    async def test_analysis_task_repr(self, db_session, sample_analysis_task):
        """__repr__ includes id, status, progress."""
        r = repr(sample_analysis_task)
        assert sample_analysis_task.id in r
        assert "pending" in r


class TestAnalysisTaskStatusEnum:
    """Tests for the AnalysisTaskStatus enum and related mappings."""

    async def test_status_enum_values(self):
        """AnalysisTaskStatus enum has the expected members."""
        assert AnalysisTaskStatus.PENDING.value == "pending"
        assert AnalysisTaskStatus.MACRO_SCAN.value == "macro_scan"
        assert AnalysisTaskStatus.SECTOR_ROTATION.value == "sector_rotation"
        assert AnalysisTaskStatus.OPPORTUNITY_HUNT.value == "opportunity_hunt"
        assert AnalysisTaskStatus.HEATMAP_FETCH.value == "heatmap_fetch"
        assert AnalysisTaskStatus.HEATMAP_ANALYSIS.value == "heatmap_analysis"
        assert AnalysisTaskStatus.DEEP_DIVE.value == "deep_dive"
        assert AnalysisTaskStatus.COVERAGE_EVALUATION.value == "coverage_evaluation"
        assert AnalysisTaskStatus.SYNTHESIS.value == "synthesis"
        assert AnalysisTaskStatus.COMPLETED.value == "completed"
        assert AnalysisTaskStatus.FAILED.value == "failed"
        assert AnalysisTaskStatus.CANCELLED.value == "cancelled"

    async def test_phase_progress_mapping(self):
        """PHASE_PROGRESS maps every status to a numeric progress value."""
        for status in AnalysisTaskStatus:
            assert status in PHASE_PROGRESS

        assert PHASE_PROGRESS[AnalysisTaskStatus.PENDING] == 0
        assert PHASE_PROGRESS[AnalysisTaskStatus.COMPLETED] == 100
        assert PHASE_PROGRESS[AnalysisTaskStatus.FAILED] == -1
        assert PHASE_PROGRESS[AnalysisTaskStatus.CANCELLED] == -1

    async def test_phase_names_mapping(self):
        """PHASE_NAMES maps every status to a human-readable string."""
        for status in AnalysisTaskStatus:
            assert status in PHASE_NAMES
            assert isinstance(PHASE_NAMES[status], str)
            assert len(PHASE_NAMES[status]) > 0

    async def test_status_is_str_enum(self):
        """AnalysisTaskStatus is a str enum so values work in string comparisons."""
        assert AnalysisTaskStatus.PENDING == "pending"
        assert AnalysisTaskStatus.COMPLETED == "completed"


# ---------------------------------------------------------------------------
# TimestampMixin
# ---------------------------------------------------------------------------


class TestTimestampMixin:
    """Tests for the TimestampMixin (created_at, updated_at)."""

    async def test_timestamps_auto_set_on_create(self, db_session):
        """created_at and updated_at are set automatically on insert."""
        stock = Stock(symbol="TS1", name="Timestamp Test 1")
        db_session.add(stock)
        await db_session.commit()
        await db_session.refresh(stock)

        assert stock.created_at is not None
        assert stock.updated_at is not None
        assert isinstance(stock.created_at, datetime)
        assert isinstance(stock.updated_at, datetime)

    async def test_timestamps_on_insight(self, db_session, sample_insight):
        """Timestamp columns are present on Insight (another mixin user)."""
        assert sample_insight.created_at is not None
        assert sample_insight.updated_at is not None

    async def test_timestamps_on_deep_insight(self, db_session, sample_deep_insight):
        """Timestamp columns are present on DeepInsight."""
        assert sample_deep_insight.created_at is not None
        assert sample_deep_insight.updated_at is not None

    async def test_timestamps_on_analysis_task(self, db_session, sample_analysis_task):
        """Timestamp columns are present on AnalysisTask."""
        assert sample_analysis_task.created_at is not None
        assert sample_analysis_task.updated_at is not None


# ---------------------------------------------------------------------------
# Cascade delete behaviour
# ---------------------------------------------------------------------------


class TestCascadeDelete:
    """Tests that cascade delete-orphan is correctly configured."""

    @pytest.mark.skip(reason="async SQLite limitation: cascade deletes require PRAGMA foreign_keys=ON which is not reliably supported in async SQLite")
    async def test_delete_stock_cascades_to_prices(self, db_session, sample_stock_with_prices):
        """Deleting a stock removes associated price history rows."""
        stock_id = sample_stock_with_prices.id
        await db_session.delete(sample_stock_with_prices)
        await db_session.commit()

        result = await db_session.execute(
            select(PriceHistory).where(PriceHistory.stock_id == stock_id)
        )
        assert result.scalars().all() == []

    @pytest.mark.skip(reason="async SQLite limitation: cascade deletes require PRAGMA foreign_keys=ON which is not reliably supported in async SQLite")
    async def test_delete_stock_cascades_to_insights(self, db_session, sample_insight):
        """Deleting a stock removes associated insights."""
        stock = sample_insight.stock
        stock_id = stock.id
        await db_session.delete(stock)
        await db_session.commit()

        result = await db_session.execute(
            select(Insight).where(Insight.stock_id == stock_id)
        )
        assert result.scalars().all() == []

    @pytest.mark.skip(reason="async SQLite limitation: cascade deletes require PRAGMA foreign_keys=ON which is not reliably supported in async SQLite")
    async def test_delete_insight_cascades_to_annotations(self, db_session, sample_insight):
        """Deleting an insight removes associated annotations."""
        ann = InsightAnnotation(insight_id=sample_insight.id, note="Will be deleted")
        db_session.add(ann)
        await db_session.commit()

        insight_id = sample_insight.id
        await db_session.delete(sample_insight)
        await db_session.commit()

        result = await db_session.execute(
            select(InsightAnnotation).where(InsightAnnotation.insight_id == insight_id)
        )
        assert result.scalars().all() == []
