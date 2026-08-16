"""Tests for per-symbol evidence packets in the autonomous deep dive.

THE regression under test: the deep dive built one market context covering every
candidate and handed that same object to each symbol's analysts.  The symbol
travelled alongside as logging metadata the model never saw, so a run over
``AAPL, MSFT`` produced byte-identical prompts for both targets -- each
containing both stocks -- and asked the model to infer which one it was
analysing.  A runtime probe hashed the formatted analyst input per target and
got the same digest for both::

    PER_SYMBOL_INPUT_HASH { 'AAPL': '42bb...e485', 'MSFT': '42bb...e485',
                            'equal': True }

Attribution on every deep-dive recommendation was therefore unreliable.
"""

from __future__ import annotations

import copy
import hashlib
import logging
from datetime import date, timedelta

import pytest

from analysis.agents.risk_analyst import format_risk_context
from analysis.agents.sector_strategist import format_sector_context
from analysis.agents.technical_analyst import format_technical_context
from analysis.autonomous_engine import AutonomousDeepEngine
from analysis.price_freshness import build_freshness
from analysis.symbol_slice import (
    PEER_HEADING,
    partition_by_freshness,
    slice_context_for_symbol,
)

# The three analysts the autonomous deep dive actually runs per symbol.
FORMATTERS = {
    "technical": format_technical_context,
    "sector": format_sector_context,
    "risk": format_risk_context,
}

# The heading the peer block is rendered under.  Data above it belongs to the
# target; data below it is explicitly labelled as somebody else's.
PEER_MARKER = f"## {PEER_HEADING}"

AS_OF = date(2026, 8, 10)  # Monday
LAST_BAR = date(2026, 8, 7)  # the preceding Friday -- one trading day old


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------

def _bars(close: float, count: int = 25, latest: date = LAST_BAR) -> list[dict]:
    """``count`` newest-first daily bars, each symbol at its own price level."""
    return [
        {
            "date": (latest - timedelta(days=i)).isoformat(),
            "open": close - 1 - i,
            "high": close + 2 - i,
            "low": close - 3 - i,
            "close": close - i,
            "volume": 1_000_000 + i,
            "adjusted_close": close - i,
            "source": "db_close",
        }
        for i in range(count)
    ]


def _fresh(symbol: str, close: float) -> dict:
    return build_freshness(symbol, LAST_BAR, close, "db_close", as_of=AS_OF)


def _stale(symbol: str, close: float) -> dict:
    return build_freshness(
        symbol, date(2026, 6, 1), close, "db_close", as_of=AS_OF,
        reason="live quote unavailable",
    )


