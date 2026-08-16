"""The shared evidence contract in data/adapters/evidence.py."""

from __future__ import annotations

import pytest


def test_usable_only_when_status_and_coverage_agree():
    from data.adapters.evidence import Evidence

    ok = Evidence(source="test", status="ok", coverage=1.0, value=42)
    assert ok.is_usable is True
    assert ok.is_fresh is True

    # Status alone is not enough: zero coverage means nothing arrived.
    assert Evidence(source="test", status="ok", coverage=0.0).is_usable is False
    assert Evidence(source="test", status="partial", coverage=0.25).is_usable is True
    assert Evidence(source="test", status="unavailable", coverage=1.0).is_usable is False
    assert Evidence(source="test", status="error", coverage=1.0).is_usable is False

    stale = Evidence(source="test", status="stale", coverage=1.0)
    assert stale.is_usable is True  # real data, just old
    assert stale.is_fresh is False


def test_unknown_status_is_rejected():
    from data.adapters.evidence import Evidence

    with pytest.raises(ValueError):
        Evidence(source="test", status="probably_fine")


def test_to_dict_exposes_the_usability_verdict():
    from data.adapters.evidence import Evidence

    payload = Evidence(
        source="yfinance",
        status="partial",
        observed_at="2026-08-06T00:00:00Z",
        fetched_at="2026-08-06T01:00:00Z",
        coverage=0.5,
        value={"x": 1},
    ).to_dict()

    assert payload["usable"] is True
    assert payload["coverage"] == 0.5
    assert payload["observed_at"] != payload["fetched_at"]


def test_evidence_is_usable_reads_legacy_and_new_records():
    from data.adapters.evidence import evidence_is_usable

    # Empty / missing.
    assert evidence_is_usable(None) is False
    assert evidence_is_usable({}) is False

    # An unavailable adapter record is still a non-empty dict -- that is exactly
    # what made `bool(record)` the wrong gate.
    assert evidence_is_usable(
        {"symbol": "AAPL", "as_of": "2026-08-06T00:00:00Z", "available": False, "notes": ["no_data"]}
    ) is False

    # Legacy record with no status field: fall back to `available`.
    assert evidence_is_usable({"symbol": "AAPL", "available": True}) is True

    # New-style record: status plus coverage.
    assert evidence_is_usable({"status": "ok", "coverage": 1.0}) is True
    assert evidence_is_usable({"status": "ok", "coverage": 0.0}) is False
    assert evidence_is_usable({"status": "error", "coverage": 0.0}) is False


def test_adapter_records_satisfy_the_contract():
    """The three fixed adapters must be readable through the shared gate."""
    from data.adapters.analyst_revisions import AnalystRevisionAdapter
    from data.adapters.evidence import evidence_is_usable
    from data.adapters.options_flow import OptionsFlowAdapter
    from data.adapters.short_interest import ShortInterestAdapter

    empties = [
        OptionsFlowAdapter._empty_signal("TEST", status="unavailable", note="no_expirations"),
        ShortInterestAdapter._empty_signal("TEST", note="no_short_interest_fields"),
        AnalystRevisionAdapter._empty_signal("TEST", note="no_analyst_coverage"),
    ]
    for signal in empties:
        assert evidence_is_usable(signal) is False
        assert evidence_is_usable(signal.to_dict()) is False
        # Legacy keys stay in place for existing consumers.
        assert "as_of" in signal.to_dict()
        assert signal.to_dict()["available"] is False
