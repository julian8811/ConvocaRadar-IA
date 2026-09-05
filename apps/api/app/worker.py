"""Dedicated scheduler process + faculty_match arq task (T7)."""

import asyncio
import threading
import time
from pathlib import Path

import structlog
from sqlalchemy import select

from app.main import _run_periodic_source_sweep

HEARTBEAT = Path("/tmp/convocaradar-worker.heartbeat")
logger = structlog.get_logger(__name__)


async def faculty_match_task(db, opportunity_ids: list[str]) -> dict:
    """Async faculty match + per-profile alert generation, idempotent, deduped."""
    start = time.time()
    from app.models import Alert, FacultyProfile, Opportunity, OpportunityAxisMatch
    from app.services.matching import match_batch

    # Run matching batch (idempotent upsert)
    try:
        result = await match_batch(db, opportunity_ids)
    except Exception as exc:
        logger.exception("faculty_match_failed", error=str(exc), ids=opportunity_ids)
        raise

    # Generate alerts per qualifying profile (final_score >= threshold)
    alerts_created = 0
    for oid in opportunity_ids:
        opp = db.get(Opportunity, oid)
        if not opp or not opp.organization_id:
            continue
        matches = list(
            db.scalars(select(OpportunityAxisMatch).where(OpportunityAxisMatch.opportunity_id == oid))
        )
        for m in matches:
            profile = db.scalar(
                select(FacultyProfile).where(
                    FacultyProfile.faculty_id == m.faculty_id, FacultyProfile.axis_id == m.axis_id
                )
            )
            # Use profile threshold or fallback
            thr = 0.35
            if profile and profile.threshold is not None:
                thr = profile.threshold
            if m.final_score < thr:
                continue
            # Dedup by (org, opp, faculty)
            exists = db.scalar(
                select(Alert).where(
                    Alert.organization_id == m.organization_id,
                    Alert.opportunity_id == m.opportunity_id,
                    Alert.faculty_id == m.faculty_id,
                )
            )
            if exists:
                continue
            faculty_label = m.faculty_id
            try:
                from app.models import Faculty

                fac = db.get(Faculty, m.faculty_id)
                if fac:
                    faculty_label = fac.name
            except Exception:
                pass
            alert = Alert(
                organization_id=m.organization_id,
                opportunity_id=m.opportunity_id,
                faculty_id=m.faculty_id,
                alert_type="faculty_match",
                channel="email",
                recipient="",
                subject=f"Nueva oportunidad para {faculty_label}",
                message=f"Oportunidad {opp.title[:80]} clasificada para {faculty_label} score {m.final_score:.2f}",
                status="pending",
            )
            db.add(alert)
            alerts_created += 1
    db.flush()
    elapsed = time.time() - start
    if elapsed > 30:
        logger.warning("faculty_match_sla_breach", elapsed=elapsed, ids=opportunity_ids)
    else:
        logger.info("faculty_match_completed", elapsed=elapsed, processed=len(opportunity_ids), alerts_created=alerts_created)
    try:
        from app.core.metrics import record_p1_latency

        record_p1_latency(elapsed * 1000)
    except Exception:
        pass
    return {"processed": len(opportunity_ids), "matches": result.get("matches", 0), "alerts_created": alerts_created}


# arq task wrapper (compatible with arq worker)
async def faculty_match(ctx, opportunity_ids: list[str]) -> dict:
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        res = await faculty_match_task(db, opportunity_ids)
        db.commit()
        return res
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# arq WorkerSettings for optional arq deployment
class WorkerSettings:
    functions = [faculty_match]
    cron_jobs = []


def _heartbeat() -> None:
    while True:
        HEARTBEAT.touch()
        time.sleep(15)


def main() -> None:
    thread = threading.Thread(target=_heartbeat, daemon=True)
    thread.start()
    asyncio.run(_run_periodic_source_sweep())


if __name__ == "__main__":
    main()
