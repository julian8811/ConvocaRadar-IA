"""Deduplication logic for opportunities.

Extracted from ``app/services.py`` (Change 3 — Architecture Refactor).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Alert, Opportunity, OpportunityDocument, OpportunityEmbedding, OpportunityScore
from app.schemas import OpportunityCreate

from app.services.validation import normalize_official_url, slugify


def opportunity_dedup_key(official_url: str | None, title: str, raw_text: str = "") -> str | None:
    """Build a deterministic deduplication key for an opportunity."""
    normalized_url = normalize_official_url(official_url)
    if normalized_url:
        url_patterns = (
            (r"/search-results-detail/(\d+)(?:/|$)", "grants-gov"),
            (r"/opportunity/(\d+)(?:/|$)", "simpler-grants-gov"),
            (r"/topic-details/([^/?#]+)", "eu-topic"),
            (r"/project/id/([^/?#]+)", "cordis-project"),
        )
        for pattern, prefix in url_patterns:
            match = re.search(pattern, normalized_url, flags=re.IGNORECASE)
            if match:
                return f"{prefix}:{match.group(1).lower()}"
        return f"url:{normalized_url}"

    if raw_text:
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            grants_id = str(payload.get("id") or "").strip()
            if grants_id.isdigit():
                return f"grants-gov:{grants_id}"
            number = str(payload.get("number") or "").strip()
            if number:
                return f"grants-gov-number:{number.lower()}"

        number_match = re.search(r"\b(OFOP\d+|TEST-[A-Z0-9-]+)\b", raw_text, flags=re.IGNORECASE)
        if number_match:
            return f"grants-gov-number:{number_match.group(1).lower()}"

    title_key = slugify(title.strip())
    if title_key and title_key != "item":
        return f"title:{title_key}"
    return None


def _organization_opportunity_scope(organization_id: str | None):
    """Build scope filter for organization-bound opportunities."""
    return or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None))


def find_duplicate_opportunity(
    db: Session,
    data: OpportunityCreate,
    organization_id: str | None,
) -> Opportunity | None:
    """Find an existing duplicate opportunity."""
    scope = _organization_opportunity_scope(organization_id)
    dedup_key = opportunity_dedup_key(data.official_url, data.title, data.raw_text or "")
    if not dedup_key:
        return None

    if dedup_key.startswith("grants-gov:"):
        grants_id = dedup_key.split(":", 1)[1]
        if grants_id.isdigit():
            existing = db.scalar(
                select(Opportunity)
                .where(
                    scope,
                    or_(
                        Opportunity.official_url.ilike(f"%/search-results-detail/{grants_id}%"),
                        Opportunity.official_url.ilike(f"%/opportunity/{grants_id}%"),
                    ),
                )
                .order_by(Opportunity.first_seen_at.asc())
            )
            if existing:
                return existing

    if dedup_key.startswith("grants-gov-number:"):
        grant_number = dedup_key.split(":", 1)[1]
        existing = db.scalar(
            select(Opportunity)
            .where(
                scope,
                or_(
                    Opportunity.raw_text.ilike(f"%{grant_number}%"),
                    Opportunity.summary.ilike(f"%{grant_number}%"),
                ),
            )
            .order_by(Opportunity.first_seen_at.asc())
        )
        if existing:
            return existing

    if dedup_key.startswith("url:"):
        normalized_target = dedup_key[4:]
        candidates = db.scalars(
            select(Opportunity).where(scope, Opportunity.official_url.is_not(None)).order_by(Opportunity.first_seen_at.asc())
        )
        for candidate in candidates:
            if normalize_official_url(candidate.official_url) == normalized_target:
                return candidate
        return None

    if dedup_key.startswith(("eu-topic:", "cordis-project:")):
        token = dedup_key.split(":", 1)[1]
        existing = db.scalar(
            select(Opportunity)
            .where(scope, Opportunity.official_url.ilike(f"%{token}%"))
            .order_by(Opportunity.first_seen_at.asc())
        )
        if existing:
            return existing

    if dedup_key.startswith("title:") and data.close_date:
        existing = db.scalar(
            select(Opportunity)
            .where(
                scope,
                Opportunity.close_date == data.close_date,
                Opportunity.title.ilike(data.title.strip()),
            )
            .order_by(Opportunity.first_seen_at.asc())
        )
        if existing:
            return existing

    return None


def _normalize_survivor_datetime(value: datetime | None) -> datetime:
    """Normalize a datetime for survivor comparison."""
    if value is None:
        return datetime.min.replace(tzinfo=None)
    if value.tzinfo is not None:
        return value.replace(tzinfo=None)
    return value


def _opportunity_survivor_key(opportunity: Opportunity) -> tuple[datetime, datetime, str]:
    """Build a sort key for survivor selection (first_seen, created, id)."""
    first_seen = _normalize_survivor_datetime(opportunity.first_seen_at)
    created = _normalize_survivor_datetime(opportunity.created_at) if opportunity.created_at else first_seen
    return (first_seen, created, opportunity.id)


def _reassign_opportunity_relations(db: Session, survivor: Opportunity, duplicate: Opportunity) -> None:
    """Reassign all FK relations from duplicate to survivor. Does NOT delete the duplicate."""
    if duplicate.is_favorite and not survivor.is_favorite:
        survivor.is_favorite = True
    if duplicate.user_status not in {"review"} and survivor.user_status == "review":
        survivor.user_status = duplicate.user_status

    for document in db.scalars(select(OpportunityDocument).where(OpportunityDocument.opportunity_id == duplicate.id)):
        document.opportunity_id = survivor.id

    for score in db.scalars(select(OpportunityScore).where(OpportunityScore.opportunity_id == duplicate.id)):
        existing_score = db.scalar(
            select(OpportunityScore).where(
                OpportunityScore.opportunity_id == survivor.id,
                OpportunityScore.organization_id == score.organization_id,
            )
        )
        if existing_score:
            if score.score > existing_score.score:
                existing_score.score = score.score
                existing_score.priority = score.priority
                existing_score.reasons = score.reasons
                existing_score.warnings = score.warnings
            db.delete(score)
        else:
            score.opportunity_id = survivor.id

    duplicate_embedding = db.scalar(select(OpportunityEmbedding).where(OpportunityEmbedding.opportunity_id == duplicate.id))
    if duplicate_embedding:
        survivor_embedding = db.scalar(select(OpportunityEmbedding).where(OpportunityEmbedding.opportunity_id == survivor.id))
        if survivor_embedding:
            db.delete(duplicate_embedding)
        else:
            duplicate_embedding.opportunity_id = survivor.id

    for alert in db.scalars(select(Alert).where(Alert.opportunity_id == duplicate.id)):
        alert.opportunity_id = survivor.id


def _merge_opportunity_records(db: Session, survivor: Opportunity, duplicate: Opportunity) -> None:
    """Merge a duplicate into survivor and delete the duplicate."""
    _reassign_opportunity_relations(db, survivor, duplicate)
    db.delete(duplicate)


def deduplicate_opportunities(db: Session, organization_id: str | None = None) -> dict[str, int]:
    """Deduplicate all opportunities visible to the given org scope."""
    scope = _organization_opportunity_scope(organization_id)
    opportunities = list(db.scalars(select(Opportunity).where(scope).order_by(Opportunity.first_seen_at.asc())))
    grouped: dict[str, list[Opportunity]] = {}
    for opportunity in opportunities:
        key = opportunity_dedup_key(opportunity.official_url, opportunity.title, opportunity.raw_text or "") or f"id:{opportunity.id}"
        grouped.setdefault(key, []).append(opportunity)

    groups_merged = 0
    duplicates_removed = 0
    duplicates_to_delete: list[Opportunity] = []

    for group in grouped.values():
        if len(group) < 2:
            continue
        survivor = min(group, key=_opportunity_survivor_key)
        for duplicate in group:
            if duplicate.id == survivor.id:
                continue
            _reassign_opportunity_relations(db, survivor, duplicate)
            duplicates_to_delete.append(duplicate)
            duplicates_removed += 1
        groups_merged += 1

    db.flush()
    for duplicate in duplicates_to_delete:
        db.delete(duplicate)
    db.flush()
    return {"groups_merged": groups_merged, "duplicates_removed": duplicates_removed}


def candidate_external_id(
    source: object,
    url: str | None,
    title: str,
    raw_text: str = "",
) -> str:
    """Build a deterministic external_id for an opportunity candidate."""
    dedup_key = opportunity_dedup_key(url, title, raw_text)
    if dedup_key:
        fingerprint = hashlib.sha256(dedup_key.encode("utf-8")).hexdigest()[:16]
        return f"dedup-{fingerprint}"
    source_key = getattr(source, "key", "unknown")
    fingerprint = hashlib.sha256(f"{url or ''}|{title}".encode("utf-8")).hexdigest()[:16]
    return f"{source_key}-{fingerprint}"
