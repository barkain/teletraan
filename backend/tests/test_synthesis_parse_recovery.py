"""Tests for synthesis response JSON recovery.

Regression: a production discovery run completed with zero insights because
the LLM emitted '},"{"' between two insight array elements (a stray quote),
making the whole 21KB document unparseable — all insights were dropped.
"""

import json

from analysis.agents.synthesis_lead import (
    _repair_llm_json,
    _salvage_insight_objects,
    parse_synthesis_response,
)


def _insight_json(symbol: str, title: str = "Title") -> str:
    return json.dumps(
        {
            "insight_type": "opportunity",
            "action": "BUY",
            "title": title,
            "thesis": f"Thesis for {symbol}",
            "primary_symbol": symbol,
            "confidence": 0.6,
        }
    )


def test_valid_json_unchanged():
    doc = f'{{"insights": [{_insight_json("NVDA")}, {_insight_json("META")}]}}'
    insights = parse_synthesis_response(doc)
    assert [i["primary_symbol"] for i in insights] == ["NVDA", "META"]


def test_stray_quote_between_objects_repaired():
    # The exact production glitch: '},"{"' where '},{"' was intended.
    a, b = _insight_json("NVDA"), _insight_json("GS")
    glitched = f'{{"insights": [{a},"{b}]}}'
    assert '},"{"' in glitched.replace(" ", "")
    insights = parse_synthesis_response(glitched)
    assert [i["primary_symbol"] for i in insights] == ["NVDA", "GS"]


def test_repair_helper_targets_only_the_glitch():
    glitched = '{"insights": [{"a": 1}, "{"b": 2}]}'
    repaired = _repair_llm_json(glitched)
    assert '},{"' in repaired.replace(" ", "")
    # Normal JSON is left alone.
    clean = '{"insights": [{"a": 1}, {"b": 2}]}'
    assert _repair_llm_json(clean) == clean


def test_salvage_recovers_valid_objects_around_corrupted_one():
    a, b, c = _insight_json("NVDA"), _insight_json("GS"), _insight_json("KMB")
    # Middle object is truncated — unrepairable.
    broken = b[: len(b) // 2]
    doc = f'{{"insights": [{a}, {broken}, {c}]}}'
    salvaged = _salvage_insight_objects(doc)
    assert [o["primary_symbol"] for o in salvaged] == ["NVDA", "KMB"]


def test_parse_falls_back_to_salvage():
    a, c = _insight_json("NVDA"), _insight_json("KMB")
    # Corruption that the repair regex cannot fix (unbalanced brace garbage
    # between objects) — whole-document parse fails, salvage must kick in.
    doc = f'{{"insights": [{a}, {{"insight_type": "broken", {c}]}}'
    insights = parse_synthesis_response(doc)
    assert [i["primary_symbol"] for i in insights] == ["NVDA", "KMB"]


def test_no_insights_anywhere_returns_empty():
    assert parse_synthesis_response("complete garbage, no JSON at all") == []
    assert _salvage_insight_objects("nothing here") == []
