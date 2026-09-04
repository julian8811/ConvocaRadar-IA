"""Hybrid faculty matching: P1 cosine gating + P2 LLM rerank (T6)."""
from __future__ import annotations

import hashlib

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.ai import build_embedding, classify_faculty_llm, cosine_similarity
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
    faculty_overrides = getattr(settings, "faculty_threshold_map", {})

    # Collect gated candidates (P1)
    candidates: list[tuple[FacultyProfile, float, float]] = []
    for profile in profiles:
        if not profile.embedding:
            continue
        score = cosine_similarity(opp_vec, list(profile.embedding))
        # per-faculty override (T9 tuning F1 0.40 / F4 0.32) > profile.threshold > global
        thr = faculty_overrides.get(profile.faculty_id) if profile.faculty_id in faculty_overrides else (profile.threshold if profile.threshold is not None else threshold_global)
        if score < thr:
            continue
        candidates.append((profile, score, thr))

    # P2 LLM rerank gating: only if candidates exist and flag enabled
    llm_result: dict | None = None
    if candidates and getattr(settings, "llm_classification_enabled", False):
        try:
            llm_result = await classify_faculty_llm(text)
        except Exception:
            llm_result = None
        # Validate strict enum already done inside classify; None means fallback

    results: list[OpportunityAxisMatch] = []
    for profile, score, thr in candidates:
        # Determine llm_score for this profile: if llm_result faculty matches profile, use its score
        llm_score: float | None = None
        extra_reasons: list[str] = []
        if llm_result is not None:
            # If llm_result faculty matches this profile's faculty, apply; otherwise still apply generic?
            # Strict: only apply if hallucinated faculty not in enum already filtered; reuse score for matching faculty
            if llm_result.get("faculty") == profile.faculty_id or llm_result.get("faculty") in {p[0].faculty_id for p in candidates}:
                # Check faculty match or fallback to first candidate faculty
                if llm_result.get("faculty") == profile.faculty_id:
                    llm_score = float(llm_result["llm_score"])
                    extra_reasons = list(llm_result.get("reasons") or [])
                else:
                    # LLM suggests different faculty than this profile; don't apply to this profile
                    llm_score = None
            else:
                llm_score = None
            # If llm_result faculty not matching any candidate, we still could apply to closest? For simplicity, apply only on exact match
            # If no exact match, llm_score stays None -> fallback
        # Weighting: 0.5/0.5 when llm_score present else 1.0*emb
        if llm_score is not None:
            final = round(0.5 * score + 0.5 * llm_score, 4)
        else:
            final = score

        reasons = [f"cosine {score:.3f} >= threshold {thr:.2f} for axis {profile.axis_id}"]
        if llm_score is not None:
            reasons.append(f"llm {llm_score:.3f} for faculty {profile.faculty_id}")
            reasons.extend(extra_reasons)

        existing = db.scalar(
            select(OpportunityAxisMatch).where(
                OpportunityAxisMatch.organization_id == org_id,
                OpportunityAxisMatch.opportunity_id == opp.id,
                OpportunityAxisMatch.faculty_id == profile.faculty_id,
            )
        )
        if existing:
            if existing.verified_by:
                existing.embedding_score = score
                results.append(existing)
                continue
            existing.embedding_score = score
            existing.llm_score = llm_score
            existing.final_score = final
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
                llm_score=llm_score,
                final_score=final,
                reasons=reasons,
            )
            db.add(obj)
            results.append(obj)

    db.flush()
    # Metrics: try to record
    try:
        from app.core.metrics import record_match

        for r in results:
            record_match(r.final_score, r.llm_score is not None)
    except Exception:
        pass
    logger.info(
        "faculty_match_completed",
        opportunity_id=opp.id,
        matches=len(results),
        llm_enabled=getattr(settings, "llm_classification_enabled", False),
        llm_hit=llm_result is not None,
    )
    return results


async def match_batch(db: Session, opportunity_ids: list[str]) -> dict:
    total = 0
    for oid in opportunity_ids:
        matches = await match_opportunity(db, oid)
        total += len(matches)
    db.commit()
    return {"processed": len(opportunity_ids), "matches": total}
