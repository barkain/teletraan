from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_sec_filings_adapter_normalizes_recent_filings(monkeypatch: pytest.MonkeyPatch):
    from data.adapters.sec_filings import get_sec_filings_adapter

    adapter = get_sec_filings_adapter()
    adapter._ticker_map = {
        "AAPL": {"cik": "0000320193", "company_name": "Apple Inc."}
    }

    async def fake_fetch_json(url: str, params=None):
        if "submissions/CIK0000320193.json" in url:
            return {
                "filings": {
                    "recent": {
                        "form": ["8-K", "4", "10-Q", "13D"],
                        "filingDate": ["2026-04-28", "2026-04-20", "2026-04-01", "2026-03-15"],
                        "accessionNumber": [
                            "0000320193-26-000010",
                            "0000320193-26-000011",
                            "0000320193-26-000012",
                            "0000320193-26-000013",
                        ],
                        "primaryDocument": ["a8k.htm", "xslF345X05/wk-form4_1745862403.xml", "a10q.htm", "sc13d.htm"],
                    }
                }
            }
        if "company_tickers.json" in url:
            return {"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."}}
        return None

    monkeypatch.setattr(adapter, "_fetch_json", fake_fetch_json)

    signal = await adapter.get_symbol_signal("AAPL", days=60, limit_per_symbol=10)

    assert signal.symbol == "AAPL"
    assert signal.cik == "0000320193"
    assert signal.recent_filing_count == 4
    assert signal.recent_8k_count == 1
    assert signal.insider_activity_count == 1
    assert signal.activism_count == 1
    assert signal.periodic_report_count == 1
    assert signal.signal_score > 0
    assert signal.filings[0].filing_url.startswith("https://www.sec.gov/Archives/edgar/data/")


@pytest.mark.asyncio
async def test_sec_filings_get_symbol_signals_returns_mapping(monkeypatch: pytest.MonkeyPatch):
    from data.adapters.sec_filings import get_sec_filings_adapter

    adapter = get_sec_filings_adapter()

    async def fake_symbol_signal(symbol: str, **kwargs):
        from data.adapters.sec_filings import SECFilingSignal

        return SECFilingSignal(
            symbol=symbol,
            company_name=symbol,
            cik="0000000000",
            as_of="2026-04-29T00:00:00+00:00",
            signal_score=12.0,
            recent_filing_count=1,
            recent_8k_count=1,
            insider_activity_count=0,
            activism_count=0,
            periodic_report_count=0,
            days_since_last_filing=1,
        )

    monkeypatch.setattr(adapter, "get_symbol_signal", fake_symbol_signal)

    signals = await adapter.get_symbol_signals(["AAPL", "MSFT"])

    assert set(signals) == {"AAPL", "MSFT"}
    assert signals["AAPL"]["signal_score"] == 12.0
