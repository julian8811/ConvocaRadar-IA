"""Scraper probe — health check for source connectors.

Usage
-----
    report = await run_probe(db)
    report = await run_probe(db, source_key="minciencias")
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field, asdict
from datetime import UTC, datetime

from sqlalchemy import select

from app.connectors.factory import connector_for
from app.models import Source


# ---------------------------------------------------------------------------
# Probe result types
# ---------------------------------------------------------------------------


@dataclass
class ProbeResult:
    """Result of probing a single source connector.

    Parameters
    ----------
    source_key:
        The source's unique key (e.g. "minciencias", "grants-gov").
    status:
        GREEN — candidates found; YELLOW — connector responded but 0 candidates;
        RED — connector raised an exception during fetch/parse.
    candidates_count:
        Number of candidates parsed (None if the probe did not reach parsing).
    error_message:
        Error message if status is RED; None otherwise.
    elapsed_seconds:
        Wall-clock time in seconds that the probe took.
    """

    source_key: str
    status: str  # "GREEN" | "YELLOW" | "RED"
    candidates_count: int | None
    error_message: str | None
    elapsed_seconds: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProbeReport:
    """Aggregated report from probing one or more sources.

    Parameters
    ----------
    total:
        Number of sources probed.
    green:
        Count of GREEN results.
    yellow:
        Count of YELLOW results.
    red:
        Count of RED results.
    results:
        Individual ProbeResult per source.
    started_at:
        ISO-8601 timestamp when the probe started.
    finished_at:
        ISO-8601 timestamp when the probe finished.
    """

    total: int
    green: int
    yellow: int
    red: int
    results: list[ProbeResult] = field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "green": self.green,
            "yellow": self.yellow,
            "red": self.red,
            "results": [r.to_dict() for r in self.results],
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


# ---------------------------------------------------------------------------
# Probe runner
# ---------------------------------------------------------------------------

_PROBE_TIMEOUT = 30  # seconds per source (was 15, increased for slow sites)

# Per-source timeout overrides (slow JS-heavy sites, d003 fix-probe-yellow-red)
_PROBE_TIMEOUT_OVERRIDES: dict[str, int] = {
    "minciencias": 45,
    "findeter-convocatorias": 60,
    "findeter": 60,  # legacy key alias
    "caricom-procurement": 60,
    "caricom": 60,
    "unesco-call-for-proposals": 60,
    "agencia-id-argentina": 45,
}


def _probe_timeout_for(source_key: str) -> int:
    return _PROBE_TIMEOUT_OVERRIDES.get(source_key, _PROBE_TIMEOUT)


async def _probe_one_source(
    source: Source,
) -> ProbeResult:
    """Probe a single source connector.

    Calls ``connector_for(source.key, ...)`` → ``fetch()`` → ``parse()``
    with a 15-second timeout.
    """
    source_key = source.key
    start = time.monotonic()

    try:
        connector = connector_for(
            source_key,
            source.base_url,
            source.source_type,
            entity_name=source.name,
            default_country=source.country,
            default_categories=source.category,
            connector_config=source.connector_config,
        )

        timeout = _probe_timeout_for(source_key)
        # Fetch with timeout
        raw = await asyncio.wait_for(
            connector.fetch(),
            timeout=timeout,
        )

        # Parse with timeout
        candidates = await asyncio.wait_for(
            connector.parse(raw),
            timeout=timeout,
        )

        elapsed = time.monotonic() - start
        count = len(candidates)
        if count > 0:
            return ProbeResult(
                source_key=source_key,
                status="GREEN",
                candidates_count=count,
                error_message=None,
                elapsed_seconds=round(elapsed, 3),
            )
        return ProbeResult(
            source_key=source_key,
            status="YELLOW",
            candidates_count=0,
            error_message=None,
            elapsed_seconds=round(elapsed, 3),
        )

    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start
        timeout = _probe_timeout_for(source_key)
        return ProbeResult(
            source_key=source_key,
            status="RED",
            candidates_count=None,
            error_message=f"Probe timed out after {timeout}s",
            elapsed_seconds=round(elapsed, 3),
        )
    except Exception as exc:
        elapsed = time.monotonic() - start
        return ProbeResult(
            source_key=source_key,
            status="RED",
            candidates_count=None,
            error_message=str(exc)[:500] if str(exc) else type(exc).__name__,
            elapsed_seconds=round(elapsed, 3),
        )


async def _probe_with_budget(
    source: Source,
    semaphore: asyncio.Semaphore,
) -> ProbeResult:
    """Acquire semaphore then probe the source.

    Domain budget is NOT acquired here — fetch_httpx_text / connector
    layer owns the domain slot. Acquiring here caused a double-budget
    deadlock for max_concurrent:1 domains (probe held 1/1, fetch then
    failed to acquire and raised 'Domain budget exhausted'). Production
    runner (runner.py) never acquires at this layer either.
    Fix: d003 remove probe-level domain budget acquire.
    """
    async with semaphore:
        return await _probe_one_source(source)


async def run_probe(
    db,
    source_key: list[str] | None = None,
) -> ProbeReport:
    """Run a probe against enabled sources.

    Parameters
    ----------
    db:
        SQLAlchemy session.
    source_key:
        If provided, only probe sources whose keys are in this list.
        Otherwise, probes all enabled sources.

    Returns
    -------
    ProbeReport
        Aggregated results from all probed sources.
    """
    started_at = datetime.now(UTC)

    query = select(Source).where(Source.enabled.is_(True))
    if source_key:
        query = query.where(Source.key.in_(source_key))

    sources = list(db.scalars(query))

    if not sources:
        finished_at = datetime.now(UTC)
        return ProbeReport(
            total=0,
            green=0,
            yellow=0,
            red=0,
            results=[],
            started_at=started_at,
            finished_at=finished_at,
        )

    # Concurrent probe with semaphore cap
    semaphore = asyncio.Semaphore(5)
    raw_results = await asyncio.gather(
        *[_probe_with_budget(s, semaphore) for s in sources],
        return_exceptions=True,
    )

    # Flatten — _probe_one_source catches everything, but gather may
    # still return an Exception if something truly unexpected leaks out.
    results: list[ProbeResult] = []
    for source, result in zip(sources, raw_results):
        if isinstance(result, Exception):
            results.append(
                ProbeResult(
                    source_key=source.key,
                    status="RED",
                    candidates_count=None,
                    error_message=f"Unexpected probe error: {result}"[:500],
                    elapsed_seconds=0.0,
                )
            )
        else:
            results.append(result)

    finished_at = datetime.now(UTC)

    green = sum(1 for r in results if r.status == "GREEN")
    yellow = sum(1 for r in results if r.status == "YELLOW")
    red = sum(1 for r in results if r.status == "RED")

    return ProbeReport(
        total=len(results),
        green=green,
        yellow=yellow,
        red=red,
        results=results,
        started_at=started_at,
        finished_at=finished_at,
    )