def _two_symbol_context() -> dict:
    """A context covering AAPL and MSFT, as the deep dive pre-builds it."""
    return {
        "timestamp": "2026-08-10T12:00:00",
        "stocks": [
            {"symbol": "AAPL", "name": "Apple Inc.", "sector": "Technology"},
            {"symbol": "MSFT", "name": "Microsoft Corp.", "sector": "Technology"},
        ],
        "price_history": {"AAPL": _bars(190.0), "MSFT": _bars(410.0)},
        "price_freshness": {
            "AAPL": _fresh("AAPL", 190.0),
            "MSFT": _fresh("MSFT", 410.0),
        },
        "technical_indicators": {
            "AAPL": {"rsi": {"value": 61.0}, "atr": {"value": 4.0}},
            "MSFT": {"rsi": {"value": 44.0}, "atr": {"value": 9.0}},
        },
        "fundamentals": {
            "AAPL": {"pe_ratio": 31.2, "market_cap": 3_000_000_000_000},
            "MSFT": {"pe_ratio": 35.8, "market_cap": 3_100_000_000_000},
        },
        "economic_indicators": [
            {"name": "Fed Funds Rate", "value": 4.25, "unit": "%"},
        ],
        "sector_performance": {
            "XLK": {
                "sector": "Technology",
                "name": "Technology Select Sector SPDR",
                "current_price": 250.0,
                "as_of": LAST_BAR.isoformat(),
                "daily_change_pct": 0.5,
                "weekly_change_pct": 1.2,
                "monthly_change_pct": 3.4,
                "volume": 9_000_000,
            },
        },
        "market_summary": {
            "market_index": {
                "symbol": "SPY",
                "current": 600.0,
                "date": LAST_BAR.isoformat(),
                "change_pct": 0.3,
                "volume": 80_000_000,
                "high": 601.0,
                "low": 598.0,
            },
        },
    }


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture()
def captured_payloads(monkeypatch):
    """Run the real per-symbol path, capturing each analyst's LLM payload.

    Returns a callable taking a list of symbols and the shared context, and
    giving back ``{(symbol, analyst_name): user_prompt}``.
    """

    async def _run(symbols: list[str], context: dict) -> dict[tuple[str, str], str]:
        engine = AutonomousDeepEngine()
        captured: dict[tuple[str, str], str] = {}

        async def _fake_query_llm(
            system_prompt: str,
            user_prompt: str,
            agent_name: str = "unknown",
            phase: str = "unknown",
            symbol: str = "",
            prompt_preview: str | None = None,
        ) -> str:
            captured[(symbol, agent_name)] = user_prompt
            return '{"confidence": 0.5}'

        monkeypatch.setattr(engine, "_query_llm", _fake_query_llm)

        for symbol in symbols:
            await engine._run_analysts_for_symbol(
                symbol, "## DISCOVERY CONTEXT\nRegime: risk-on.",
                pre_built_context=context,
            )
        return captured

    return _run


# ---------------------------------------------------------------------------
# 1. THE HEADLINE REGRESSION -- per-symbol prompts must not be identical
# ---------------------------------------------------------------------------

async def test_per_symbol_analyst_payloads_differ_between_symbols(captured_payloads):
    """Two targets in one run must not receive byte-identical analyst input.

    Against the old code every digest below matched, exactly as the runtime
    probe found (``'AAPL': '42bb...e485', 'MSFT': '42bb...e485'``).
    """
    context = _two_symbol_context()
    captured = await captured_payloads(["AAPL", "MSFT"], context)

    for analyst in FORMATTERS:
        apple = captured[("AAPL", analyst)]
        microsoft = captured[("MSFT", analyst)]
        assert _digest(apple) != _digest(microsoft), (
            f"{analyst} analyst received identical input for AAPL and MSFT"
        )

    # And the difference is the actual subject, not incidental formatting.
    assert "Apple Inc." in captured[("AAPL", "technical")]
    assert "Microsoft Corp." in captured[("MSFT", "technical")]


@pytest.mark.parametrize("analyst", sorted(FORMATTERS))
async def test_untargeted_formatting_is_identical_for_every_symbol(analyst):
    """The defect itself: with no target, the body cannot distinguish symbols.

    ``format_func(shared_context)`` is the old call.  It returns one string
    naming both stocks, and the deep dive reused it for every target -- which is
    why the probe's two digests matched.  Adding the target is what breaks the
    tie.
    """
    context = _two_symbol_context()
    formatter = FORMATTERS[analyst]

    untargeted = formatter(context)
    assert "AAPL" in untargeted and "MSFT" in untargeted
    # What each of the two targets used to receive, byte for byte.
    assert _digest(formatter(context)) == _digest(untargeted)

    targeted_apple = _digest(formatter(context, target_symbol="AAPL"))
    targeted_microsoft = _digest(formatter(context, target_symbol="MSFT"))
    assert targeted_apple != targeted_microsoft
    assert _digest(untargeted) not in (targeted_apple, targeted_microsoft)


