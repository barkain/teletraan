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
async def test_short_interest_adapter_skips_non_equity_symbol():
    from data.adapters.short_interest import get_short_interest_adapter

    signal = await get_short_interest_adapter().get_symbol_short_interest("^VIX")

    assert signal.available is False
    assert signal.notes == ["non_equity_symbol"]
