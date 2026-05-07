"""Core utilities for the v2 alpha engine.

This module stays deterministic and lightweight:
- build a market-wide universe
- detect the current market regime
- persist a daily preflight snapshot

It does not rank ideas yet; that comes later.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from analysis.agents.universe_builder import get_screening_universe
from analysis.context_builder import MarketContextBuilder as ContextBuilder
from analysis.alpha_synthesis import synthesize_alpha_run
from analysis.sectors import SECTOR_ETFS
from data.adapters.yahoo import yahoo_adapter
from models.alpha_engine import (
    AnalysisRun,
    AnalysisRunStatus,
    CandidateIdea,
    MarketSnapshot,
    SecuritySignal,
)
from models.portfolio import Portfolio, PortfolioHolding
from models.stock import Stock
from config import get_settings

try:
    from data.adapters.fred import fred_adapter
except Exception:  # pragma: no cover - optional dependency
    fred_adapter = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

NY_TZ = ZoneInfo("America/New_York")
DEFAULT_REGIME_SYMBOLS = ["SPY", "QQQ", "IWM", "^VIX"]


@dataclass
class MarketUniverse:
    """Wide, deduplicated symbol universe for daily scanning."""

    as_of: datetime
    all_symbols: list[str] = field(default_factory=list)
    categories: dict[str, list[str]] = field(default_factory=dict)
    portfolio_symbols: list[str] = field(default_factory=list)
    active_stock_symbols: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "all_symbols": self.all_symbols,
            "categories": self.categories,
            "portfolio_symbols": self.portfolio_symbols,
            "active_stock_symbols": self.active_stock_symbols,
            "total_symbols": len(self.all_symbols),
        }


@dataclass
class MarketRegime:
    """Deterministic market regime label and supporting evidence."""

    as_of: datetime
    name: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    tilts: dict[str, Any] = field(default_factory=dict)
    benchmark_snapshot: dict[str, Any] = field(default_factory=dict)
    sector_snapshot: dict[str, Any] = field(default_factory=dict)
    breadth_snapshot: dict[str, Any] = field(default_factory=dict)
    macro_snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "name": self.name,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "tilts": self.tilts,
            "benchmark_snapshot": self.benchmark_snapshot,
            "sector_snapshot": self.sector_snapshot,
            "breadth_snapshot": self.breadth_snapshot,
            "macro_snapshot": self.macro_snapshot,
        }


@dataclass
class ScoredCandidate:
    """Deterministic output of the factor scorer for one symbol."""

    symbol: str
    sector: str | None
    rank: int
    overall_score: float
    confidence: float
    data_completeness: float
    technical_score: float
    fundamental_score: float
    valuation_score: float
    flow_score: float
    sentiment_score: float
    macro_score: float
    catalyst_score: float
    liquidity_score: float
    risk_score: float
    thesis_type: str
    expected_horizon_days: int | None
    bull_case: str
    bear_case: str
    key_drivers: list[str] = field(default_factory=list)
    setup_trigger: str = ""
    invalidations: list[str] = field(default_factory=list)
    target_price: float | None = None
    stop_price: float | None = None
    is_portfolio_holding: bool = False
    portfolio_relevance: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    subscores: dict[str, Any] = field(default_factory=dict)

    def to_signal_row(self, analysis_run_id: str) -> SecuritySignal:
        return SecuritySignal(
            analysis_run_id=analysis_run_id,
            symbol=self.symbol,
            sector=self.sector,
            overall_score=self.overall_score,
            technical_score=self.technical_score,
            fundamental_score=self.fundamental_score,
            valuation_score=self.valuation_score,
            flow_score=self.flow_score,
            sentiment_score=self.sentiment_score,
            macro_score=self.macro_score,
            catalyst_score=self.catalyst_score,
            liquidity_score=self.liquidity_score,
            risk_score=self.risk_score,
            data_completeness=self.data_completeness,
            subscores=self.subscores,
            evidence=self.evidence,
        )

    def to_candidate_row(self, analysis_run_id: str) -> CandidateIdea:
        return CandidateIdea(
            analysis_run_id=analysis_run_id,
            symbol=self.symbol,
            rank=self.rank,
            thesis_type=self.thesis_type,
            overall_score=self.overall_score,
            confidence=self.confidence,
            expected_horizon_days=self.expected_horizon_days,
            bull_case=self.bull_case,
            bear_case=self.bear_case,
            key_drivers=self.key_drivers,
            setup_trigger=self.setup_trigger,
            invalidations=self.invalidations,
            portfolio_relevance=self.portfolio_relevance,
            is_portfolio_holding=self.is_portfolio_holding,
            target_price=self.target_price,
            stop_price=self.stop_price,
            evidence=self.evidence,
        )


def _dedupe(seq: list[str]) -> list[str]:
    return list(dict.fromkeys(sym.upper() for sym in seq if sym))


def _now_market_date() -> date:
    return datetime.now(NY_TZ).date()


async def _fetch_portfolio_symbols(db: AsyncSession | None) -> list[str]:
    if db is None:
        return []

    result = await db.execute(
        select(PortfolioHolding.symbol)
        .join(Portfolio, Portfolio.id == PortfolioHolding.portfolio_id)
        .order_by(PortfolioHolding.symbol.asc())
    )
    return _dedupe([row[0] for row in result.fetchall()])


async def _fetch_active_stock_symbols(db: AsyncSession | None) -> list[str]:
    if db is None:
        return []

    result = await db.execute(
        select(Stock.symbol)
        .where(Stock.is_active == True)  # noqa: E712
        .order_by(Stock.symbol.asc())
    )
    return _dedupe([row[0] for row in result.fetchall()])


async def build_market_universe(db: AsyncSession | None = None) -> MarketUniverse:
    """Build a market-wide universe with portfolio overlay."""
    now = datetime.now(NY_TZ)

    dynamic = await get_screening_universe()
    categories: dict[str, list[str]] = {name: _dedupe(symbols) for name, symbols in dynamic.items()}

    active_stock_symbols = await _fetch_active_stock_symbols(db)
    portfolio_symbols = await _fetch_portfolio_symbols(db)

    if active_stock_symbols:
        categories["Active Stocks"] = _dedupe(active_stock_symbols)
    if portfolio_symbols:
        categories["Portfolio Holdings"] = _dedupe(portfolio_symbols)

    all_symbols: list[str] = []
    for symbols in categories.values():
        all_symbols.extend(symbols)
    all_symbols.extend(active_stock_symbols)
    all_symbols.extend(portfolio_symbols)
    all_symbols.extend(DEFAULT_REGIME_SYMBOLS)
    all_symbols.extend(list(SECTOR_ETFS.keys()))

    return MarketUniverse(
        as_of=now,
        all_symbols=_dedupe(all_symbols),
        categories=categories,
        portfolio_symbols=portfolio_symbols,
        active_stock_symbols=active_stock_symbols,
    )


async def _fetch_price_history(symbol: str, period: str = "3mo") -> list[dict[str, Any]]:
    try:
        return await yahoo_adapter.get_price_history(symbol, period=period)
    except Exception as exc:
        logger.debug("Price history fetch failed for %s: %s", symbol, exc)
        return []


def _returns_from_history(history: list[dict[str, Any]]) -> dict[str, float | None]:
    closes = [float(row["close"]) for row in history if row.get("close") is not None]
    if len(closes) < 2:
        return {"1d": None, "5d": None, "20d": None, "60d": None, "latest": None}

    latest = closes[-1]

    def _ret(offset: int) -> float | None:
        if len(closes) <= offset:
            return None
        ref = closes[-1 - offset]
        if not ref:
            return None
        return ((latest / ref) - 1.0) * 100.0

    return {
        "1d": _ret(1),
        "5d": _ret(5),
        "20d": _ret(20),
        "60d": _ret(60),
        "latest": latest,
    }


async def _fetch_macro_snapshot() -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    if fred_adapter is not None and getattr(fred_adapter, "is_available", False):
        try:
            ten_year = await fred_adapter.get_latest_value("DGS10")
            two_year = await fred_adapter.get_latest_value("DGS2")
            if ten_year is not None and two_year is not None:
                snapshot["yield_curve_10y2y"] = round(float(ten_year) - float(two_year), 2)
        except Exception as exc:
            logger.debug("FRED macro snapshot failed: %s", exc)
    return snapshot


async def detect_market_regime() -> MarketRegime:
    """Detect the current market regime from price, breadth, and macro inputs."""
    now = datetime.now(NY_TZ)

    symbols = list(dict.fromkeys(DEFAULT_REGIME_SYMBOLS + list(SECTOR_ETFS.keys())))
    histories = await asyncio.gather(
        *[_fetch_price_history(sym) for sym in symbols],
        return_exceptions=True,
    )

    price_by_symbol: dict[str, dict[str, float | None]] = {}
    for sym, hist in zip(symbols, histories):
        if isinstance(hist, BaseException):
            continue
        price_by_symbol[sym] = _returns_from_history(hist)

    spy = price_by_symbol.get("SPY", {})
    qqq = price_by_symbol.get("QQQ", {})
    iwm = price_by_symbol.get("IWM", {})
    vix = price_by_symbol.get("^VIX", {})

    sector_returns = {
        symbol: (metrics.get("20d") or 0.0)
        for symbol, metrics in price_by_symbol.items()
        if symbol in SECTOR_ETFS
    }

    positive_sectors = sum(1 for ret in sector_returns.values() if ret > 0)
    negative_sectors = sum(1 for ret in sector_returns.values() if ret < 0)
    sector_strength = positive_sectors - negative_sectors

    spy_20d = float(spy.get("20d") or 0.0)
    qqq_20d = float(qqq.get("20d") or 0.0)
    iwm_20d = float(iwm.get("20d") or 0.0)
    vix_latest = float(vix.get("latest") or 0.0)

    macro_snapshot = await _fetch_macro_snapshot()

    evidence: list[str] = []
    tilts: dict[str, Any] = {}

    if vix_latest >= 25:
        evidence.append(f"VIX elevated at {vix_latest:.1f}")
    elif vix_latest and vix_latest <= 16:
        evidence.append(f"VIX subdued at {vix_latest:.1f}")

    evidence.append(f"SPY 20d trend {spy_20d:+.2f}%")
    evidence.append(f"QQQ 20d trend {qqq_20d:+.2f}% vs IWM {iwm_20d:+.2f}%")

    if sector_strength > 0:
        evidence.append(f"Sector breadth positive: {positive_sectors} sectors up vs {negative_sectors} down")
    elif sector_strength < 0:
        evidence.append(f"Sector breadth negative: {positive_sectors} sectors up vs {negative_sectors} down")

    if "yield_curve_10y2y" in macro_snapshot:
        evidence.append(f"10y-2y spread at {macro_snapshot['yield_curve_10y2y']:+.2f}bps")

    if vix_latest >= 25 and spy_20d <= 0:
        name = "risk_off"
        confidence = 0.82
        tilts = {"favor": ["quality", "cash_flow", "defensives"], "avoid": ["high_beta", "unprofitable"]}
    elif spy_20d > 3 and qqq_20d > iwm_20d and positive_sectors >= negative_sectors:
        name = "risk_on_growth"
        confidence = 0.76
        tilts = {"favor": ["tech", "communication_services", "cyclicals"], "avoid": ["defensives"]}
    elif iwm_20d > qqq_20d and positive_sectors > negative_sectors:
        name = "broadening_out"
        confidence = 0.69
        tilts = {"favor": ["small_caps", "industrials", "financials"], "avoid": ["crowded_megacaps"]}
    elif spy_20d > 0 and negative_sectors > positive_sectors:
        name = "defensive_rotation"
        confidence = 0.67
        tilts = {"favor": ["staples", "utilities", "healthcare"], "avoid": ["high_beta"]}
    else:
        name = "transition"
        confidence = 0.55
        tilts = {"favor": ["balanced"], "avoid": ["strong_leverage"]}

    return MarketRegime(
        as_of=now,
        name=name,
        confidence=confidence,
        evidence=evidence,
        tilts=tilts,
        benchmark_snapshot={"SPY": spy, "QQQ": qqq, "IWM": iwm, "VIX": vix},
        sector_snapshot=sector_returns,
        breadth_snapshot={
            "positive_sectors": positive_sectors,
            "negative_sectors": negative_sectors,
            "sector_strength": sector_strength,
        },
        macro_snapshot=macro_snapshot,
    )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _safe_mean(values: list[float]) -> float | None:
    values = [float(v) for v in values if v is not None]
    return statistics.mean(values) if values else None


def _safe_std(values: list[float]) -> float | None:
    values = [float(v) for v in values if v is not None]
    if len(values) < 2:
        return None
    return statistics.pstdev(values)


def _price_series(history: list[dict[str, Any]]) -> tuple[list[float], list[float]]:
    closes = [float(row["close"]) for row in history if row.get("close") is not None]
    volumes = [float(row.get("volume") or 0.0) for row in history if row.get("close") is not None]
    return closes, volumes


def _pct_return(closes: list[float], offset: int) -> float | None:
    if len(closes) <= offset:
        return None
    start = closes[-1 - offset]
    end = closes[-1]
    if not start:
        return None
    return ((end / start) - 1.0) * 100.0


def _latest_close(history: list[dict[str, Any]]) -> float | None:
    closes, _ = _price_series(history)
    return closes[-1] if closes else None


def _volume_ratio(history: list[dict[str, Any]], lookback: int = 20) -> float | None:
    closes, volumes = _price_series(history)
    if len(volumes) < 2:
        return None
    latest = volumes[-1]
    window = volumes[-(lookback + 1):-1] if len(volumes) > lookback else volumes[:-1]
    avg = _safe_mean(window)
    if not avg:
        return None
    return latest / avg


def _sector_symbol_to_etf() -> dict[str, str]:
    return {sector.lower(): etf for etf, sector in SECTOR_ETFS.items()}


def _sentiment_lookup(sentiment: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    if not sentiment:
        return lookup
    for row in sentiment.get("per_symbol", []) or []:
        if isinstance(row, dict):
            symbol = str(row.get("symbol") or "").upper()
            if symbol:
                lookup[symbol] = row
    for row in sentiment.get("symbol_sentiments", []) or []:
        if isinstance(row, dict):
            symbol = str(row.get("symbol") or "").upper()
            if symbol:
                lookup[symbol] = row
    return lookup


def _score_fundamentals(
    fundamentals: dict[str, Any] | None,
    latest_price: float | None,
) -> tuple[float, float, float, float, list[str]]:
    """Return fundamental, valuation, catalyst, liquidity scores and evidence."""
    if not fundamentals:
        return 50.0, 50.0, 45.0, 50.0, ["fundamentals unavailable"]

    f = fundamentals
    notes: list[str] = []

    def norm_low(value: float | None, thresholds: list[tuple[float, float]]) -> float | None:
        if value is None:
            return None
        if value <= thresholds[0][0]:
            return thresholds[0][1]
        for i in range(1, len(thresholds)):
            x0, y0 = thresholds[i - 1]
            x1, y1 = thresholds[i]
            if value <= x1:
                if x1 == x0:
                    return y1
                ratio = (value - x0) / (x1 - x0)
                return y0 + ratio * (y1 - y0)
        return thresholds[-1][1]

    rev_growth_raw = f.get("revenue_growth")
    gross_margin_raw = f.get("gross_margins")
    rev_growth_val = float(rev_growth_raw) if rev_growth_raw is not None else None
    gross_margin_val = float(gross_margin_raw) if gross_margin_raw is not None else None

    # Growth company: high revenue growth + strong gross margins → score on unit economics
    is_growth_company = (
        rev_growth_val is not None and rev_growth_val > 0.20
        and gross_margin_val is not None and gross_margin_val > 0.50
    )

    balance_scores = []
    current_ratio = f.get("current_ratio")
    if current_ratio is not None:
        balance_scores.append(_clamp(float(current_ratio) * 20.0, 0.0, 100.0))
    debt_to_equity = f.get("debt_to_equity")
    if debt_to_equity is not None:
        dte = float(debt_to_equity)
        balance_scores.append(
            100.0 if dte <= 0 else 80.0 if dte <= 50 else 60.0 if dte <= 100 else 40.0 if dte <= 200 else 20.0
        )
    fcf = f.get("free_cashflow")
    if fcf is not None:
        balance_scores.append(80.0 if float(fcf) > 0 else 20.0)
    if balance_scores:
        notes.append("balance")

    if is_growth_company:
        # Growth path: gross margin + revenue acceleration dominate; net profitability not penalised
        notes.append("growth_mode")
        gm_score = norm_low(gross_margin_val, [(0.0, 20.0), (0.40, 55.0), (0.55, 72.0), (0.65, 85.0), (0.75, 95.0), (0.85, 100.0)])
        rev_score = norm_low(rev_growth_val, [(0.0, 40.0), (0.15, 62.0), (0.25, 78.0), (0.40, 90.0), (0.60, 100.0)])
        growth_mode_scores: list[float] = []
        if gm_score is not None:
            growth_mode_scores += [gm_score, gm_score]  # double-weight gross margin
        if rev_score is not None:
            growth_mode_scores.append(rev_score)
        # Earnings growth bonus (expanding margins signal)
        eg = f.get("earnings_growth")
        if eg is not None and float(eg) > (rev_growth_val or 0):
            growth_mode_scores.append(75.0)
        # Balance sheet: cash runway matters more than FCF for growth names
        if balance_scores:
            growth_mode_scores.append(_safe_mean(balance_scores) or 50.0)
        fundamental_score = _safe_mean(growth_mode_scores) or 50.0
    else:
        # Value/mature path: all three margin types + balance sheet
        notes.append("growth")
        growth_scores = []
        for key in ("revenue_growth", "earnings_growth", "earnings_quarterly_growth"):
            val = f.get(key)
            if val is not None:
                score = norm_low(float(val), [(-0.50, 20.0), (0.0, 45.0), (0.10, 70.0), (0.25, 90.0), (0.50, 100.0)])
                if score is not None:
                    growth_scores.append(score)

        margin_scores = []
        notes.append("margins")
        for key in ("gross_margins", "operating_margins", "profit_margins"):
            val = f.get(key)
            if val is not None:
                score = norm_low(float(val), [(-0.20, 15.0), (0.0, 40.0), (0.10, 65.0), (0.25, 85.0), (0.40, 95.0)])
                if score is not None:
                    margin_scores.append(score)

        fundamental_score = _safe_mean([*(growth_scores or []), *(margin_scores or []), *(balance_scores or [])]) or 50.0

    forward_pe = f.get("forward_pe")
    trailing_pe = f.get("trailing_pe")
    peg = f.get("peg_ratio")
    price_to_sales = f.get("price_to_sales")
    valuation_components: list[float] = []
    if forward_pe is not None:
        pe = float(forward_pe)
        if is_growth_company:
            # Growth-adjusted: P/E 60 is cheap for a 30%+ grower (PEG ~2)
            valuation_components.append(
                95.0 if pe <= 40 else 85.0 if pe <= 70 else 70.0 if pe <= 100 else 50.0 if pe <= 150 else 25.0
            )
        else:
            valuation_components.append(
                95.0 if pe <= 15 else 85.0 if pe <= 25 else 70.0 if pe <= 35 else 50.0 if pe <= 50 else 25.0
            )
    if trailing_pe is not None:
        pe = float(trailing_pe)
        if is_growth_company:
            # Pre-profit or early-profit companies: trailing PE less meaningful, use loosely
            valuation_components.append(
                90.0 if pe <= 50 else 75.0 if pe <= 100 else 55.0 if pe <= 200 else 30.0
            )
        else:
            valuation_components.append(
                90.0 if pe <= 18 else 80.0 if pe <= 30 else 65.0 if pe <= 45 else 45.0 if pe <= 60 else 20.0
            )
    if peg is not None:
        p = float(peg)
        valuation_components.append(
            95.0 if p <= 1.0 else 85.0 if p <= 1.5 else 70.0 if p <= 2.0 else 45.0 if p <= 3.0 else 20.0
        )
    if price_to_sales is not None:
        ps = float(price_to_sales)
        if is_growth_company:
            # High-growth SaaS/tech: P/S 15-20 is normal, penalise only >35
            valuation_components.append(
                90.0 if ps <= 8 else 80.0 if ps <= 15 else 65.0 if ps <= 25 else 45.0 if ps <= 40 else 20.0
            )
        else:
            valuation_components.append(
                90.0 if ps <= 2 else 80.0 if ps <= 4 else 65.0 if ps <= 8 else 45.0 if ps <= 15 else 20.0
            )
    if not valuation_components:
        valuation_components.append(50.0)

    if latest_price is not None and f.get("target_mean_price") is not None:
        upside = ((float(f["target_mean_price"]) / latest_price) - 1.0) * 100.0
        notes.append("target")
        if upside >= 50:
            valuation_components.append(100.0)
        elif upside >= 20:
            valuation_components.append(85.0)
        elif upside >= 5:
            valuation_components.append(65.0)
        elif upside >= -10:
            valuation_components.append(40.0)
        else:
            valuation_components.append(20.0)

    valuation_score = _safe_mean(valuation_components) or 50.0

    catalyst_components: list[float] = []
    if latest_price is not None and f.get("target_mean_price") is not None:
        upside = ((float(f["target_mean_price"]) / latest_price) - 1.0) * 100.0
        catalyst_components.append(_clamp(55.0 + upside, 10.0, 100.0))
    recommendation = str(f.get("recommendation_key") or "").lower()
    if recommendation:
        if "strong_buy" in recommendation or "buy" == recommendation:
            catalyst_components.append(85.0)
        elif "sell" in recommendation:
            catalyst_components.append(30.0)
        else:
            catalyst_components.append(55.0)
    if not catalyst_components:
        catalyst_components.append(45.0)
    catalyst_score = _safe_mean(catalyst_components) or 45.0

    liquidity_components: list[float] = []
    if latest_price is not None:
        liquidity_components.append(70.0 if latest_price >= 5 else 25.0)
    market_cap = f.get("market_cap")
    if market_cap is not None:
        mc = float(market_cap)
        liquidity_components.append(
            95.0 if mc >= 10_000_000_000 else 85.0 if mc >= 2_000_000_000 else 70.0 if mc >= 500_000_000 else 50.0 if mc >= 100_000_000 else 30.0
        )
    liquidity_score = _safe_mean(liquidity_components) or 50.0

    return fundamental_score, valuation_score, catalyst_score, liquidity_score, notes


def _score_basic_technical(
    history: list[dict[str, Any]],
    benchmark_history: list[dict[str, Any]] | None,
    sector_history: list[dict[str, Any]] | None,
    technical_indicators: dict[str, Any] | None,
    rich_technical: dict[str, Any] | None,
) -> tuple[float, dict[str, Any], float, float, float]:
    closes, volumes = _price_series(history)
    if len(closes) < 2:
        return 0.0, {}, 0.0, 0.0, 100.0

    latest = closes[-1]
    ret_5 = _pct_return(closes, 5) or 0.0
    ret_20 = _pct_return(closes, 20) or 0.0
    ret_60 = _pct_return(closes, 60) or 0.0

    spy_5 = _pct_return(_price_series(benchmark_history or [])[0], 5) or 0.0
    spy_20 = _pct_return(_price_series(benchmark_history or [])[0], 20) or 0.0
    sector_20 = _pct_return(_price_series(sector_history or [])[0], 20) or 0.0

    avg_20 = _safe_mean(closes[-20:]) or latest
    avg_50 = _safe_mean(closes[-50:]) or latest
    vol_ratio = _volume_ratio(history, 20) or 1.0
    close_above_20 = 1.0 if latest >= avg_20 else 0.0
    close_above_50 = 1.0 if latest >= avg_50 else 0.0
    accel = ret_5 - ret_20
    rel_strength = (ret_20 - spy_20) * 2.0 + (ret_5 - spy_5)
    sector_strength = sector_20
    volatility = _safe_std(
        [((closes[i] / closes[i - 1]) - 1.0) * 100.0 for i in range(1, len(closes)) if closes[i - 1]]
    ) or 0.0

    rich_signal = 0.0
    rich_confidence = 0.0
    rating = "neutral"
    if rich_technical and isinstance(rich_technical, dict):
        summary = rich_technical.get("signal_summary", {}) or {}
        if isinstance(summary, dict):
            rich_signal = float(summary.get("composite_score") or 0.0) * 100.0
            rich_confidence = float(summary.get("confidence") or 0.0) * 100.0
            rating = str(summary.get("rating") or rating)

    indicator_bonus = 0.0
    if technical_indicators and isinstance(technical_indicators, dict):
        for key, entry in technical_indicators.items():
            if not isinstance(entry, dict):
                continue
            key_u = key.upper()
            value = entry.get("value")
            if value is None:
                continue
            val = float(value)
            if "RSI" in key_u:
                indicator_bonus += 8.0 if 40.0 <= val <= 60.0 else 4.0 if 30.0 <= val < 40.0 or 60.0 < val <= 70.0 else 0.0
            elif "ADX" in key_u:
                indicator_bonus += 8.0 if val >= 25.0 else 4.0 if val >= 18.0 else 0.0
            elif key_u.startswith("SMA_20") or key_u.startswith("EMA_20"):
                indicator_bonus += 6.0 if latest >= val else 0.0
            elif key_u.startswith("SMA_50") or key_u.startswith("EMA_50"):
                indicator_bonus += 6.0 if latest >= val else 0.0

    # IC-calibrated weights (Phase 2): volatility IC=+0.111 at 90d; accel IC=−0.127 at 20d;
    # ret_60 IC=−0.163 at 90d (mean-reversion for overextended names).
    volatility_signal = _clamp((volatility - 1.0) / 3.5, 0.0, 1.0) * 100.0
    ret_60_overextension = _clamp((ret_60 - 20.0) / 40.0, 0.0, 1.0) * 10.0
    technical_score = (
        0.25 * _clamp((ret_20 + 25.0) / 50.0, 0.0, 1.0) * 100.0
        + 0.20 * _clamp((rel_strength + 35.0) / 70.0, 0.0, 1.0) * 100.0
        + 0.15 * volatility_signal
        + 0.10 * _clamp((vol_ratio - 0.5) / 2.5, 0.0, 1.0) * 100.0
        + 0.08 * _clamp(close_above_20 + close_above_50, 0.0, 2.0) / 2.0 * 100.0
        + 0.10 * _clamp((sector_strength + 20.0) / 40.0, 0.0, 1.0) * 100.0
        + 0.07 * _clamp((accel + 20.0) / 40.0, 0.0, 1.0) * 100.0
        + 0.05 * _clamp((rich_signal + 100.0) / 200.0, 0.0, 1.0) * 100.0
        + indicator_bonus
        - ret_60_overextension
    )
    technical_score = _clamp(technical_score, 0.0, 100.0)
    # Remove volatility from risk_score: it's the single strongest positive predictor (IC +0.111).
    # Replace with ret_60 overextension penalty: stocks that already ran >20% in 60d face
    # mean-reversion risk (IC −0.163 at 90d).
    risk_score = _clamp(
        55.0
        + abs(min(ret_20, 0.0)) * 0.8
        + max(0.0, ret_60 - 20.0) * 0.4
        - vol_ratio * 5.0
        - close_above_20 * 5.0
        - close_above_50 * 5.0,
        0.0,
        100.0,
    )
    flow_proxy = _clamp((vol_ratio - 0.5) / 2.5 * 100.0, 0.0, 100.0)

    evidence = {
        "ret_5d": round(ret_5, 2),
        "ret_20d": round(ret_20, 2),
        "ret_60d": round(ret_60, 2),
        "spy_20d": round(spy_20, 2),
        "rel_strength_20d": round(rel_strength, 2),
        "volume_ratio": round(vol_ratio, 2),
        "volatility_daily_pct": round(volatility, 3),
        "volatility_signal": round(volatility_signal, 1),
        "ret_60_overextension_penalty": round(ret_60_overextension, 1),
        "rich_signal": round(rich_signal, 2),
        "rich_confidence": round(rich_confidence, 2),
        "rating": rating,
    }

    return technical_score, evidence, flow_proxy, risk_score, volatility


def _macro_alignment_score(regime_name: str, sector: str | None) -> float:
    sector = (sector or "").lower()
    defensive = any(token in sector for token in ("health", "staple", "utility", "real estate"))
    growth = any(token in sector for token in ("tech", "communication", "consumer discretionary"))
    cyclical = any(token in sector for token in ("financial", "industrial", "materials", "energy"))

    if regime_name == "risk_off":
        return 88.0 if defensive else 40.0 if growth or cyclical else 60.0
    if regime_name == "risk_on_growth":
        return 88.0 if growth else 72.0 if cyclical else 50.0
    if regime_name == "broadening_out":
        return 88.0 if cyclical else 76.0 if growth else 60.0
    if regime_name == "defensive_rotation":
        return 88.0 if defensive else 55.0
    return 65.0


def _sentiment_score(symbol: str, sentiment_lookup: dict[str, dict[str, Any]]) -> tuple[float, dict[str, Any]]:
    row = sentiment_lookup.get(symbol.upper())
    if not row:
        return 50.0, {"sentiment": "missing"}

    raw = row.get("sentiment_score")
    if raw is None:
        raw = row.get("overall_score")
    if raw is None:
        return 50.0, {"sentiment": "neutral", "source": row}
    raw = float(raw)
    score = _clamp((raw + 1.0) / 2.0 * 100.0, 0.0, 100.0)
    return score, {"sentiment": raw, "source": row}


def _thesis_type(technical: float, fundamental: float, valuation: float, flow: float, catalyst: float) -> tuple[str, int]:
    if technical >= 70 and flow >= 60:
        return "momentum", 45
    if technical >= 65 and catalyst >= 65 and valuation >= 45:
        return "breakout", 60
    if fundamental >= 70 and valuation >= 60:
        return "quality_re_rate", 90
    if catalyst >= 70:
        return "catalyst", 30
    return "setup", 45


async def _build_portfolio_overlay(
    db: AsyncSession,
    candidate_rows: list[ScoredCandidate],
    context: dict[str, Any],
    regime: MarketRegime,
) -> dict[str, Any]:
    holdings_result = await db.execute(
        select(PortfolioHolding, Stock)
        .join(Portfolio, Portfolio.id == PortfolioHolding.portfolio_id)
        .join(Stock, Stock.symbol == PortfolioHolding.symbol)
        .order_by(PortfolioHolding.symbol.asc())
    )
    holding_rows = holdings_result.all()

    price_history = context.get("price_history", {}) or {}

    holdings: list[dict[str, Any]] = []
    sector_values: dict[str, float] = {}
    total_value = 0.0

    for holding, stock in holding_rows:
        hist = price_history.get(stock.symbol, [])
        latest = _latest_close(hist)
        market_value = (holding.shares * latest) if latest is not None else (holding.shares * holding.cost_basis)
        total_value += market_value
        sector = stock.sector or "Unknown"
        sector_values[sector] = sector_values.get(sector, 0.0) + market_value
        holdings.append(
            {
                "symbol": stock.symbol,
                "sector": sector,
                "shares": holding.shares,
                "cost_basis": holding.cost_basis,
                "latest_price": latest,
                "market_value": round(market_value, 2),
                "weight": 0.0,  # filled after total_value known
            }
        )

    for row in holdings:
        row["weight"] = round(row["market_value"] / total_value, 4) if total_value else 0.0

    sector_weights = {
        sector: round(value / total_value, 4) if total_value else 0.0
        for sector, value in sector_values.items()
    }
    top_sector = max(sector_weights.items(), key=lambda item: item[1], default=(None, 0.0))
    top_three = sorted(sector_weights.values(), reverse=True)[:3]

    concentration = "low"
    if top_sector[1] >= 0.35 or sum(top_three) >= 0.65:
        concentration = "high"
    elif top_sector[1] >= 0.25 or sum(top_three) >= 0.50:
        concentration = "moderate"

    holding_symbols = {h["symbol"] for h in holdings}
    suggestions: list[dict[str, Any]] = []
    for candidate in candidate_rows[:10]:
        action = "add"
        reason_parts: list[str] = []
        if candidate.symbol in holding_symbols:
            action = "hold"
            if candidate.overall_score < 55:
                action = "trim"
                reason_parts.append("held name but weak relative score")
            else:
                reason_parts.append("already in portfolio")
        elif concentration == "high" and candidate.sector and candidate.sector == top_sector[0]:
            action = "hedge"
            reason_parts.append(f"portfolio already concentrated in {candidate.sector}")
        elif candidate.overall_score < 60:
            action = "watch"
            reason_parts.append("insufficient edge for immediate add")
        else:
            reason_parts.append("strong score vs universe")

        if regime.name == "risk_off" and action == "add":
            action = "watch"
            reason_parts.append("risk-off regime favors patience")
        elif regime.name == "risk_on_growth" and action in {"add", "hold"}:
            reason_parts.append("risk-on growth regime supports offense")

        suggestions.append(
            {
                "symbol": candidate.symbol,
                "sector": candidate.sector,
                "action": action,
                "score": round(candidate.overall_score, 2),
                "confidence": round(candidate.confidence, 3),
                "reason": "; ".join(reason_parts) or "overlay generated",
            }
        )

    return {
        "portfolio_value_estimate": round(total_value, 2),
        "holdings": holdings,
        "sector_weights": sector_weights,
        "concentration_risk": concentration,
        "top_sector": {"sector": top_sector[0], "weight": round(top_sector[1], 4)},
        "suggestions": suggestions,
    }


async def run_daily_factor_scoring(
    db: AsyncSession,
    run: AnalysisRun,
    universe: MarketUniverse,
    regime: MarketRegime,
) -> dict[str, Any]:
    """Score the universe, persist candidates, and build portfolio overlay."""
    settings = get_settings()
    builder = ContextBuilder()

    logger.info(
        "Building factor context for %d symbols (daily v2 scoring)",
        len(universe.all_symbols),
    )
    context = await builder.build_context(
        symbols=universe.all_symbols,
        include_price_history=True,
        include_technical=True,
        include_economic=True,
        include_sectors=True,
        include_rich_technical=True,
        include_predictions=True,
        include_sentiment=True,
        include_fundamentals=True,
        include_options_flow=True,
        include_short_interest=True,
        include_analyst_revisions=True,
        price_history_days=90,
    )

    price_history = context.get("price_history", {}) or {}
    technical_indicators = context.get("technical_indicators", {}) or {}
    rich_technical = context.get("rich_technical", {}) or {}
    fundamentals = context.get("fundamentals", {}) or {}
    options_flow = context.get("options_flow", {}) or {}
    short_interest = context.get("short_interest", {}) or {}
    analyst_revisions = context.get("analyst_revisions", {}) or {}
    sector_performance = context.get("sector_performance", {}) or {}
    sentiment_lookup = _sentiment_lookup(context.get("sentiment"))
    market_summary = context.get("market_summary", {}) or {}

    spy_history = price_history.get("SPY", [])
    sector_reverse = _sector_symbol_to_etf()

    scored: list[ScoredCandidate] = []
    all_symbols = universe.all_symbols
    for symbol in all_symbols:
        history = price_history.get(symbol)
        if not history:
            continue

        stock_info = next((s for s in context.get("stocks", []) if s.get("symbol") == symbol), {})
        sector = stock_info.get("sector") or "Unknown"
        sector_etf = sector_reverse.get(str(sector).lower())
        sector_history = price_history.get(sector_etf, []) if sector_etf else []
        fundamental_data = fundamentals.get(symbol, {})
        options_flow_data = options_flow.get(symbol, {})
        short_interest_data = short_interest.get(symbol, {})
        analyst_revision_data = analyst_revisions.get(symbol, {})
        rich_data = rich_technical.get(symbol, {})
        technical_data = technical_indicators.get(symbol, {})

        tech_score, tech_evidence, flow_proxy, risk_score, volatility = _score_basic_technical(
            history,
            spy_history,
            sector_history,
            technical_data,
            rich_data,
        )
        fundamental_score, valuation_score, catalyst_score, liquidity_score, fundamental_notes = _score_fundamentals(
            fundamental_data,
            _latest_close(history),
        )
        sentiment_score, sentiment_evidence = _sentiment_score(symbol, sentiment_lookup)
        macro_score = _macro_alignment_score(regime.name, sector)

        options_flow_score = float(options_flow_data.get("signal_score") or 0.0) if isinstance(options_flow_data, dict) else 0.0
        short_interest_score = float(short_interest_data.get("squeeze_score") or 0.0) if isinstance(short_interest_data, dict) else 0.0
        revision_score = float(analyst_revision_data.get("revision_score") or 0.0) if isinstance(analyst_revision_data, dict) else 0.0
        if options_flow_score > 0:
            flow_proxy = _clamp((flow_proxy + options_flow_score) / 2.0, 0.0, 100.0)
        if short_interest_score > 0:
            catalyst_score = _clamp((catalyst_score + short_interest_score) / 2.0, 0.0, 100.0)
        if revision_score > 0:
            fundamental_score = _clamp((fundamental_score * 0.7) + (revision_score * 0.3), 0.0, 100.0)
            catalyst_score = _clamp((catalyst_score * 0.8) + (revision_score * 0.2), 0.0, 100.0)

        # For high-quality growth companies, absence of retail flow is not a negative signal.
        # Floor at 35 (neutral) so WSB silence doesn't sink fundamentally strong innovators.
        if (
            "growth_mode" in fundamental_notes
            and fundamental_score >= 65
            and flow_proxy < 35.0
        ):
            flow_proxy = 35.0

        prediction_boost = 0.0
        predictions = context.get("predictions") or {}
        if isinstance(predictions, dict):
            for bucket in predictions.values():
                if isinstance(bucket, dict):
                    for row in bucket.values():
                        if isinstance(row, dict) and str(row.get("symbol") or "").upper() == symbol:
                            prediction_boost = 5.0
                            break

        data_completeness_flags = [
            bool(history),
            bool(technical_data),
            bool(rich_data),
            bool(fundamental_data),
            bool(options_flow_data),
            bool(short_interest_data),
            bool(analyst_revision_data),
            _volume_ratio(history, 20) is not None,
            symbol in sentiment_lookup,
            bool(fundamental_data.get("target_mean_price") if isinstance(fundamental_data, dict) else None),
            bool(fundamental_data.get("market_cap") if isinstance(fundamental_data, dict) else None),
        ]
        data_completeness = sum(1 for flag in data_completeness_flags if flag) / len(data_completeness_flags)

        positive = (
            0.28 * tech_score
            + 0.20 * fundamental_score
            + 0.12 * valuation_score
            + 0.10 * flow_proxy
            + 0.08 * sentiment_score
            + 0.10 * macro_score
            + 0.07 * catalyst_score
            + 0.05 * liquidity_score
        )
        overall = positive - (0.14 * risk_score)
        if prediction_boost:
            overall += prediction_boost
        overall *= (0.70 + 0.30 * data_completeness)
        overall = _clamp(overall, 0.0, 100.0)

        alignment_bonus = sum(
            1
            for score in (tech_score, fundamental_score, macro_score, sentiment_score, catalyst_score)
            if score >= 60
        )
        confidence = _clamp(
            0.25 + 0.45 * data_completeness + 0.05 * alignment_bonus + 0.002 * overall,
            0.10,
            0.95,
        )

        fundamental_strength = fundamental_score >= 60 or valuation_score >= 60
        thesis_type, horizon = _thesis_type(tech_score, fundamental_score, valuation_score, flow_proxy, catalyst_score)
        if tech_score >= 70 and fundamental_strength and flow_proxy >= 60:
            thesis_type = "momentum"
            horizon = 30
        if tech_score >= 65 and valuation_score >= 60 and fundamental_score >= 60:
            thesis_type = "re_rating"
            horizon = 90
        if catalyst_score >= 75:
            thesis_type = "catalyst"
            horizon = 21

        latest_price = _latest_close(history) or 0.0
        target_price = None
        if fundamental_data.get("target_mean_price") is not None and latest_price:
            target_price = float(fundamental_data["target_mean_price"])
        stop_price = latest_price * 0.92 if latest_price else None

        bull_case = (
            f"Technical score {tech_score:.0f}, fundamental score {fundamental_score:.0f}, "
            f"macro alignment {macro_score:.0f}."
        )
        if fundamental_data.get("target_mean_price") and latest_price:
            upside = ((float(fundamental_data["target_mean_price"]) / latest_price) - 1.0) * 100.0
            bull_case += f" Street upside {upside:+.1f}%."
        if rich_data:
            bull_case += f" Rich TA rating {rich_data.get('signal_summary', {}).get('rating', 'n/a')}."

        bear_case = (
            f"Risk score {risk_score:.0f}, sentiment {sentiment_score:.0f}, "
            f"volatility {volatility:.2f}, flow proxy {flow_proxy:.0f}."
        )
        if latest_price and stop_price:
            bear_case += f" Stop guide near {stop_price:.2f}."

        key_drivers = [
            f"tech:{tech_score:.0f}",
            f"fund:{fundamental_score:.0f}",
            f"val:{valuation_score:.0f}",
            f"flow:{flow_proxy:.0f}",
            f"optflow:{options_flow_score:.0f}",
            f"short:{short_interest_score:.0f}",
            f"rev:{revision_score:.0f}",
            f"sent:{sentiment_score:.0f}",
            f"macro:{macro_score:.0f}",
            f"catalyst:{catalyst_score:.0f}",
        ]
        if prediction_boost:
            key_drivers.append("prediction_boost")
        if rich_data:
            key_drivers.append(f"rich:{rich_data.get('signal_summary', {}).get('rating', 'n/a')}")

        evidence = {
            "technical": tech_evidence,
            "fundamentals": {
                "upside_target": target_price,
                "notes": fundamental_notes,
            },
            "options_flow": options_flow_data,
            "short_interest": short_interest_data,
            "analyst_revisions": analyst_revision_data,
            "sentiment": sentiment_evidence,
            "market_summary": market_summary.get("market_index", {}),
            "sector_performance": sector_performance.get(sector_etf, {}) if sector_etf else {},
            "prediction_boost": prediction_boost,
            "completeness": round(data_completeness, 3),
        }

        subscores = {
            "technical": round(tech_score, 2),
            "fundamental": round(fundamental_score, 2),
            "valuation": round(valuation_score, 2),
            "flow": round(flow_proxy, 2),
            "options_flow": round(options_flow_score, 2),
            "short_interest": round(short_interest_score, 2),
            "analyst_revisions": round(revision_score, 2),
            "sentiment": round(sentiment_score, 2),
            "macro": round(macro_score, 2),
            "catalyst": round(catalyst_score, 2),
            "liquidity": round(liquidity_score, 2),
            "risk": round(risk_score, 2),
            "prediction_boost": round(prediction_boost, 2),
        }

        scored.append(
            ScoredCandidate(
                symbol=symbol,
                sector=sector,
                rank=0,
                overall_score=round(overall, 2),
                confidence=round(confidence, 4),
                data_completeness=round(data_completeness, 4),
                technical_score=round(tech_score, 2),
                fundamental_score=round(fundamental_score, 2),
                valuation_score=round(valuation_score, 2),
                flow_score=round(flow_proxy, 2),
                sentiment_score=round(sentiment_score, 2),
                macro_score=round(macro_score, 2),
                catalyst_score=round(catalyst_score, 2),
                liquidity_score=round(liquidity_score, 2),
                risk_score=round(risk_score, 2),
                thesis_type=thesis_type,
                expected_horizon_days=horizon,
                bull_case=bull_case,
                bear_case=bear_case,
                key_drivers=key_drivers,
                setup_trigger=f"Close {latest_price:.2f}" if latest_price else "Monitor price action",
                invalidations=[f"Break below {stop_price:.2f}" if stop_price else "Loss of trend"],
                target_price=target_price,
                stop_price=stop_price,
                is_portfolio_holding=symbol in universe.portfolio_symbols,
                subscores=subscores,
                evidence=evidence,
            )
        )

    scored.sort(key=lambda item: item.overall_score, reverse=True)
    for idx, candidate in enumerate(scored, start=1):
        candidate.rank = idx

    max_ideas = max(1, int(settings.SCHEDULED_ANALYSIS_MAX_INSIGHTS))
    signal_limit = max(25, max_ideas * 8)
    signal_rows = scored[:signal_limit]
    candidate_rows = scored[:max_ideas]

    overlay = await _build_portfolio_overlay(db, scored, context, regime)

    for row in signal_rows:
        db.add(row.to_signal_row(run.id))
    for row in candidate_rows:
        if row.symbol in universe.portfolio_symbols:
            if row.overall_score >= 70:
                row.portfolio_relevance = "High-conviction held name; consider adding on strength."
            elif row.overall_score <= 50:
                row.portfolio_relevance = "Held name but weak relative score; consider trimming."
            else:
                row.portfolio_relevance = "Held name; maintain watch."
        else:
            row.portfolio_relevance = (
                "Candidate adds diversification" if overlay.get("concentration_risk") == "high"
                else "Candidate fits current market regime"
            )
        row.evidence["portfolio_overlay"] = overlay
        db.add(row.to_candidate_row(run.id))

    run.ideas_persisted = len(candidate_rows)
    run.analysis_metadata = {
        **(run.analysis_metadata or {}),
        "scoring": {
            "scored_symbols": len(scored),
            "signal_rows": len(signal_rows),
            "candidate_rows": len(candidate_rows),
            "top_symbol": scored[0].symbol if scored else None,
            "top_score": scored[0].overall_score if scored else None,
            "factor_weights": {
                "technical": 0.28,
                "fundamental": 0.20,
                "valuation": 0.12,
                "flow": 0.10,
                "sentiment": 0.08,
                "macro": 0.10,
                "catalyst": 0.07,
                "liquidity": 0.05,
                "risk_penalty": 0.14,
            },
            "portfolio_overlay": overlay,
        },
    }

    return {
        "scored": scored,
        "signal_rows": signal_rows,
        "candidate_rows": candidate_rows,
        "portfolio_overlay": overlay,
        "context": context,
    }


async def create_daily_alpha_run(db: AsyncSession) -> dict[str, Any]:
    """Persist the daily preflight snapshot and return a summary."""
    market_date = _now_market_date()
    started_at = datetime.now(NY_TZ)

    run = AnalysisRun(
        run_type="daily",
        status=AnalysisRunStatus.RUNNING.value,
        market_date=market_date,
        started_at=started_at,
    )
    db.add(run)
    await db.flush()

    universe = await build_market_universe(db)
    regime = await detect_market_regime()

    run.market_regime = regime.name
    run.market_confidence = regime.confidence
    run.universe_size = len(universe.all_symbols)
    run.symbols_scanned = len(universe.all_symbols)
    run.portfolio_symbols = universe.portfolio_symbols
    run.analysis_metadata = {
        "universe_categories": len(universe.categories),
        "top_categories": {name: len(symbols) for name, symbols in list(universe.categories.items())[:6]},
    }

    snapshot = MarketSnapshot(
        analysis_run_id=run.id,
        market_date=market_date,
        regime_name=regime.name,
        regime_confidence=regime.confidence,
        benchmark_snapshot=regime.benchmark_snapshot,
        sector_snapshot=regime.sector_snapshot,
        macro_snapshot=regime.macro_snapshot,
        breadth_snapshot=regime.breadth_snapshot,
        portfolio_snapshot={
            "symbols": universe.portfolio_symbols,
            "holding_count": len(universe.portfolio_symbols),
        },
        universe_snapshot=universe.to_dict(),
        notes="Phase 1 preflight snapshot; candidate ranking arrives in later phases.",
    )
    db.add(snapshot)

    scoring = await run_daily_factor_scoring(db, run, universe, regime)
    snapshot.portfolio_snapshot = scoring["portfolio_overlay"]
    snapshot.notes = "Phase 2 factor-ranked snapshot with portfolio overlay."

    synthesis = await synthesize_alpha_run(
        db,
        run=run,
        candidates=scoring["candidate_rows"],
        portfolio_overlay=scoring["portfolio_overlay"],
        regime=regime,
        market_snapshot={
            "market_date": market_date.isoformat(),
            "market_regime": regime.name,
            "market_confidence": regime.confidence,
            "universe_size": len(universe.all_symbols),
            "portfolio_symbols": len(universe.portfolio_symbols),
        },
    )
    run.analysis_metadata = {
        **(run.analysis_metadata or {}),
        "synthesis": {
            "summary": synthesis.get("summary"),
            "deep_insights_seeded": synthesis.get("deep_insights_seeded", 0),
            "tracked": synthesis.get("tracked", 0),
            "data_gaps": synthesis.get("data_gaps", []),
        },
    }

    run.status = AnalysisRunStatus.COMPLETED.value
    run.completed_at = datetime.now(NY_TZ)
    await db.flush()

    return {
        "analysis_run_id": run.id,
        "market_date": market_date.isoformat(),
        "universe_size": len(universe.all_symbols),
        "regime": regime.to_dict(),
        "universe": universe.to_dict(),
        "top_candidates": [
            {
                "symbol": c.symbol,
                "rank": c.rank,
                "score": c.overall_score,
                "confidence": c.confidence,
                "thesis_type": c.thesis_type,
            }
            for c in scoring["candidate_rows"]
        ],
        "portfolio_overlay": scoring["portfolio_overlay"],
        "synthesis": {
            "summary": synthesis.get("summary"),
            "deep_insights_seeded": synthesis.get("deep_insights_seeded", 0),
            "tracked": synthesis.get("tracked", 0),
            "data_gaps": synthesis.get("data_gaps", []),
        },
    }


__all__ = ["MarketUniverse", "MarketRegime", "build_market_universe", "detect_market_regime", "create_daily_alpha_run"]