# ---------------------------------------------------------------------------
# 2. A target's own data blocks name exactly one symbol
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("target,other", [("AAPL", "MSFT"), ("MSFT", "AAPL")])
@pytest.mark.parametrize("analyst", sorted(FORMATTERS))
async def test_target_data_blocks_name_only_the_target(analyst, target, other):
    """The other symbol may appear only inside the labelled comparison block."""
    context = _two_symbol_context()
    body = FORMATTERS[analyst](context, target_symbol=target)

    assert PEER_MARKER in body, f"{analyst} rendered no labelled comparison block"

    own_data, _, peer_block = body.partition(PEER_MARKER)
    assert other not in own_data, (
        f"{analyst}: {other} leaked into {target}'s own data blocks"
    )
    assert target in own_data
    # Cross-symbol context is still available -- just attributed.
    assert other in peer_block
    assert "NOT THE TARGET'S DATA" in PEER_HEADING


async def test_peer_block_is_absent_for_a_single_symbol_context():
    """Nothing to compare against means no empty heading."""
    context = _two_symbol_context()
    single = slice_context_for_symbol(context, "AAPL")

    body = format_technical_context(single, target_symbol="AAPL")
    assert PEER_MARKER in body  # AAPL's slice still carries MSFT as a peer

    context["price_history"].pop("MSFT")
    context["price_freshness"].pop("MSFT")
    context["stocks"] = [s for s in context["stocks"] if s["symbol"] != "MSFT"]
    body = format_technical_context(context, target_symbol="AAPL")
    assert PEER_MARKER not in body


# ---------------------------------------------------------------------------
# 3. The target is stated in-band, at the top of every payload
# ---------------------------------------------------------------------------

async def test_every_analyst_payload_starts_with_its_target(captured_payloads):
    """The symbol must not travel only as LLM metadata the model never sees."""
    context = _two_symbol_context()
    captured = await captured_payloads(["AAPL", "MSFT"], context)

    assert len(captured) == len(FORMATTERS) * 2
    for (symbol, analyst), payload in captured.items():
        assert payload.startswith(f"TARGET SYMBOL: {symbol}"), (
            f"{analyst} payload for {symbol} did not lead with its target"
        )


@pytest.mark.parametrize("analyst", sorted(FORMATTERS))
async def test_formatted_body_leads_with_the_target(analyst):
    context = _two_symbol_context()
    body = FORMATTERS[analyst](context, target_symbol="MSFT")
    assert body.startswith("TARGET SYMBOL: MSFT")


# ---------------------------------------------------------------------------
# 4. Slicing must not mutate the shared (TTL-cached) context
# ---------------------------------------------------------------------------

async def test_slicer_does_not_mutate_the_shared_context():
    """build_context() serves a cached dict -- slicing must copy, never mutate."""
    context = _two_symbol_context()
    before = copy.deepcopy(context)

    apple = slice_context_for_symbol(context, "AAPL")
    microsoft = slice_context_for_symbol(context, "MSFT")

    assert context == before, "slicing mutated the shared context"

    for block in ("price_history", "price_freshness", "technical_indicators",
                  "fundamentals"):
        assert set(apple[block]) == {"AAPL"}
        assert set(microsoft[block]) == {"MSFT"}
    assert [s["symbol"] for s in apple["stocks"]] == ["AAPL"]
    assert [s["symbol"] for s in microsoft["stocks"]] == ["MSFT"]

    # Copy depth, pinned: the freshness record is the slice's own, every other
    # nested value is shared by reference and must be treated as read-only.
    assert apple["price_freshness"]["AAPL"] is not context["price_freshness"]["AAPL"]
    assert apple["price_history"]["AAPL"] is context["price_history"]["AAPL"]

    # Each slice owns its own containers.
    apple["price_history"]["INJECTED"] = []
    apple["stocks"].append({"symbol": "INJECTED"})
    assert "INJECTED" not in microsoft["price_history"]
    assert [s["symbol"] for s in microsoft["stocks"]] == ["MSFT"]
    assert context == before


