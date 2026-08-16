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


def _chain_rows(count: int, base_volume: int, base_oi: int, prefix: str) -> list[dict]:
    """Strikes in ascending order, with the heavy volume at the HIGH strikes.

    That ordering is the point: `frame.head(12)` sampled the lowest strikes, so
    everything below index 12 was invisible to the totals.
    """
    return [
        {
            "volume": base_volume * (i + 1),
            "openInterest": base_oi * (i + 1),
            "impliedVolatility": 0.30,
            "strike": 100.0 + i,
            "contractSymbol": f"{prefix}{i}",
        }
        for i in range(count)
    ]


@pytest.mark.asyncio
async def test_options_flow_totals_cover_the_whole_chain(monkeypatch: pytest.MonkeyPatch):
    """Totals must come from every strike, not the first twelve.

    Measured on AAPL, the truncated version reported a call/put volume ratio of
    1.02 against a true 2.52 and turned it into a bullish signal_score of 72.36.
    """
    from data.adapters import options_flow as of

    call_rows = _chain_rows(20, base_volume=10, base_oi=100, prefix="C")
    put_rows = _chain_rows(20, base_volume=5, base_oi=50, prefix="P")
    # A NaN row: yfinance emits these for untraded strikes, and they are common
    # once we read past the first twelve.
    put_rows.append(
        {
            "volume": float("nan"),
            "openInterest": float("nan"),
            "impliedVolatility": float("nan"),
            "strike": 121.0,
            "contractSymbol": "PNAN",
        }
    )

    expected_call_volume = sum(row["volume"] for row in call_rows)
    expected_put_volume = sum(row["volume"] for row in put_rows[:-1])
    expected_call_oi = sum(row["openInterest"] for row in call_rows)
    expected_put_oi = sum(row["openInterest"] for row in put_rows[:-1])

    class FakeChain:
        def __init__(self):
            self.calls = _FakeFrame(call_rows)
            self.puts = _FakeFrame(put_rows)

    class FakeTicker:
        @property
        def options(self):
            return ["2026-05-15"]

        def option_chain(self, expiry):
            return FakeChain()

    monkeypatch.setattr(of.yf, "Ticker", lambda symbol: FakeTicker())

    adapter = of.get_options_flow_adapter()
    adapter._cache.clear()
    signal = await adapter.get_symbol_flow("FULLCHN", expirations=1)

    assert signal.available is True
    assert signal.call_volume == expected_call_volume
    assert signal.put_volume == expected_put_volume
    assert signal.call_open_interest == expected_call_oi
    assert signal.put_open_interest == expected_put_oi
    assert signal.contracts_parsed == len(call_rows) + len(put_rows)
    # head(12) would have stopped at strike 111 on each side.
    assert signal.call_volume > sum(row["volume"] for row in call_rows[:12])


@pytest.mark.asyncio
async def test_options_flow_unavailable_when_every_chain_fails(monkeypatch: pytest.MonkeyPatch):
    """A chain we could not read is not a balanced chain.

    `available=bool(expiries)` stayed True after every `option_chain()` call
    raised, and the zero totals fell through to the neutral `50.0 + ...` score.
    """
    from data.adapters import options_flow as of

    class FakeTicker:
        @property
        def options(self):
            return ["2026-05-15", "2026-06-19"]

        def option_chain(self, expiry):
            raise RuntimeError("chain fetch failed")

    monkeypatch.setattr(of.yf, "Ticker", lambda symbol: FakeTicker())

    adapter = of.get_options_flow_adapter()
    adapter._cache.clear()
    signal = await adapter.get_symbol_flow("NOCHAIN")

    assert signal.available is False
    assert signal.status == "error"
    assert signal.coverage == 0.0
    assert signal.signal_score == 0.0
    assert signal.sentiment == "unknown"
    assert signal.contracts_parsed == 0
    assert signal.chains_failed == 2


@pytest.mark.asyncio
async def test_options_flow_adapter_ignores_non_equity_symbols(monkeypatch: pytest.MonkeyPatch):
    from data.adapters import options_flow as of

    adapter = of.get_options_flow_adapter()
    signal = await adapter.get_symbol_flow("^VIX")

    assert signal.available is False
    assert signal.signal_score == 0
    assert signal.notes == ["non_equity_symbol"]
