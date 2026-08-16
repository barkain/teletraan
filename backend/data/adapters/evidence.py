"""Shared evidence contract for signal adapters.

Every adapter answers two different questions and the codebase used to conflate
them: *did the fetch return an object* and *is there anything in it worth
scoring*.  A yfinance ``info`` payload of ``{'trailingPegRatio': None}`` answers
"yes" to the first and "no" to the second; treating it as data is how a missing
signal turns into a confident-looking number.

`Evidence` makes the second question explicit, and `evidence_is_usable()` lets
consumers gate on it without caring which adapter produced the record.

Timestamps: two conventions already exist in this package.  The yfinance-backed
adapters (`options_flow`, `short_interest`, `analyst_revisions`) publish
``as_of``; `prediction_markets` / `polymarket` publish ``fetched_at``.  Nothing
is renamed here -- adapters keep the keys they already emit and *add* the new
ones, so existing consumers keep working.  `Evidence` carries both, with the
distinction they should have had all along:

- ``observed_at`` -- when the underlying data was true (quote/report timestamp)
- ``fetched_at``  -- when we retrieved it
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# Status vocabulary ---------------------------------------------------------
STATUS_OK = "ok"                    # complete, fresh data
STATUS_PARTIAL = "partial"          # some fields/rows present, some missing
STATUS_UNAVAILABLE = "unavailable"  # source responded, but with nothing usable
STATUS_ERROR = "error"              # source failed (exception, timeout, HTTP error)
STATUS_STALE = "stale"              # real data, but older than the caller wants

ALL_STATUSES = (
    STATUS_OK,
    STATUS_PARTIAL,
    STATUS_UNAVAILABLE,
    STATUS_ERROR,
    STATUS_STALE,
)

#: Statuses whose evidence may contribute to a score.  ``stale`` is included --
#: it is real data, just old -- but callers that need freshness should check
#: :attr:`Evidence.is_fresh` instead.
USABLE_STATUSES = frozenset({STATUS_OK, STATUS_PARTIAL, STATUS_STALE})


def utc_now_iso() -> str:
    """UTC timestamp in the format the existing adapters already emit."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class Evidence:
    """A single piece of evidence plus whether it can be trusted for scoring.

    ``coverage`` is the fraction (0-1) of the requested evidence that actually
    arrived: parsed option expiries over requested expiries, populated fields
    over expected fields, symbols returned over symbols asked for.  A record
    with ``coverage == 0`` is never usable, whatever its status says.
    """

    source: str
    status: str = STATUS_UNAVAILABLE
    observed_at: str | None = None
    fetched_at: str | None = None
    coverage: float = 0.0
    value: Any = None
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in ALL_STATUSES:
            raise ValueError(f"unknown evidence status: {self.status!r}")
        self.coverage = max(0.0, min(1.0, float(self.coverage)))

    @property
    def is_usable(self) -> bool:
        """True when this evidence may contribute to a score."""
        return self.status in USABLE_STATUSES and self.coverage > 0.0

    @property
    def is_fresh(self) -> bool:
        """True when the evidence is usable *and* not known to be stale."""
        return self.is_usable and self.status != STATUS_STALE

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "observed_at": self.observed_at,
            "fetched_at": self.fetched_at,
            "coverage": round(self.coverage, 4),
            "usable": self.is_usable,
            "value": self.value,
            "notes": list(self.notes),
        }

    @classmethod
    def unavailable(cls, source: str, *, reason: str, **kwargs: Any) -> Evidence:
        """Convenience constructor for "the source gave us nothing usable"."""
        return cls(
            source=source,
            status=STATUS_UNAVAILABLE,
            fetched_at=kwargs.pop("fetched_at", utc_now_iso()),
            coverage=0.0,
            notes=[reason],
            **kwargs,
        )

    @classmethod
    def error(cls, source: str, *, reason: str, **kwargs: Any) -> Evidence:
        """Convenience constructor for "the fetch failed"."""
        return cls(
            source=source,
            status=STATUS_ERROR,
            fetched_at=kwargs.pop("fetched_at", utc_now_iso()),
            coverage=0.0,
            notes=[reason],
            **kwargs,
        )


def _read(record: Any, key: str) -> Any:
    if isinstance(record, dict):
        return record.get(key)
    return getattr(record, key, None)


def evidence_status(record: Any) -> str:
    """Best-effort status for any adapter record.

    Accepts an :class:`Evidence`, an adapter dataclass, or the plain dict its
    ``to_dict()`` produces.  Adapters that have not been migrated to carry an
    explicit ``status`` are read through their legacy ``available`` flag, so a
    single gate works across the whole package.
    """
    if record is None:
        return STATUS_UNAVAILABLE
    if isinstance(record, dict) and not record:
        return STATUS_UNAVAILABLE

    status = _read(record, "status")
    if isinstance(status, str) and status in ALL_STATUSES:
        return status

    available = _read(record, "available")
    if available is None:
        # No contract at all: a non-empty payload is the only evidence we have.
        return STATUS_OK if record else STATUS_UNAVAILABLE
    return STATUS_OK if bool(available) else STATUS_UNAVAILABLE


def evidence_is_usable(record: Any) -> bool:
    """Whether an adapter record may contribute to a score.

    This is the gate that replaces ``bool(record)`` and ``score > 0`` checks.
    An unavailable record is still a non-empty dict -- it always carries
    ``symbol``/``as_of``/``available`` -- so truthiness proves nothing.
    """
    if evidence_status(record) not in USABLE_STATUSES:
        return False
    coverage = _read(record, "coverage")
    if coverage is not None:
        try:
            return float(coverage) > 0.0
        except (TypeError, ValueError):
            return True
    return True
