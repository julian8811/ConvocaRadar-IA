"""Embedding management for opportunities.

Extracted from ``app/services.py`` (Change 3 — Architecture Refactor).
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.ai import build_embedding, compose_embedding_text, embedding_model_version
from app.models import PGVECTOR_AVAILABLE, Opportunity, OpportunityDocument, OpportunityEmbedding


def _get_opportunity_embedding(db: Session, opportunity_id: str) -> OpportunityEmbedding | None:
    """Get existing embedding for an opportunity (from DB or pending flush)."""
    existing = db.scalar(select(OpportunityEmbedding).where(OpportunityEmbedding.opportunity_id == opportunity_id))
    if existing:
        return existing
    for pending in db.new:
        if isinstance(pending, OpportunityEmbedding) and pending.opportunity_id == opportunity_id:
            return pending
    return None


def _supports_vector_search(db: Session) -> bool:
    """Check if the database supports vector search."""
    return PGVECTOR_AVAILABLE and db.bind is not None and db.bind.dialect.name == "postgresql"


def opportunity_embedding_text(opportunity: Opportunity) -> str:
    """Build the source text for embedding from an opportunity."""
    parts = [
        opportunity.title,
        opportunity.entity,
        opportunity.country,
        opportunity.region or "",
        opportunity.summary or opportunity.description,
        opportunity.raw_text,
        opportunity.official_url or "",
        opportunity.application_url or "",
        opportunity.funding_amount_raw or "",
    ]
    if opportunity.categories:
        parts.append("Categories: " + ", ".join(opportunity.categories))
    if opportunity.topics:
        parts.append("Topics: " + ", ".join(opportunity.topics))
    if opportunity.requirements:
        parts.append("Requirements: " + ", ".join(opportunity.requirements))
    if opportunity.documents_required:
        parts.append("Documents: " + ", ".join(opportunity.documents_required))
    if opportunity.evaluation_criteria:
        parts.append("Criteria: " + ", ".join(opportunity.evaluation_criteria))
    if opportunity.restrictions:
        parts.append("Restrictions: " + ", ".join(opportunity.restrictions))
    if opportunity.risk_flags:
        parts.append("Risks: " + ", ".join(opportunity.risk_flags))
    return compose_embedding_text(
        parts[0],
        "\n".join(part for part in parts[1:3] if part),
        "\n".join(part for part in parts[3:] if part),
    )


def opportunity_reanalysis_text(db: Session, opportunity: Opportunity) -> str:
    """Build the source text for AI re-analysis of an opportunity."""
    parts = [
        opportunity.title,
        opportunity.entity,
        opportunity.country,
        opportunity.summary,
        opportunity.raw_text,
        opportunity.official_url or "",
        opportunity.application_url or "",
    ]
    documents = list(
        db.scalars(
            select(OpportunityDocument)
            .where(OpportunityDocument.opportunity_id == opportunity.id)
            .order_by(OpportunityDocument.created_at.desc())
            .limit(5)
        )
    )
    for document in documents:
        if document.text_content:
            parts.append(document.text_content)
    if opportunity.categories:
        parts.append("Categories: " + ", ".join(opportunity.categories))
    if opportunity.topics:
        parts.append("Topics: " + ", ".join(opportunity.topics))
    if opportunity.requirements:
        parts.append("Requirements: " + ", ".join(opportunity.requirements))
    if opportunity.documents_required:
        parts.append("Documents: " + ", ".join(opportunity.documents_required))
    return compose_embedding_text(
        parts[0],
        "\n".join(part for part in parts[1:3] if part),
        "\n".join(part for part in parts[3:] if part),
    )


async def upsert_opportunity_embedding(db: Session, opportunity: Opportunity) -> OpportunityEmbedding:
    """Create or update the embedding for an opportunity."""
    source_text = opportunity_embedding_text(opportunity)
    vector = await build_embedding(source_text)
    existing = _get_opportunity_embedding(db, opportunity.id)
    if existing:
        existing.organization_id = opportunity.organization_id
        existing.source_text = source_text
        existing.embedding = vector
        existing.model_version = embedding_model_version()
        return existing
    embedding = OpportunityEmbedding(
        opportunity_id=opportunity.id,
        organization_id=opportunity.organization_id,
        source_text=source_text,
        embedding=vector,
        model_version=embedding_model_version(),
    )
    db.add(embedding)
    return embedding


async def rebuild_opportunity_embeddings(db: Session, organization_id: str, *, limit: int | None = None) -> dict[str, int]:
    """Rebuild embeddings for all opportunities visible to the org."""
    scope = or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None))
    stmt = select(Opportunity).where(scope).order_by(Opportunity.updated_at.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    opportunities = list(db.scalars(stmt))
    created = 0
    updated = 0
    for opportunity in opportunities:
        existing = db.scalar(select(OpportunityEmbedding).where(OpportunityEmbedding.opportunity_id == opportunity.id))
        source_text = opportunity_embedding_text(opportunity)
        vector = await build_embedding(source_text)
        if existing:
            existing.organization_id = opportunity.organization_id
            existing.source_text = source_text
            existing.embedding = vector
            existing.model_version = embedding_model_version()
            updated += 1
            continue
        db.add(
            OpportunityEmbedding(
                opportunity_id=opportunity.id,
                organization_id=opportunity.organization_id,
                source_text=source_text,
                embedding=vector,
                model_version=embedding_model_version(),
            )
        )
        created += 1
    return {"processed": len(opportunities), "created": created, "updated": updated}
