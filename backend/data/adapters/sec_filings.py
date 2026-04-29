"""SEC filings adapter for normalized, market-relevant SEC event signals.

This adapter is intentionally deterministic and lightweight:
- map symbols to CIKs using the public company_tickers list
- fetch recent SEC submissions JSON
- normalize material filings into a common structure
- derive a simple, auditable filing signal summary

It is designed to feed the alpha engine and investor intelligence layers
without requiring paid vendors.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp  # type: ignore[import-untyped]

from config import get_settings

logger = logging.getLogger(__name__)

SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

_CACHE_TTL = 60 * 60  # 1 hour
_REQUEST_TIMEOUT = 30
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0
_BACKOFF_FACTOR = 2.0
_CONCURRENCY = 6


def _sec_user_agent() -> str:
    settings = get_settings()
    return settings.SEC_USER_AGENT or "Teletraan/1.0 (market intelligence; ops@example.com)"


class _CacheEntry:
    __slots__ = ("data", "expires_at")

    def __init__(self, data: Any, ttl: float) -> None:
        self.data = data
        self.expires_at = time.monotonic() + ttl

    @property
    def is_valid(self) -> bool:
        return time.monotonic() < self.expires_at


@dataclass
class SECFiling:
    symbol: str
    cik: str
    company_name: str
    form_type: str
    filing_date: str
    accession_number: str
    primary_document: str | None = None
    filing_url: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "cik": self.cik,
            "company_name": self.company_name,
            "form_type": self.form_type,
            "filing_date": self.filing_date,
            "accession_number": self.accession_number,
            "primary_document": self.primary_document,
            "filing_url": self.filing_url,
            "tags": self.tags,
        }


@dataclass
class SECFilingSignal:
    symbol: str
    company_name: str
    cik: str | None
    as_of: str
    signal_score: float
    recent_filing_count: int
    recent_8k_count: int
    insider_activity_count: int
    activism_count: int
    periodic_report_count: int
    days_since_last_filing: int | None
    notable_tags: list[str] = field(default_factory=list)
    filings: list[SECFiling] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "cik": self.cik,
            "as_of": self.as_of,
            "signal_score": self.signal_score,
            "recent_filing_count": self.recent_filing_count,
            "recent_8k_count": self.recent_8k_count,
            "insider_activity_count": self.insider_activity_count,
            "activism_count": self.activism_count,
            "periodic_report_count": self.periodic_report_count,
            "days_since_last_filing": self.days_since_last_filing,
            "notable_tags": self.notable_tags,
            "filings": [f.to_dict() for f in self.filings],
        }


class SECFilingsAdapter:
    """Normalized SEC filings fetcher with symbol->CIK mapping."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._semaphore = asyncio.Semaphore(_CONCURRENCY)
        self._cache: dict[str, _CacheEntry] = {}
        self._ticker_map: dict[str, dict[str, str]] | None = None

    @property
    def is_available(self) -> bool:
        return True

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT),
                headers={"User-Agent": _sec_user_agent(), "Accept": "application/json"},
            )
        return self._session

    def _get_cached(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if entry is not None and entry.is_valid:
            return entry.data
        self._cache.pop(key, None)
        return None

    def _set_cached(self, key: str, data: Any, ttl: float = _CACHE_TTL) -> None:
        self._cache[key] = _CacheEntry(data, ttl)

    async def _fetch_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> Any | None:
        session = await self._ensure_session()
        delay = _BACKOFF_BASE
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with self._semaphore:
                    async with session.get(url, params=params) as resp:
                        if resp.status == 200:
                            return await resp.json(content_type=None)
                        if resp.status == 429:
                            await asyncio.sleep(delay)
                            delay *= _BACKOFF_FACTOR
                            continue
                        logger.warning("SEC HTTP %s from %s", resp.status, url)
            except Exception as exc:
                logger.debug("SEC fetch failed for %s (attempt %d/%d): %s", url, attempt, _MAX_RETRIES, exc)
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(delay)
                delay *= _BACKOFF_FACTOR
        return None

    async def _load_ticker_map(self) -> dict[str, dict[str, str]]:
        if self._ticker_map is not None:
            return self._ticker_map
        cached = self._get_cached("ticker_map")
        if cached is not None:
            self._ticker_map = cached
            return cached

        raw = await self._fetch_json(SEC_TICKER_MAP_URL)
        mapping: dict[str, dict[str, str]] = {}
        if isinstance(raw, dict):
            for row in raw.values():
                if not isinstance(row, dict):
                    continue
                symbol = str(row.get("ticker") or "").upper()
                cik_str = str(row.get("cik_str") or "").zfill(10)
                title = str(row.get("title") or "")
                if symbol and cik_str:
                    mapping[symbol] = {"cik": cik_str, "company_name": title}

        self._ticker_map = mapping
        self._set_cached("ticker_map", mapping, ttl=24 * 60 * 60)
        return mapping

    async def symbol_to_cik(self, symbol: str) -> tuple[str | None, str]:
        ticker_map = await self._load_ticker_map()
        row = ticker_map.get(symbol.upper())
        if not row:
            return None, symbol.upper()
        return row.get("cik"), row.get("company_name") or symbol.upper()

    @staticmethod
    def _tag_filing(form_type: str) -> list[str]:
        form = form_type.upper().strip()
        tags: list[str] = []
        if form in {"4", "4/A"}:
            tags.append("insider_activity")
        if form in {"13D", "13D/A", "SC 13D", "SC 13D/A"}:
            tags.append("activism")
        if form in {"13G", "13G/A", "SC 13G", "SC 13G/A"}:
            tags.append("passive_stake")
        if form == "8-K":
            tags.append("material_event")
        if form in {"10-Q", "10-K"}:
            tags.append("periodic_report")
        return tags

    async def get_recent_filings(
        self,
        symbols: list[str],
        *,
        forms: set[str] | None = None,
        days: int = 180,
        limit_per_symbol: int = 12,
    ) -> list[SECFiling]:
        cache_key = f"filings:{','.join(sorted(s.upper() for s in symbols))}:{days}:{limit_per_symbol}:{','.join(sorted(forms)) if forms else 'all'}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if not symbols:
            return []

        results = await asyncio.gather(
            *[self._get_symbol_filings(symbol, forms=forms, days=days, limit_per_symbol=limit_per_symbol) for symbol in symbols],
            return_exceptions=True,
        )

        filings: list[SECFiling] = []
        for result in results:
            if isinstance(result, list):
                filings.extend(result)

        filings.sort(key=lambda item: item.filing_date, reverse=True)
        self._set_cached(cache_key, filings)
        return filings

    async def _get_symbol_filings(
        self,
        symbol: str,
        *,
        forms: set[str] | None = None,
        days: int = 180,
        limit_per_symbol: int = 12,
    ) -> list[SECFiling]:
        cik, company_name = await self.symbol_to_cik(symbol)
        if not cik:
            return []

        cache_key = f"symbol:{symbol.upper()}:{days}:{limit_per_symbol}:{','.join(sorted(forms)) if forms else 'all'}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        url = f"{SEC_SUBMISSIONS_BASE}/CIK{cik}.json"
        data = await self._fetch_json(url)
        if not isinstance(data, dict):
            return []

        recent = data.get("filings", {}).get("recent", {}) or {}
        form_list = list(recent.get("form", []) or [])
        filing_dates = list(recent.get("filingDate", []) or [])
        accession_numbers = list(recent.get("accessionNumber", []) or [])
        primary_docs = list(recent.get("primaryDocument", []) or [])

        threshold = datetime.now(timezone.utc) - timedelta(days=days)
        parsed: list[SECFiling] = []
        cik_int = int(cik)

        for idx, form_type in enumerate(form_list):
            form = str(form_type).upper().strip()
            if forms and form not in forms:
                continue
            filing_date = filing_dates[idx] if idx < len(filing_dates) else ""
            try:
                filing_dt = datetime.fromisoformat(filing_date)
            except Exception:
                filing_dt = None
            if filing_dt is not None and filing_dt.replace(tzinfo=timezone.utc) < threshold:
                continue

            accession = accession_numbers[idx] if idx < len(accession_numbers) else ""
            primary_doc = primary_docs[idx] if idx < len(primary_docs) else ""
            accession_no_dashes = accession.replace("-", "")
            filing_url = ""
            if accession_no_dashes and primary_doc:
                filing_url = f"{SEC_ARCHIVES_BASE}/{cik_int}/{accession_no_dashes}/{primary_doc}"

            parsed.append(
                SECFiling(
                    symbol=symbol.upper(),
                    cik=cik,
                    company_name=company_name,
                    form_type=form,
                    filing_date=filing_date,
                    accession_number=accession,
                    primary_document=primary_doc or None,
                    filing_url=filing_url,
                    tags=self._tag_filing(form),
                )
            )
            if len(parsed) >= limit_per_symbol:
                break

        parsed.sort(key=lambda item: item.filing_date, reverse=True)
        self._set_cached(cache_key, parsed)
        return parsed

    def _score_from_filings(self, filings: list[SECFiling]) -> tuple[float, dict[str, int], list[str], int | None]:
        if not filings:
            return 0.0, {"recent": 0, "8k": 0, "insider": 0, "activism": 0, "periodic": 0}, [], None

        recent_8k = 0
        insider = 0
        activism = 0
        periodic = 0
        notable_tags: list[str] = []
        latest_date: datetime | None = None

        for filing in filings:
            if filing.filing_date:
                try:
                    filed = datetime.fromisoformat(filing.filing_date)
                    if latest_date is None or filed > latest_date:
                        latest_date = filed
                except Exception:
                    pass
            if "material_event" in filing.tags:
                recent_8k += 1
                notable_tags.append("8k")
            if "insider_activity" in filing.tags:
                insider += 1
                notable_tags.append("insider")
            if "activism" in filing.tags:
                activism += 1
                notable_tags.append("activism")
            if "periodic_report" in filing.tags:
                periodic += 1
                notable_tags.append("periodic")

        days_since_last = None
        if latest_date is not None:
            days_since_last = max(0, (datetime.now(timezone.utc) - latest_date.replace(tzinfo=timezone.utc)).days)

        score = 0.0
        score += min(25.0, recent_8k * 8.0)
        score += min(30.0, insider * 10.0)
        score += min(25.0, activism * 12.0)
        score += min(15.0, periodic * 3.0)
        if days_since_last is not None:
            score += max(0.0, 15.0 - min(days_since_last / 7.0, 15.0))

        return min(100.0, score), {
            "recent": len(filings),
            "8k": recent_8k,
            "insider": insider,
            "activism": activism,
            "periodic": periodic,
        }, list(dict.fromkeys(notable_tags)), days_since_last

    async def get_symbol_signal(
        self,
        symbol: str,
        *,
        days: int = 180,
        limit_per_symbol: int = 12,
    ) -> SECFilingSignal:
        filings = await self._get_symbol_filings(
            symbol,
            days=days,
            limit_per_symbol=limit_per_symbol,
        )
        cik, company_name = await self.symbol_to_cik(symbol)
        score, counts, notable_tags, days_since_last = self._score_from_filings(filings)
        return SECFilingSignal(
            symbol=symbol.upper(),
            company_name=company_name,
            cik=cik,
            as_of=datetime.now(timezone.utc).isoformat(),
            signal_score=round(score, 2),
            recent_filing_count=counts["recent"],
            recent_8k_count=counts["8k"],
            insider_activity_count=counts["insider"],
            activism_count=counts["activism"],
            periodic_report_count=counts["periodic"],
            days_since_last_filing=days_since_last,
            notable_tags=notable_tags,
            filings=filings,
        )

    async def get_symbol_signals(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        if not symbols:
            return {}
        results = await asyncio.gather(
            *[self.get_symbol_signal(symbol) for symbol in symbols],
            return_exceptions=True,
        )
        signals: dict[str, dict[str, Any]] = {}
        for result in results:
            if isinstance(result, SECFilingSignal):
                signals[result.symbol] = result.to_dict()
        return signals

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None


_adapter_instance: SECFilingsAdapter | None = None


def get_sec_filings_adapter() -> SECFilingsAdapter:
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = SECFilingsAdapter()
    return _adapter_instance

