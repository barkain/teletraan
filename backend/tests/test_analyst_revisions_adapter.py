from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_analyst_revisions_adapter_scores_improving_trends(monkeypatch: pytest.MonkeyPatch):
    from data.adapters import analyst_revisions as ar

    monkeypatch.setattr(ar.finnhub_adapter, "api_key", "test-key")

    async def fake_trends(symbol: str):
        return [
            {"buy": 15, "hold": 5, "sell": 1, "strongBuy": 4, "strongSell": 0},
            {"buy": 12, "hold": 8, "sell": 2, "strongBuy": 3, "strongSell": 1},
        ]

    monkeypatch.setattr(ar.finnhub_adapter, "get_recommendation_trends", fake_trends)

    class FakeTicker:
        @property
        def info(self):
            return {
                "recommendationMean": 1.9,
                "recommendationKey": "buy",
                "targetMeanPrice": 220,
                "currentPrice": 180,
            }

    monkeypatch.setattr(ar.yf, "Ticker", lambda symbol: FakeTicker())

    adapter = ar.get_analyst_revision_adapter()
    signal = await adapter.get_symbol_revision("AAPL")

    assert signal.symbol == "AAPL"
    assert signal.available is True
    assert signal.revision_score > 50
    assert signal.target_upside_pct and signal.target_upside_pct > 0
    assert signal.recommendation_key == "buy"
    assert signal.latest_trend is not None


@pytest.mark.asyncio
async def test_analyst_revisions_placeholder_info_is_not_data(monkeypatch: pytest.MonkeyPatch):
    """No rating, no target, no trend history -> no score at all.

    `available=bool(trends or info)` plus weights summing to 0.85 used to emit
    `available=True, revision_score=42.5` for a symbol with zero analyst
    coverage, which downstream read as a real mildly-bearish signal.
    """
    from data.adapters import analyst_revisions as ar

    monkeypatch.setattr(ar.finnhub_adapter, "api_key", None)

    class FakeTicker:
        @property
        def info(self):
            return {"trailingPegRatio": None}

    monkeypatch.setattr(ar.yf, "Ticker", lambda symbol: FakeTicker())

    adapter = ar.get_analyst_revision_adapter()
    adapter._cache.clear()
    signal = await adapter.get_symbol_revision("NOCOVER")

    assert signal.available is False
    assert signal.status == "unavailable"
    assert signal.coverage == 0.0
    assert signal.revision_score == 0.0
    assert signal.recommendation_key is None
    assert signal.latest_trend is None


@pytest.mark.asyncio
async def test_analyst_revisions_neutral_inputs_score_neutral(monkeypatch: pytest.MonkeyPatch):
    """Genuinely neutral analyst evidence scores 50, not the old 42.5."""
    from data.adapters import analyst_revisions as ar

    monkeypatch.setattr(ar.finnhub_adapter, "api_key", "test-key")

    async def fake_trends(symbol: str):
        # Equal buys and sells in both months: no tilt, no momentum.
        return [
            {"buy": 5, "hold": 4, "sell": 5, "strongBuy": 0, "strongSell": 0},
            {"buy": 5, "hold": 4, "sell": 5, "strongBuy": 0, "strongSell": 0},
        ]

    monkeypatch.setattr(ar.finnhub_adapter, "get_recommendation_trends", fake_trends)

    class FakeTicker:
        @property
        def info(self):
            return {"recommendationMean": 3.0}  # dead-centre hold

    monkeypatch.setattr(ar.yf, "Ticker", lambda symbol: FakeTicker())

    adapter = ar.get_analyst_revision_adapter()
    adapter._cache.clear()
    signal = await adapter.get_symbol_revision("NEUTRAL")

    assert signal.available is True
    assert signal.revision_score == 50.0


@pytest.mark.asyncio
async def test_analyst_revisions_adapter_skips_non_equity_symbol():
    from data.adapters.analyst_revisions import get_analyst_revision_adapter

    signal = await get_analyst_revision_adapter().get_symbol_revision("^VIX")

    assert signal.available is False
    assert signal.notes == ["non_equity_symbol"]
