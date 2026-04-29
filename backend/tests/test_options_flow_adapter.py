from __future__ import annotations

import pytest


class _FakeFrame:
    def __init__(self, rows):
        self._rows = rows
        self.empty = len(rows) == 0

    def head(self, n):
        return self

    def iterrows(self):
        for idx, row in enumerate(self._rows):
            yield idx, row


class _FakeChain:
    def __init__(self):
        self.calls = _FakeFrame(
            [
                {"volume": 120, "openInterest": 300, "impliedVolatility": 0.42, "strike": 200.0, "contractSymbol": "AAPL260515C00200000"},
                {"volume": 30, "openInterest": 80, "impliedVolatility": 0.39, "strike": 205.0, "contractSymbol": "AAPL260515C00205000"},
            ]
        )
        self.puts = _FakeFrame(
            [
                {"volume": 40, "openInterest": 150, "impliedVolatility": 0.43, "strike": 190.0, "contractSymbol": "AAPL260515P00190000"},
            ]
        )


class _FakeTicker:
    @property
    def options(self):
        return ["2026-05-15", "2026-06-19"]

    def option_chain(self, expiry):
        return _FakeChain()


@pytest.mark.asyncio
async def test_options_flow_adapter_scores_call_heavy_flow(monkeypatch: pytest.MonkeyPatch):
    from data.adapters import options_flow as of

    monkeypatch.setattr(of.yf, "Ticker", lambda symbol: _FakeTicker())

    adapter = of.get_options_flow_adapter()
    signal = await adapter.get_symbol_flow("AAPL")

    assert signal.symbol == "AAPL"
    assert signal.available is True
    assert signal.expirations_scanned == 2
    assert signal.call_volume > signal.put_volume
    assert signal.call_put_volume_ratio and signal.call_put_volume_ratio > 1
    assert signal.sentiment in {"bullish", "neutral"}
    assert signal.signal_score >= 50
    assert signal.top_contracts


@pytest.mark.asyncio
async def test_options_flow_adapter_ignores_non_equity_symbols(monkeypatch: pytest.MonkeyPatch):
    from data.adapters import options_flow as of

    adapter = of.get_options_flow_adapter()
    signal = await adapter.get_symbol_flow("^VIX")

    assert signal.available is False
    assert signal.signal_score == 0
    assert signal.notes == ["non_equity_symbol"]