async def test_market_wide_blocks_stay_shared():
    """Macro, sector and benchmark data are not symbol-specific -- keep them."""
    context = _two_symbol_context()
    apple = slice_context_for_symbol(context, "AAPL")

    assert apple["economic_indicators"] == context["economic_indicators"]
    assert apple["sector_performance"] == context["sector_performance"]
    assert apple["market_summary"] == context["market_summary"]
    assert apple["timestamp"] == context["timestamp"]
    assert apple["target_symbol"] == "AAPL"


async def test_slicing_an_already_sliced_context_is_a_no_op():
    """The formatters re-slice defensively; that must not drop the peer block."""
    context = _two_symbol_context()
    once = slice_context_for_symbol(context, "AAPL")
    twice = slice_context_for_symbol(once, "AAPL")

    assert twice["peer_comparison"] == once["peer_comparison"]
    assert [p["symbol"] for p in twice["peer_comparison"]["peers"]] == ["MSFT"]


# ---------------------------------------------------------------------------
# 5. Symbols without a usable price snapshot are dropped
# ---------------------------------------------------------------------------

async def test_stale_and_missing_symbols_are_dropped_with_a_reason(caplog):
    """Stale data cannot support entry/stop/target levels -- do not analyse it."""
    context = _two_symbol_context()
    context["price_freshness"]["MSFT"] = _stale("MSFT", 410.0)
    # NVDA has no snapshot at all.
    context["price_freshness"]["NVDA"] = build_freshness(
        "NVDA", None, None, "db_close", as_of=AS_OF, reason="no bars ingested",
    )

    with caplog.at_level(logging.WARNING, logger="analysis.symbol_slice"):
        usable, dropped = partition_by_freshness(["AAPL", "MSFT", "NVDA"], context)

    assert usable == ["AAPL"]
    assert [symbol for symbol, _ in dropped] == ["MSFT", "NVDA"]

    reasons = dict(dropped)
    assert "stale" in reasons["MSFT"]
    assert "2026-06-01" in reasons["MSFT"]
    assert "missing" in reasons["NVDA"]

    assert "MSFT" in caplog.text and "stale" in caplog.text
    assert "NVDA" in caplog.text


async def test_refreshed_symbols_are_kept():
    """A stale bar that was successfully re-quoted is usable again."""
    context = _two_symbol_context()
    context["price_freshness"]["MSFT"] = build_freshness(
        "MSFT", LAST_BAR, 410.0, "live_quote", as_of=AS_OF, refreshed=True,
    )

    usable, dropped = partition_by_freshness(["AAPL", "MSFT"], context)

    assert usable == ["AAPL", "MSFT"]
    assert dropped == []


async def test_an_unavailable_macro_feed_reaches_the_macro_scanner(monkeypatch):
    """A failed macro-news fetch must be stated, not rendered as silence.

    The gate used to require ``article_count``, which an unavailable record
    leaves at 0 -- so during a feed outage the MacroScanner heard nothing and
    could read the quiet as a calm news backdrop.
    """
    engine = AutonomousDeepEngine()
    unavailable = {
        "available": False,
        "data_status": "error",
        "article_count": 0,
        "label": None,
        "by_topic": {},
    }

    async def _fake_macro_news(days: int = 3):
        return unavailable

    monkeypatch.setattr(
        "analysis.news_intelligence.get_macro_news_intelligence", _fake_macro_news,
    )

    seen: dict = {}

    async def _fake_scan(context=None):
        seen["context"] = context
        raise RuntimeError("stop after the gate")

    monkeypatch.setattr(engine.macro_scanner, "scan", _fake_scan)

    try:
        await engine._run_macro_scan()
    except Exception:
        pass  # the scan itself is out of scope; the gate is what is under test

    assert seen["context"] is not None, "unavailable macro news never reached the scanner"
    assert seen["context"]["macro_news"] is unavailable


async def test_dropping_every_candidate_leaves_an_empty_list_not_a_crash():
    """A full data outage degrades to "analyse nothing", not to bad prices."""
    context = _two_symbol_context()
    context["price_freshness"] = {
        "AAPL": _stale("AAPL", 190.0),
        "MSFT": _stale("MSFT", 410.0),
    }

    usable, dropped = partition_by_freshness(["AAPL", "MSFT"], context)

    assert usable == []
    assert len(dropped) == 2


