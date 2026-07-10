"""Inline scraper runner — extracted from app.services.

Phase 1: pure extraction of scraping lifecycle. No Redis, no Celery.
Phase 2: services.py will call this module via thin wrappers.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.core.config import get_settings
from app.models import Source, SourceRun, Task
from app.schemas import OpportunityCreate
from app.services import (
    candidate_external_id,
    create_opportunity,
    create_source_health_alert,
    is_noise_payload,
    validate_source_url,
)


async def _scrape_candidates(
    source: Source, stats: dict[str, object] | None = None
) -> list[OpportunityCreate]:
    """Extracted from services._scrape_source_candidates.

    Fetches raw data from the source connector, parses candidates,
    filters noise, validates, and normalizes into OpportunityCreate list.
    """
    from app.connectors.factory import connector_for

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
                    source,
                    candidate.official_url,
                    candidate.title,
                    candidate.raw_text or "",
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
    """Extracted from services._scrape_source_candidates_with_timeout.

    Wraps _scrape_candidates with a per-source timeout.
    """
    settings = get_settings()
    timeout_seconds = max(settings.scraping_max_source_seconds, 30)
    timeout_seconds = min(
        timeout_seconds, int(settings.per_connector_timeout_seconds)
    )
    try:
        return await asyncio.wait_for(
            _scrape_candidates(source, stats), timeout=timeout_seconds
        )
    except TimeoutError as exc:
        raise TimeoutError(
            f"Scrape for source {source.key} exceeded {timeout_seconds}s"
        ) from exc


async def run_source_inline(
    db, source: Source, organization_id: str | None = None
) -> SourceRun:
    """Async version of services.execute_source_run_locally.

    Creates a SourceRun, scrapes candidates, persists opportunities,
    and updates the run with final status and counts.
    """
    started_at = datetime.now(UTC).replace(tzinfo=None)
    run = SourceRun(
        source_id=source.id,
        status="running",
        started_at=started_at,
        logs=[{"level": "info", "message": "Scraping MVP started"}],
    )
    source.last_run_at = started_at
    db.add(run)
    db.flush()
    org_id = (
        organization_id
        or source.organization_id
        or "00000000-0000-0000-0000-000000000000"
    )
    task = Task(
        organization_id=org_id,
        source_run_id=run.id,
        task_type="scrape_source",
        provider="local",
        status="running",
        started_at=started_at,
        payload={
            "source_key": source.key,
            "base_url": source.base_url,
            "source_type": source.source_type,
        },
    )
    db.add(task)
    db.flush()
    try:
        validate_source_url(source)
        scrape_stats: dict[str, object] = {}
        opportunities = await _scrape_source_candidates_with_timeout(
            source, scrape_stats
        )
        created = 0
        updated = 0
        failed_items = 0
        for opportunity_data in opportunities:
            try:
                opportunity = create_opportunity(
                    db, opportunity_data, organization_id=organization_id
                )
                if opportunity.first_seen_at == opportunity.last_seen_at:
                    created += 1
                else:
                    updated += 1
            except Exception as exc:
                failed_items += 1
                run.logs.append(
                    {
                        "level": "warning",
                        "message": "Candidate skipped during local persistence",
                        "title": getattr(opportunity_data, "title", ""),
                        "error": str(exc),
                    }
                )
        db.flush()
        finished_at = datetime.now(UTC).replace(tzinfo=None)
        run.status = "degraded" if len(opportunities) == 0 else "success"
        run.finished_at = finished_at
        run.items_found = len(opportunities)
        run.items_created = created
        run.items_updated = updated
        run.items_failed = failed_items
        run.logs = [
            *run.logs,
            {
                "level": "info",
                "message": "Local connector executed",
                "task_id": task.id,
            },
            {
                "level": "info",
                "message": "Connector diagnostics",
                **scrape_stats,
            },
            {
                "level": "info",
                "message": "Candidates normalized",
                "items_found": len(opportunities),
                "items_failed": failed_items,
            },
        ]
        task.status = run.status
        task.finished_at = finished_at
        task.result = {
            "items_found": len(opportunities),
            "items_created": created,
            "items_updated": updated,
        }
        if len(opportunities) > 0:
            source.last_success_at = finished_at
            source.last_error = None
        if len(opportunities) == 0:
            create_source_health_alert(
                db,
                source,
                reason="no se detectaron oportunidades nuevas en la ultima corrida",
            )
    except asyncio.CancelledError:
        finished_at = datetime.now(UTC).replace(tzinfo=None)
        run.status = "failed"
        run.finished_at = finished_at
        run.error_message = "Scrape cancelled (shutdown or timeout)"
        run.logs = [
            *run.logs,
            {"level": "error", "message": "Scrape cancelled"},
        ]
        task.status = "failed"
        task.finished_at = finished_at
        task.error_message = "Scrape cancelled"
        source.last_error = "Scrape cancelled"
        raise  # Re-raise so the scheduler knows this task was cancelled
    except Exception as exc:
        finished_at = datetime.now(UTC).replace(tzinfo=None)
        run.status = "failed"
        run.finished_at = finished_at
        run.items_failed = 1
        run.error_message = str(exc)
        run.logs = [
            *run.logs,
            {"level": "error", "message": str(exc)},
        ]
        task.status = "failed"
        task.finished_at = finished_at
        task.error_message = str(exc)
        task.result = {"items_failed": 1}
        source.last_error = str(exc)
        create_source_health_alert(db, source, reason=str(exc))
    return run
