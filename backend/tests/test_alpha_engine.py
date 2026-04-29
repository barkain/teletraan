from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


def _series(start: float, end: float, points: int = 61) -> list[dict[str, float]]:
    step = (end - start) / max(points - 1, 1)
    return [{"close": start + step * i} for i in range(points)]


@pytest.mark.asyncio
async def test_build_market_universe_includes_active_and_portfolio_symbols(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    from models.portfolio import Portfolio, PortfolioHolding
    from models.stock import Stock
    from analysis import alpha_engine as ae

    stock_a = Stock(symbol="AAPL", name="Apple", sector="Technology", is_active=True)
    stock_b = Stock(symbol="MSFT", name="Microsoft", sector="Technology", is_active=True)
    portfolio = Portfolio(name="Test Portfolio")
    db_session.add_all([stock_a, stock_b, portfolio])
    await db_session.flush()
    db_session.add(PortfolioHolding(portfolio_id=portfolio.id, symbol="AAPL", shares=5, cost_basis=100))
    await db_session.commit()

    async def fake_universe():
        return {"Technology": ["AAPL", "NVDA"], "Commodities": ["GC=F"]}

    monkeypatch.setattr(ae, "get_screening_universe", fake_universe)

    universe = await ae.build_market_universe(db_session)

    assert "AAPL" in universe.all_symbols
    assert "MSFT" in universe.all_symbols
    assert "GC=F" in universe.all_symbols
    assert "SPY" in universe.all_symbols
    assert universe.portfolio_symbols == ["AAPL"]
    assert universe.active_stock_symbols == ["AAPL", "MSFT"]


@pytest.mark.asyncio
async def test_detect_market_regime_prefers_risk_on_growth(monkeypatch: pytest.MonkeyPatch):
    from analysis import alpha_engine as ae

    async def fake_fetch_price_history(symbol: str, period: str = "3mo"):
        if symbol == "SPY":
            return _series(100, 105)
        if symbol == "QQQ":
            return _series(100, 112)
        if symbol == "IWM":
            return _series(100, 103)
        if symbol == "^VIX":
            return _series(15, 14)
        # Positive sector breadth
        if symbol in {"XLK", "XLC", "XLY", "XLI", "XLF", "XLE"}:
            return _series(100, 108)
        return _series(100, 101)

    async def fake_macro_snapshot():
        return {"yield_curve_10y2y": -0.25}

    monkeypatch.setattr(ae, "_fetch_price_history", fake_fetch_price_history)
    monkeypatch.setattr(ae, "_fetch_macro_snapshot", fake_macro_snapshot)

    regime = await ae.detect_market_regime()

    assert regime.name == "risk_on_growth"
    assert regime.confidence >= 0.7
    assert any("SPY 20d trend" in item for item in regime.evidence)
    assert regime.tilts["favor"]
