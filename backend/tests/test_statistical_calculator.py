"""Statistical features must describe recent history, and must fail visibly.

Two defects here were invisible to the suite because a broad per-symbol
`except Exception` swallowed them while orchestration still logged success:

1. `_get_price_data()` ordered ASCENDING then applied `LIMIT 300`, so any symbol
   with more than 300 bars had every feature computed from its OLDEST 300
   observations and stamped with today's calculation date.
2. `_compute_seasonality_features()` raised `AttributeError: 'numpy.ndarray'
   object has no attribute 'values'` on any ordinary DataFrame, so seasonality
   contributed nothing -- observed live for 4 of 5 symbols in a real run.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.statistical_calculator import StatisticalFeatureCalculator
from models.price import PriceHistory
from models.stock import Stock


def _business_days(count: int, end: date) -> list[date]:
    days: list[date] = []
    cursor = end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(days)


def _frame(rows: int, *, end: date = date(2026, 4, 30), start_price: float = 100.0):
    """An ordinary OHLCV frame: a `date` column and a drifting close."""
    days = _business_days(rows, end)
    closes = [start_price + i * 0.5 for i in range(rows)]
    return pd.DataFrame(
        {
            "date": days,
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000 + i * 1_000 for i in range(rows)],
        }
    )


class TestSeasonalityFeatures:
    """Pre-fix every one of these raised AttributeError on `.values`."""

    @pytest.mark.asyncio
    async def test_seasonality_computes_on_an_ordinary_dataframe(self):
        calc = StatisticalFeatureCalculator(db_session=None)  # type: ignore[arg-type]
        calculation_date = date(2026, 4, 30)  # a Thursday

        features = await calc._compute_seasonality_features(
            "ABCD", _frame(120), calculation_date
        )

        kinds = {f.feature_type for f in features}
        assert kinds, "seasonality produced nothing for a normal frame"
        assert all(f.symbol == "ABCD" for f in features)
        assert all(f.calculation_date == calculation_date for f in features)

    @pytest.mark.asyncio
    async def test_day_of_week_effect_only_samples_that_weekday(self):
        calc = StatisticalFeatureCalculator(db_session=None)  # type: ignore[arg-type]
        calculation_date = date(2026, 4, 30)  # Thursday
        frame = _frame(200)

        features = await calc._compute_seasonality_features(
            "ABCD", frame, calculation_date
        )
        dow = next(
            (f for f in features if f.feature_type == "day_of_week_effect"), None
        )
        assert dow is not None, "day-of-week effect missing"

        thursdays = sum(1 for d in frame["date"] if d.weekday() == 3)
        # One return is lost to pct_change; the sample cannot exceed the rest.
        assert dow.metadata_json["sample_count"] <= thursdays
        assert dow.metadata_json["day_of_week"] == 3

    @pytest.mark.asyncio
    async def test_a_nan_close_does_not_desynchronise_dates_from_returns(self):
        """The old code sliced `dates[1:]` against a separately dropna'd return
        series, so one NaN close shifted every later return onto a wrong date."""
        calc = StatisticalFeatureCalculator(db_session=None)  # type: ignore[arg-type]
        frame = _frame(200)
        frame.loc[10, "close"] = float("nan")

        features = await calc._compute_seasonality_features(
            "ABCD", frame, date(2026, 4, 30)
        )
        assert features, "a single NaN close voided the whole family"

    @pytest.mark.asyncio
    async def test_short_history_returns_empty_rather_than_raising(self):
        calc = StatisticalFeatureCalculator(db_session=None)  # type: ignore[arg-type]
        assert await calc._compute_seasonality_features(
            "ABCD", _frame(10), date(2026, 4, 30)
        ) == []


class TestPriceWindowSelection:
    @pytest.mark.asyncio
    async def test_the_newest_bars_are_selected_not_the_oldest(
        self, db_session: AsyncSession
    ):
        stock = Stock(symbol="ABCD", name="Test Co", sector="Technology")
        db_session.add(stock)
        await db_session.flush()

        # 400 bars, more than the 300-row window, with a price that only rises.
        days = _business_days(400, date(2026, 4, 30))
        for i, day in enumerate(days):
            db_session.add(
                PriceHistory(
                    stock_id=stock.id, date=day,
                    open=100.0 + i, high=101.0 + i, low=99.0 + i,
                    close=100.0 + i, volume=1_000_000,
                )
            )
        await db_session.commit()

        calc = StatisticalFeatureCalculator(db_session)
        frame = await calc._get_price_data("ABCD", lookback_days=300)

        assert frame is not None
        assert len(frame) == 300
        # Pre-fix: ascending order + LIMIT 300 returned days[0:300], so the
        # newest bar in the frame was 100 sessions stale and the close was 399
        # points too low.
        assert frame["date"].iloc[-1] == days[-1], "window must end at the newest bar"
        assert frame["date"].iloc[0] == days[100], "window must be the newest 300"
        assert frame["close"].iloc[-1] == pytest.approx(100.0 + 399)

    @pytest.mark.asyncio
    async def test_the_frame_is_returned_oldest_first(self, db_session: AsyncSession):
        """pct_change/rolling in every family depend on chronological order."""
        stock = Stock(symbol="WXYZ", name="Test Co", sector="Technology")
        db_session.add(stock)
        await db_session.flush()

        days = _business_days(50, date(2026, 4, 30))
        for i, day in enumerate(days):
            db_session.add(
                PriceHistory(
                    stock_id=stock.id, date=day,
                    open=10.0, high=11.0, low=9.0, close=10.0 + i, volume=1_000,
                )
            )
        await db_session.commit()

        frame = await StatisticalFeatureCalculator(db_session)._get_price_data("WXYZ")
        assert frame is not None
        assert list(frame["date"]) == sorted(frame["date"])


class TestFailureVisibility:
    @pytest.mark.asyncio
    async def test_a_broken_family_is_recorded_instead_of_swallowed(
        self, db_session: AsyncSession, monkeypatch
    ):
        stock = Stock(symbol="EFGH", name="Test Co", sector="Technology")
        db_session.add(stock)
        await db_session.flush()
        for i, day in enumerate(_business_days(120, date(2026, 4, 30))):
            db_session.add(
                PriceHistory(
                    stock_id=stock.id, date=day,
                    open=10.0, high=11.0, low=9.0, close=10.0 + i, volume=1_000,
                )
            )
        await db_session.commit()

        calc = StatisticalFeatureCalculator(db_session)

        async def boom(*_args, **_kwargs):
            raise AttributeError("'numpy.ndarray' object has no attribute 'values'")

        monkeypatch.setattr(calc, "_compute_seasonality_features", boom)

        features = await calc.compute_all_features(["EFGH"])

        # The other three families still ran ...
        assert features
        # ... but the outage is on the record rather than logged as success.
        assert calc.last_run_failures
        assert any(
            symbol == "EFGH" and family == "seasonality"
            for symbol, family, _err in calc.last_run_failures
        )

    @pytest.mark.asyncio
    async def test_a_clean_run_records_no_failures(self, db_session: AsyncSession):
        stock = Stock(symbol="IJKL", name="Test Co", sector="Technology")
        db_session.add(stock)
        await db_session.flush()
        for i, day in enumerate(_business_days(120, date(2026, 4, 30))):
            db_session.add(
                PriceHistory(
                    stock_id=stock.id, date=day,
                    open=10.0, high=11.0, low=9.0, close=10.0 + i * 0.5, volume=1_000,
                )
            )
        await db_session.commit()

        calc = StatisticalFeatureCalculator(db_session)
        await calc.compute_all_features(["IJKL"])

        assert calc.last_run_failures == [], (
            "seasonality raised on every ordinary symbol before this fix"
        )
