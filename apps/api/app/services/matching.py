"""Cosine matching service for faculty profiles (PR1: cosine-only, threshold 0.35)."""
from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.ai import build_embedding, cosine_similarity
from app.core.config import get_settings
from app.models import Faculty, FacultyProfile, InstitutionalAxis, Opportunity, OpportunityAxisMatch, OpportunityEmbedding

logger = structlog.get_logger(__name__)


def _opportunity_text(opportunity: Opportunity) -> str:
    parts = [opportunity.title or "", opportunity.entity or "", opportunity.summary or "", opportunity.description or "", opportunity.raw_text or ""]
    if opportunity.categories:
        parts.append(" ".join(opportunity.categories))
    if opportunity.topics:
        parts.append(" ".join(opportunity.topics))
    return "\n".join(p for p in parts if p)


async def match_opportunity(db: Session, opportunity_id: str) -> list[OpportunityAxisMatch]:
    settings = get_settings()
    if not settings.faculty_match_enabled:
        return []

    opp = db.get(Opportunity, opportunity_id)
    if not opp:
        return []

    org_id = opp.organization_id
    # opportunity must be visible - but for matching we still need org context
    # If opportunity has no org, match for all orgs? For now use its org or create generic
    # We match per opportunity's organization; if None, skip
    if not org_id:
        # Fallback: find any org to scope? Skip if no org - use first org? For test, opp has org
        # Try to find local org
        from app.models import Organization
        org = db.scalar(select(Organization).limit(1))
        if not org:
            return []
        org_id = org.id

    # Load profiles
    profiles = list(db.scalars(select(FacultyProfile)))
    if not profiles:
        return []

    # Build opportunity embedding
    text = _opportunity_text(opp)
    # Try to reuse existing opportunity embedding if available
    existing_emb = db.scalar(select(OpportunityEmbedding).where(OpportunityEmbedding.opportunity_id == opp.id))
    if existing_emb and existing_emb.embedding:
        opp_vec = list(existing_emb.embedding)
    else:
        opp_vec = await build_embedding(text)

    threshold_global = settings.axis_match_threshold

    results: list[OpportunityAxisMatch] = []
    for profile in profiles:
        if not profile.embedding:
            continue
        score = cosine_similarity(opp_vec, list(profile.embedding))
        thr = profile.threshold if profile.threshold is not None else threshold_global
        if score < thr:
            continue
        # Idempotent upsert by (org, opp, faculty)
        existing = db.scalar(
            select(OpportunityAxisMatch).where(
                OpportunityAxisMatch.organization_id == org_id,
                OpportunityAxisMatch.opportunity_id == opp.id,
                OpportunityAxisMatch.faculty_id == profile.faculty_id,
            )
        )
        reasons = [f"cosine {score:.3f} >= threshold {thr:.2f} for axis {profile.axis_id}"]
        if existing:
            # If verified_by set, don't overwrite faculty/axis
            if existing.verified_by:
                existing.embedding_score = score
                # keep faculty/axis as verified
                results.append(existing)
                continue
            existing.embedding_score = score
            existing.final_score = score  # PR1: final = embedding only
            existing.llm_score = None
            existing.reasons = reasons
            existing.axis_id = profile.axis_id
            results.append(existing)
        else:
            obj = OpportunityAxisMatch(
                organization_id=org_id,
                opportunity_id=opp.id,
                faculty_id=profile.faculty_id,
                axis_id=profile.axis_id,
                embedding_score=score,
                llm_score=None,
                final_score=score,
                reasons=reasons,
            )
            db.add(obj)
            results.append(obj)

    db.flush()
    logger.info("faculty_match_completed", opportunity_id=opp.id, matches=len(results))
    return results


async def match_batch(db: Session, opportunity_ids: list[str]) -> dict:
    total = 0
    for oid in opportunity_ids:
        matches = await match_opportunity(db, oid)
        total += len(matches)
    db.commit()
    return {"processed": len(opportunity_ids), "matches": total}
