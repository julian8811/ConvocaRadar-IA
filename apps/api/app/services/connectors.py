"""Connector factory and scraping execution functions.

Extracted from ``_legacy.py`` (PR C-1). Provides the connector dispatch
function, scraping frequency checks, and async scraping execution with
timeout support.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Source
from app.schemas import OpportunityCreate
from app.services.dedup import candidate_external_id
from app.services.validation import is_noise_payload


def connector_for(
    source_key: str,
    base_url: str | None = None,
    source_type: str | None = None,
    *,
    entity_name: str | None = None,
    default_country: str | None = None,
    default_categories: list[str] | None = None,
    connector_config: dict | None = None,
):
    from app.connectors.factory import connector_for as worker_connector_for

    return worker_connector_for(
        source_key,
        base_url,
        source_type,
        entity_name=entity_name,
        default_country=default_country,
        default_categories=default_categories,
        connector_config=connector_config,
    )


SLOW_SCRAPE_SOURCE_KEYS = frozenset(
    {
        "innovamos-global-innovation-fund",
        "innovamos-fid",
        "eu-funding-tenders",
        "minciencias",
        "ukri-opportunities",
        "horizon-europe-sedia",
        "eic-accelerator",
        "procolombia-convocatorias",
        # PR5 follow-up: apc-colombia's HTML page is heavy enough to timeout
        # under Render free's 30-90s scraping window. Regression test
        # apps/api/tests/test_sources.py::test_apc_colombia_is_classified_as_slow_source
        # pins this entry.
        "apc-colombia",
    }
)
SLOW_SCRAPE_SOURCE_TYPES = frozenset({"hybrid"})


def is_slow_scrape_source(source: Source) -> bool:
    return source.key in SLOW_SCRAPE_SOURCE_KEYS or (source.source_type or "") in SLOW_SCRAPE_SOURCE_TYPES


def source_due_for_scraping(source: Source, *, now: datetime | None = None) -> bool:
    current = now or datetime.now(UTC).replace(tzinfo=None)
    frequency = (source.scraping_frequency or "daily").lower()
    if frequency in {"hourly", "every_hour", "daily", "every_day"}:
        return True
    if not source.last_run_at:
        return True
    elapsed = current - source.last_run_at
    if frequency in {"weekly", "every_week"}:
        return elapsed >= timedelta(days=7)
    if frequency in {"monthly", "every_month"}:
        return elapsed >= timedelta(days=28)
    return elapsed >= timedelta(days=1)


async def _scrape_source_candidates(
    source: Source, stats: dict[str, object] | None = None
) -> list[OpportunityCreate]:
    connector = connector_for(
        source.key,
        source.base_url,
        source.source_type,
        entity_name=source.name,
        default_country=source.country,
        default_categories=source.category,
    )
    raw = await connector.fetch()
    if stats is not None:
        stats["raw_url"] = raw.url
        stats["raw_content_type"] = raw.content_type
        stats["raw_content_length"] = len(raw.content or "")
    candidates = await connector.parse(raw)
    if not candidates and source.key in {
        "grants-gov",
        "grants-gov-rss",
        "grants-gov-forecast",
        "simpler-grants",
    }:
        fallback_connector = connector_for(source.key, None, source.source_type)
        fallback_raw = await fallback_connector.fetch()
        fallback_candidates = await fallback_connector.parse(fallback_raw)
        if stats is not None:
            stats["fallback_raw_url"] = fallback_raw.url
            stats["fallback_raw_content_type"] = fallback_raw.content_type
            stats["fallback_raw_content_length"] = len(fallback_raw.content or "")
            stats["fallback_candidates_parsed"] = len(fallback_candidates)
        if fallback_candidates:
            connector = fallback_connector
            candidates = fallback_candidates
    if stats is not None:
        stats["candidates_parsed"] = len(candidates)
    opportunities: list[OpportunityCreate] = []
    noise_rejected = 0
    validation_rejected = 0
    validation_reasons: list[str] = []
    for candidate in candidates:
        if is_noise_payload(candidate.title, candidate.summary, candidate.raw_text):
            noise_rejected += 1
            continue
        validation = await connector.validate(candidate)
        if not validation.ok:
            validation_rejected += 1
            if len(validation_reasons) < 5:
                validation_reasons.append(validation.reason or "sin razon")
            continue
        opportunities.append(
            OpportunityCreate(
                source_id=source.id,
                external_id=candidate_external_id(
                    source, candidate.official_url, candidate.title, candidate.raw_text or ""
                ),
                title=candidate.title,
                entity=candidate.entity,
                country=candidate.country,
                region=source.region,
                language=candidate.language,
                categories=candidate.categories,
                topics=candidate.topics,
                description=candidate.summary or candidate.title,
                summary=candidate.summary or candidate.title,
                raw_text=candidate.raw_text,
                official_url=candidate.official_url,
                open_date=candidate.open_date,
                close_date=candidate.close_date,
                funding_amount_raw=candidate.funding_amount_raw,
                requirements=candidate.requirements,
                confidence_score=candidate.confidence_score,
            )
        )
    if stats is not None:
        stats["noise_rejected"] = noise_rejected
        stats["validation_rejected"] = validation_rejected
        stats["validation_reasons"] = validation_reasons
        stats["opportunities_normalized"] = len(opportunities)
    return opportunities


async def _scrape_source_candidates_with_timeout(
    source: Source, stats: dict[str, object] | None = None
) -> list[OpportunityCreate]:
    settings = get_settings()
    timeout_seconds = max(settings.scraping_max_source_seconds, 30)
    timeout_seconds = min(timeout_seconds, int(settings.per_connector_timeout_seconds))
    try:
        return await asyncio.wait_for(
            _scrape_source_candidates(source, stats), timeout=timeout_seconds
        )
    except TimeoutError as exc:
        raise TimeoutError(
            f"Scrape for source {source.key} exceeded {timeout_seconds}s"
        ) from exc


def execute_source_run_locally(
    db: Session, source: Source, organization_id: str | None = None
) -> object:
    """Thin sync wrapper — delegates to app.scraper.runner.run_source_inline.

    FastAPI sync endpoints run in a thread pool.  ``asyncio.run()`` in a
    thread can deadlock with the parent event loop on some platforms, so
    we use an explicit fresh loop (same pattern as the original).
    """
    from app.scraper.runner import run_source_inline

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run_source_inline(db, source, organization_id))
    finally:
        loop.close()
