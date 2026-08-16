from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_short_interest_adapter_scores_high_short_interest(monkeypatch: pytest.MonkeyPatch):
    from data.adapters import short_interest as si

    class FakeTicker:
        @property
        def info(self):
            return {
                "sharesShort": 50000000,
                "shortRatio": 8.5,
                "shortPercentOfFloat": 12.4,
                "floatShares": 400000000,
            }

    monkeypatch.setattr(si.yf, "Ticker", lambda symbol: FakeTicker())

    adapter = si.get_short_interest_adapter()
    signal = await adapter.get_symbol_short_interest("AAPL")

    assert signal.symbol == "AAPL"
    assert signal.available is True
    assert signal.short_ratio == 8.5
    assert signal.short_percent_float == 12.4
    assert signal.squeeze_score > 0
    assert signal.sentiment in {"squeeze_setup", "neutral"}


@pytest.mark.asyncio
async def test_short_interest_placeholder_info_is_not_data(monkeypatch: pytest.MonkeyPatch):
    """yfinance's placeholder response must not become a score.

    `{'trailingPegRatio': None}` is what yfinance returns for a symbol it has
    no fundamentals for. `available=bool(info)` called that data, which emitted
    squeeze_score=0.0 with sentiment 'low_short_interest' -- a measured-looking
    verdict on a symbol we know nothing about.
    """
    from data.adapters import short_interest as si

    class FakeTicker:
        @property
        def info(self):
            return {"trailingPegRatio": None}

    monkeypatch.setattr(si.yf, "Ticker", lambda symbol: FakeTicker())

    adapter = si.get_short_interest_adapter()
    adapter._cache.clear()
    signal = await adapter.get_symbol_short_interest("PLCHLDR")

    assert signal.available is False
    assert signal.status == "unavailable"
    assert signal.coverage == 0.0
    assert signal.squeeze_score == 0.0
    assert signal.sentiment == "unknown"
    assert signal.short_ratio is None
    assert signal.short_percent_float is None


@pytest.mark.asyncio
async def test_short_percent_of_float_fraction_is_normalized_to_percent(monkeypatch: pytest.MonkeyPatch):
    """yfinance reports shortPercentOfFloat as a fraction (AAPL = 0.01 = 1%)."""
    from data.adapters import short_interest as si

    class FakeTicker:
        @property
        def info(self):
            return {"shortPercentOfFloat": 0.01, "shortRatio": 1.0}

    monkeypatch.setattr(si.yf, "Ticker", lambda symbol: FakeTicker())

    adapter = si.get_short_interest_adapter()
    adapter._cache.clear()
    signal = await adapter.get_symbol_short_interest("FRACPCT")

    assert signal.available is True
    assert signal.short_percent_float == 1.0  # 1 percentage point, not 0.01
    # 1% of float is far below the 5% threshold, so it contributes nothing.
    assert signal.squeeze_score == 0.0
    assert "short_percent_float=1.00" in signal.notes


@pytest.mark.asyncio
async def test_short_percent_of_float_percent_value_is_left_alone(monkeypatch: pytest.MonkeyPatch):
    """A caller supplying an already-percent value must not be scaled twice."""
    from data.adapters import short_interest as si

    class FakeTicker:
        @property
        def info(self):
            return {"shortPercentOfFloat": 18.0, "shortRatio": 4.0}

    monkeypatch.setattr(si.yf, "Ticker", lambda symbol: FakeTicker())

    adapter = si.get_short_interest_adapter()
    adapter._cache.clear()
    signal = await adapter.get_symbol_short_interest("PCTPCT")

    assert signal.short_percent_float == 18.0
    assert signal.squeeze_score > 0


@pytest.mark.asyncio
async def test_short_interest_adapter_skips_non_equity_symbol():
    from data.adapters.short_interest import get_short_interest_adapter

    signal = await get_short_interest_adapter().get_symbol_short_interest("^VIX")

    assert signal.available is False
    assert signal.notes == ["non_equity_symbol"]
