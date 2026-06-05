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
async def test_analyst_revisions_adapter_skips_non_equity_symbol():
    from data.adapters.analyst_revisions import get_analyst_revision_adapter

    signal = await get_analyst_revision_adapter().get_symbol_revision("^VIX")

    assert signal.available is False
    assert signal.notes == ["non_equity_symbol"]