# ---------------------------------------------------------------------------
# 6. Symbol case must not decide whether a candidate is analysed
# ---------------------------------------------------------------------------

async def test_lower_case_candidates_are_not_dropped_from_a_healthy_context():
    """The context builder keys every block upper-case; candidates may not be.

    ``heatmap_analyzer`` builds each selection straight from the model's JSON,
    so a run can reach this gate holding "aapl".  Against the exact-key lookup
    that symbol was dropped as "no price snapshot in context" off a context
    carrying fresh, complete data -- and a run where every pick was affected
    reported a price-ETL outage that had not happened.
    """
    context = _two_symbol_context()

    usable, dropped = partition_by_freshness(["aapl", "Msft"], context)

    assert dropped == [], f"case alone dropped a healthy symbol: {dropped}"
    assert usable == ["aapl", "Msft"]


async def test_lower_case_symbol_resolves_to_the_same_snapshot():
    """The record found for "aapl" is the one stored under "AAPL"."""
    from analysis.price_freshness import resolve_snapshot

    context = _two_symbol_context()

    assert resolve_snapshot(context, "aapl") == resolve_snapshot(context, "AAPL")
    assert resolve_snapshot(context, "aapl")["status"] == "fresh"


async def test_a_stale_symbol_is_still_dropped_whatever_its_case():
    """Normalising case must not turn the freshness gate off."""
    context = _two_symbol_context()
    context["price_freshness"]["MSFT"] = _stale("MSFT", 410.0)

    usable, dropped = partition_by_freshness(["aapl", "msft"], context)

    assert usable == ["aapl"]
    assert [symbol for symbol, _ in dropped] == ["msft"]


def test_heatmap_selections_are_upper_cased_at_the_json_boundary():
    """The symbol enters from LLM JSON and is used as a context lookup key."""
    from analysis.agents.heatmap_analyzer import parse_heatmap_analysis_response

    parsed = parse_heatmap_analysis_response(
        '{"overview": "o", "selected_stocks": ['
        '{"symbol": "aapl", "sector": "Technology", "reason": "r",'
        ' "opportunity_type": "momentum", "priority": "high",'
        ' "expected_insight_value": 0.8},'
        '{"symbol": " Msft ", "sector": "Technology", "reason": "r",'
        ' "opportunity_type": "momentum", "priority": "low",'
        ' "expected_insight_value": 0.4}], "confidence": 0.6}'
    )

    assert [s.symbol for s in parsed.selected_stocks] == ["AAPL", "MSFT"]


# ---------------------------------------------------------------------------
# 7. Copy depth: the freshness record a slice carries is its own
# ---------------------------------------------------------------------------

async def test_mutating_a_slices_freshness_record_does_not_reach_the_context():
    """Slices are consumed concurrently off a TTL-cached context.

    The slicer copies containers one level deep, so a formatter that annotated
    ``slice["price_freshness"][SYM]`` used to write straight through to the
    cached context and every other symbol's slice.  The freshness record is
    copied precisely because it is the block most likely to be annotated.
    """
    context = _two_symbol_context()
    original = context["price_freshness"]["AAPL"]

    apple = slice_context_for_symbol(context, "AAPL")
    assert apple["price_freshness"]["AAPL"] is not original

    apple["price_freshness"]["AAPL"]["status"] = "POISONED"
    apple["price_freshness"]["AAPL"]["price"] = 0.0

    assert original["status"] == "fresh"
    assert original["price"] == 190.0
    assert context["price_freshness"]["AAPL"]["status"] == "fresh"

    # And a second slice taken afterwards is unaffected.
    again = slice_context_for_symbol(context, "AAPL")
    assert again["price_freshness"]["AAPL"]["status"] == "fresh"
