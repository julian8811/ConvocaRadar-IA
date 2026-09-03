"""Inline scraper runner — extracted from app.services.

Phase 1: pure extraction of scraping lifecycle. No Redis, no Celery.
Phase 2 (PR2): updated to track progress after each lifecycle phase.
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime

import structlog
import time

from app.core.config import get_settings
from app.models import Source, SourceRun, Task

_struct_logger = structlog.get_logger(__name__)
from app.schemas import OpportunityCreate
from app.scraper.dom_monitor import compute_dom_hash
from app.scraper.errors import ErrorType, classify_error
from app.services import (
    candidate_external_id,
    create_opportunity,
    create_source_health_alert,
    is_noise_payload,
    validate_source_url,
)
from app.services.scoring import (
    should_auto_pause,
    update_consecutive_empty_runs,
)

# Batch enrichment wiring — extracted for S2 p95 (chunks 20 LLM / 32 embedding, LRU256)
try:
    from app.core.ai import extract_opportunities_structured_batch
except Exception:  # pragma: no cover
    extract_opportunities_structured_batch = None  # type: ignore

try:
    from app.services.embeddings import build_embeddings_batch
except Exception:  # pragma: no cover
    build_embeddings_batch = None  # type: ignore

# Phases tracked in run.progress
PROGRESS_STEPS = ["fetch", "parse", "persist"]


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
        connector_config=source.connector_config,
    )
    raw = await connector.fetch()
    if stats is not None:
        stats["raw_url"] = raw.url
        stats["raw_content_type"] = raw.content_type
        stats["raw_content_length"] = len(raw.content or "")
        # Change D: compute DOM hash from raw page content
        stats["dom_hash"] = compute_dom_hash(raw.content or "")
    candidates = await connector.parse(raw)
    # Persist connector state (processed_urls, last_sitemap_fetch)
    # for connectors that track incremental progress across runs.
    updated_config = getattr(connector, "get_updated_config", lambda: None)()
    if updated_config is not None:
        source.connector_config = updated_config
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
    from app.connectors.common import fill_candidate_from_content

    opportunities: list[OpportunityCreate] = []
    noise_rejected = 0
    validation_rejected = 0
    validation_reasons: list[str] = []
    for candidate in candidates:
        candidate = fill_candidate_from_content(
            candidate,
            text=candidate.raw_text or candidate.summary,
            page_url=candidate.official_url,
        )
        if is_noise_payload(candidate.title, candidate.summary, candidate.raw_text):
            noise_rejected += 1
            continue
        validation = await connector.validate(candidate)
        if not validation.ok:
            reason = (validation.reason or "").lower()
            appears_closed = "closed" in reason or "cerrad" in reason
            if not appears_closed:
                validation_rejected += 1
                if len(validation_reasons) < 5:
                    validation_reasons.append(validation.reason or "sin razon")
                continue
        opportunities.append(
            OpportunityCreate(
                source_id=source.id,
                external_id=candidate.external_id
                or candidate_external_id(
                    source,
                    candidate.official_url,
                    candidate.title,
                    candidate.raw_text or "",
                ),
                title=candidate.title,
                entity=candidate.entity,
                country=candidate.country,
                # A region scraped from the page is more specific than the
                # source-wide default, so it wins when present.
                region=candidate.region or source.region,
                language=candidate.language,
                categories=candidate.categories,
                topics=candidate.topics,
                description=candidate.description or candidate.summary or candidate.title,
                summary=candidate.summary or candidate.title,
                raw_text=candidate.raw_text,
                official_url=candidate.official_url,
                application_url=candidate.application_url,
                open_date=candidate.open_date,
                close_date=candidate.close_date,
                funding_amount_raw=candidate.funding_amount_raw,
                funding_amount_value=candidate.funding_amount_value,
                funding_amount_currency=candidate.funding_amount_currency,
                eligible_applicants=candidate.eligible_applicants,
                requirements=candidate.requirements,
                documents_required=candidate.documents_required,
                evaluation_criteria=candidate.evaluation_criteria,
                restrictions=candidate.restrictions,
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
    timeout_seconds = min(timeout_seconds, int(settings.per_connector_timeout_seconds))
    try:
        return await asyncio.wait_for(_scrape_candidates(source, stats), timeout=timeout_seconds)
    except TimeoutError as exc:
        raise TimeoutError(f"Scrape for source {source.key} exceeded {timeout_seconds}s") from exc


async def _batch_enrich(
    opportunities: list[OpportunityCreate],
) -> list[OpportunityCreate]:
    """Batched enrichment for p95 — flag-gated serial vs batch.

    Flag OFF (default): serial parity via enrich_opportunity_payload per item.
    Flag ON: uses extract_opportunities_structured_batch(chunk_size=20) with LRU256
             and build_embeddings_batch (chunk 32/20) for p95 ≤4s. No N-loop.
    """
    settings = get_settings()
    if not opportunities:
        return []

    if not settings.extraction_batch_enabled:
        # Serial fallback — preserves parity, no cross-contamination
        from app.services.opportunity import enrich_opportunity_payload

        results: list[OpportunityCreate] = []
        for oc in opportunities:
            results.append(await enrich_opportunity_payload(oc))
        return results

    # Batch path: LLM extraction chunk 20 + embedding batch 32/20
    texts = [(oc.raw_text or oc.summary or oc.title or "") for oc in opportunities]

    # Embedding batch for p95 (best-effort, does not block enrichment on failure)
    if build_embeddings_batch is not None:
        try:
            await build_embeddings_batch(texts)
        except Exception:
            pass

    if extract_opportunities_structured_batch is None:
        # Fallback to serial if batch unavailable
        from app.services.opportunity import enrich_opportunity_payload

        results = []
        for oc in opportunities:
            results.append(await enrich_opportunity_payload(oc))
        return results

    extractions = await extract_opportunities_structured_batch(texts, chunk_size=20)

    # Merge extractions into OpportunityCreate copies — parser frozen (d9579f4)
    enriched: list[OpportunityCreate] = []
    for orig, ext in zip(opportunities, extractions):
        data = ext.data if hasattr(ext, "data") else {}
        merged = orig.model_dump()
        # Funding raw only if missing
        if not merged.get("funding_amount_raw") and data.get("funding_amount_raw"):
            from app.services.opportunity import _is_tr_artifact

            fr = str(data.get("funding_amount_raw") or "")
            if fr and not _is_tr_artifact(fr):
                merged["funding_amount_raw"] = fr
        # Confidence max
        try:
            merged["confidence_score"] = round(
                max(float(orig.confidence_score), float(data.get("confidence") or orig.confidence_score)), 2
            )
        except Exception:
            pass
        # Title / entity / country fill if missing (ES/EN isolated per candidate)
        if not merged.get("title") or merged["title"] == "Convocatoria detectada":
            t = str(data.get("title") or "")
            if t:
                merged["title"] = t
        if not merged.get("entity") or merged["entity"] == "Entidad por validar":
            e = str(data.get("entity") or "")
            if e:
                merged["entity"] = e
        if not merged.get("country") or merged["country"] in ("Por validar", "Sin dato", ""):
            c = str(data.get("country") or "")
            if c:
                merged["country"] = c
        # Categories / topics if missing
        if not merged.get("categories"):
            cats = data.get("category") or []
            if cats:
                merged["categories"] = list(cats)
        if not merged.get("topics"):
            kws = data.get("matched_keywords") or []
            if kws:
                merged["topics"] = list(kws)
        enriched.append(OpportunityCreate(**merged))

    return enriched


def _setup_run(db, source: Source, organization_id: str | None) -> tuple[SourceRun, Task, datetime]:
    """Create SourceRun + Task records for this scrape."""
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
    org_id = organization_id or source.organization_id or "00000000-0000-0000-0000-000000000000"
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
    return run, task, started_at


async def _persist_opportunities(
    db, run: SourceRun, opportunities: list[OpportunityCreate], organization_id: str | None
) -> tuple[int, int, int]:
    """Persist scraped opportunities, returning (created, updated, failed).

    Uses bulk dedup preload_external_ids per source to avoid N+1, with
    clear_bulk_cache after each source batch.
    """
    from app.services.opportunity import clear_bulk_cache, preload_external_ids

    # Preload per-source external_id sets (1 query per source)
    source_ids = {o.source_id for o in opportunities if o.source_id}
    for sid in source_ids:
        try:
            preload_external_ids(db, sid)
        except Exception:
            pass
    created = 0
    updated = 0
    failed_items = 0
    for opportunity_data in opportunities:
        try:
            opportunity_result = create_opportunity(
                db, opportunity_data, organization_id=organization_id
            )
            opportunity = (
                await opportunity_result
                if inspect.isawaitable(opportunity_result)
                else opportunity_result
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
    # Clear per-source bulk caches so next source starts fresh
    try:
        clear_bulk_cache()
    except Exception:
        pass
    return created, updated, failed_items


def _finalize_run(
    db,
    run: SourceRun,
    task: Task,
    source: Source,
    opportunities: list[OpportunityCreate],
    created: int,
    updated: int,
    failed_items: int,
    scrape_stats: dict[str, object],
) -> None:
    """Update SourceRun, Task, and Source with final status after successful scrape."""
    finished_at = datetime.now(UTC).replace(tzinfo=None)
    run.status = "degraded" if len(opportunities) == 0 else "success"
    run.finished_at = finished_at
    run.items_found = len(opportunities)
    run.items_created = created
    run.items_updated = updated
    run.items_failed = failed_items
    run.logs = [
        *run.logs,
        {"level": "info", "message": "Local connector executed", "task_id": task.id},
        {"level": "info", "message": "Connector diagnostics", **scrape_stats},
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
    # Track consecutive empty runs and auto-pause
    source.consecutive_empty_runs = update_consecutive_empty_runs(
        items_found=len(opportunities),
        current_count=source.consecutive_empty_runs or 0,
    )
    if should_auto_pause(source.consecutive_empty_runs):
        source.auto_paused = True
        run.logs.append(
            {
                "level": "warn",
                "message": f"Source auto-paused after {source.consecutive_empty_runs} consecutive empty runs",
            }
        )
    # Track selector failures and auto-pause
    if len(opportunities) == 0:
        source.selector_failures = (source.selector_failures or 0) + 1
    else:
        source.selector_failures = 0
    if (source.selector_failures or 0) >= 5:
        source.auto_paused = True
        run.logs.append(
            {
                "level": "warn",
                "message": f"Source auto-paused after {source.selector_failures} consecutive selector failures",
            }
        )
    db.flush()


def _handle_run_error(
    db,
    run: SourceRun,
    task: Task,
    source: Source,
    exc: Exception,
) -> None:
    """Update run/task/source on scrape error."""
    finished_at = datetime.now(UTC).replace(tzinfo=None)
    error_type = classify_error(exc)
    error_message = str(exc).strip() or f"{type(exc).__name__}: ejecución interrumpida"
    error_type_value = error_type.value
    run.status = "degraded" if error_type == ErrorType.PARSE else "failed"
    run.finished_at = finished_at
    run.items_failed = 1
    run.error_message = error_message
    run.logs = [
        *run.logs,
        {"level": "error", "message": error_message, "error_type": error_type_value},
    ]
    task.status = run.status
    task.finished_at = finished_at
    task.error_message = error_message
    task.result = {"items_failed": 1}
    source.last_error = error_message
    if error_type not in (ErrorType.TIMEOUT, ErrorType.NETWORK):
        create_source_health_alert(db, source, reason=error_message)
    # Auto-pause counters must increment also on timeout/network failures (failed category)
    source.consecutive_empty_runs = update_consecutive_empty_runs(
        items_found=0,
        current_count=source.consecutive_empty_runs or 0,
    )
    if should_auto_pause(source.consecutive_empty_runs):
        source.auto_paused = True
        run.logs.append(
            {
                "level": "warn",
                "message": f"Source auto-paused after {source.consecutive_empty_runs} consecutive empty runs (error)",
            }
        )
    source.selector_failures = (source.selector_failures or 0) + 1
    if (source.selector_failures or 0) >= 5:
        source.auto_paused = True
        run.logs.append(
            {
                "level": "warn",
                "message": f"Source auto-paused after {source.selector_failures} consecutive selector failures (error)",
            }
        )
    db.flush()


async def run_source_inline(db, source: Source, organization_id: str | None = None) -> SourceRun:
    """Scrape a source, persist opportunities, and return the SourceRun.

    Orchestrates: setup → scrape → persist → finalize (or error handling).
    """
    _t0 = time.monotonic()
    run, task, _started_at = _setup_run(db, source, organization_id)
    try:
        validate_source_url(source)
        scrape_stats: dict[str, object] = {}
        opportunities = await _scrape_source_candidates_with_timeout(source, scrape_stats)

        _update_dom_hash(source, run, scrape_stats)
        items_parsed = scrape_stats.get("candidates_parsed")
        if isinstance(items_parsed, int):
            source.last_item_count = items_parsed
        # S2 batch enrichment — flag-gated, chunks 20/32 LRU256, removes serial N-loop
        if get_settings().extraction_batch_enabled and opportunities:
            try:
                opportunities = await _batch_enrich(opportunities)
            except Exception as exc:  # pragma: no cover — batch best-effort fallback
                _struct_logger.warning("batch_enrich_failed_fallback_serial", error=str(exc))
        _set_progress(run, {"fetch": _now(), "parse": _now()})
        db.flush()

        elapsed = (datetime.now(UTC).replace(tzinfo=None) - _started_at).total_seconds()
        remaining = max(1.0, get_settings().scraping_max_source_seconds - elapsed)
        created, updated, failed = await asyncio.wait_for(
            _persist_opportunities(db, run, opportunities, organization_id),
            timeout=remaining,
        )
        _set_progress(run, {"persist": _now()})
        db.flush()

        _finalize_run(db, run, task, source, opportunities, created, updated, failed, scrape_stats)
        _dur = time.monotonic() - _t0
        _struct_logger.info(
            "scraper_source_complete",
            source_key=source.key,
            latency_ms=int(_dur * 1000),
            items_found=len(opportunities),
            created=created,
            updated=updated,
            status=run.status,
        )
        try:
            from app.scraper.metrics import record_scrape

            record_scrape(source_key=source.key or source.id, duration_s=_dur, items_found=len(opportunities), status=run.status)
        except Exception:
            pass
    except asyncio.CancelledError:
        finished_at = datetime.now(UTC).replace(tzinfo=None)
        run.status = "failed"
        run.finished_at = finished_at
        run.error_message = "Scrape cancelled (shutdown or timeout)"
        run.logs = [
            *run.logs,
            {"level": "error", "message": "Scrape cancelled", "error_type": "TIMEOUT"},
        ]
        task.status = "failed"
        task.finished_at = finished_at
        task.error_message = "Scrape cancelled"
        source.last_error = "Scrape cancelled"
        raise
    except Exception as exc:
        _handle_run_error(db, run, task, source, exc)
        _dur2 = time.monotonic() - _t0
        _struct_logger.warning(
            "scraper_source_error",
            source_key=source.key,
            latency_ms=int(_dur2 * 1000),
            error=str(exc),
            status=run.status,
        )
        try:
            from app.scraper.metrics import record_scrape

            record_scrape(source_key=source.key or source.id, duration_s=_dur2, items_found=0, status=run.status)
        except Exception:
            pass
    return run


def _now() -> str:
    """Return current UTC datetime as ISO string."""
    return datetime.now(UTC).replace(tzinfo=None).isoformat()


def _set_progress(run: SourceRun, updates: dict[str, str]) -> None:
    """Update run.progress with the given key/value pairs.

    Merges the updates into the existing progress dict (or creates one).
    Each key is a lifecycle phase name; each value is an ISO datetime string.
    """
    current = dict(run.progress or {})
    current.update(updates)
    run.progress = current


def _update_dom_hash(
    source: Source,
    run: SourceRun,
    stats: dict[str, object],
) -> None:
    """Update source DOM hash from scrape stats and log changes.

    Uses ``stats["dom_hash"]`` (computed during ``_scrape_candidates``) to
    update the source's ``dom_hash``. If the hash has changed (or this is
    the first scrape), logs a structural change warning.

    Must be called after ``_scrape_source_candidates_with_timeout`` and
    before ``db.flush()`` so the changes to ``source`` are persisted.
    """
    new_hash = stats.get("dom_hash")
    if not isinstance(new_hash, str):
        return

    old_hash = source.dom_hash
    source.dom_hash = new_hash

    if old_hash is None:
        run.logs.append(
            {
                "level": "info",
                "message": "DOM hash recorded for the first time",
                "dom_hash": new_hash[:16],
            }
        )
    elif old_hash != new_hash:
        source.dom_hash_changed_at = datetime.now(UTC).replace(tzinfo=None)
        run.logs.append(
            {
                "level": "warn",
                "message": "DOM hash changed — page structure may have changed",
                "old_hash_prefix": old_hash[:16],
                "new_hash_prefix": new_hash[:16],
            }
        )
