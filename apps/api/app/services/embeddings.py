"""Embedding management for opportunities.

Extracted from ``app/services.py`` (Change 3 — Architecture Refactor).
"""

from __future__ import annotations

import asyncio

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.ai import build_embedding, compose_embedding_text, embedding_model_version
from app.core.config import effective_llm_provider, get_settings
from app.core.http_client import http_client
from app.models import PGVECTOR_AVAILABLE, Opportunity, OpportunityDocument, OpportunityEmbedding

EMBEDDING_BATCH_SIZE = 32
EMBEDDING_BATCH_RETRY_CHUNK = 20


def _get_opportunity_embedding(db: Session, opportunity_id: str) -> OpportunityEmbedding | None:
    """Get existing embedding for an opportunity (from DB or pending flush)."""
    existing = db.scalar(
        select(OpportunityEmbedding).where(OpportunityEmbedding.opportunity_id == opportunity_id)
    )
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


async def upsert_opportunity_embedding(
    db: Session, opportunity: Opportunity
) -> OpportunityEmbedding:
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


async def _call_openai_embedding_batch(
    texts: list[str], *, dimensions: int
) -> list[list[float]] | None:
    """Batch embedding call — Cloudflare Workers AI compatible (input: string[])."""
    settings = get_settings()
    provider = effective_llm_provider(settings.llm_provider)
    if provider == "local" or not settings.llm_api_key or not settings.embedding_model:
        return None
    payload: dict[str, object] = {
        "model": settings.embedding_model,
        "input": [t[:8000] for t in texts],
    }
    if provider == "openai":
        payload["dimensions"] = dimensions  # type: ignore[assignment]
    client = await http_client()
    response = await client.post(
        f"{settings.llm_api_base.rstrip('/')}/embeddings",
        headers={
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=settings.llm_timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()
    rows = data.get("data") or []
    if not rows:
        return None
    # Workers AI may return unordered; sort by index if present.
    try:
        rows = sorted(rows, key=lambda r: r.get("index", 0))
    except Exception:
        pass
    vectors: list[list[float]] = []
    for row in rows:
        vec = row.get("embedding")
        if isinstance(vec, list):
            vectors.append([round(float(v), 6) for v in vec])
    if len(vectors) != len(texts):
        return None
    return vectors


async def build_embeddings_batch(
    texts: list[str], *, dimensions: int | None = None
) -> list[list[float]]:
    """Build embeddings for many texts via batched Cloudflare/OpenAI call (chunk 32).

    Falls back to serial ``build_embedding`` per chunk on 429/5xx or mismatched
    response, with chunked retry (20) semantics. Local provider does serial.
    """
    if not texts:
        return []
    settings = get_settings()
    target = dimensions or settings.embedding_dimensions or 64
    provider = effective_llm_provider(settings.llm_provider)
    if provider == "local":
        # Local hashing is CPU-bound but cheap; still respect chunk for back-pressure.
        results: list[list[float]] = []
        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            for t in texts[i : i + EMBEDDING_BATCH_SIZE]:
                results.append(await build_embedding(t, dimensions=target))
        return results
    all_vectors: list[list[float]] = []
    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        chunk = texts[i : i + EMBEDDING_BATCH_SIZE]
        try:
            batch = await _call_openai_embedding_batch(chunk, dimensions=target)
            if batch is not None:
                all_vectors.extend(batch)
                continue
            raise RuntimeError("empty batch response")
        except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError):
            # Chunked retry with smaller sub-chunks, then serial fallback.
            sub_chunk_size = EMBEDDING_BATCH_RETRY_CHUNK
            for j in range(0, len(chunk), sub_chunk_size):
                sub = chunk[j : j + sub_chunk_size]
                try:
                    batch = await _call_openai_embedding_batch(sub, dimensions=target)
                    if batch is not None:
                        all_vectors.extend(batch)
                        continue
                except Exception:
                    pass
                for t in sub:
                    try:
                        all_vectors.append(await build_embedding(t, dimensions=target))
                    except Exception:
                        all_vectors.append([0.0] * target)
            # brief backoff to respect rate limits
            await asyncio.sleep(0.2)
    return all_vectors


class EmbeddingBatchService:
    """Batch upsert helper — chunks 32 via build_embeddings_batch."""

    async def batch_upsert(
        self, db: Session, opportunities: list[Opportunity]
    ) -> dict[str, int]:
        if not opportunities:
            return {"processed": 0, "created": 0, "updated": 0}
        texts = [opportunity_embedding_text(o) for o in opportunities]
        vectors = await build_embeddings_batch(texts)
        created = 0
        updated = 0
        for opp, vec, txt in zip(opportunities, vectors, texts):
            existing = _get_opportunity_embedding(db, opp.id)
            if existing:
                existing.organization_id = opp.organization_id
                existing.source_text = txt
                existing.embedding = vec
                existing.model_version = embedding_model_version()
                updated += 1
            else:
                db.add(
                    OpportunityEmbedding(
                        opportunity_id=opp.id,
                        organization_id=opp.organization_id,
                        source_text=txt,
                        embedding=vec,
                        model_version=embedding_model_version(),
                    )
                )
                created += 1
        # Async hook: faculty_match after embeddings persisted (T7)
        try:
            from app.core.config import get_settings

            if get_settings().faculty_match_enabled:
                opp_ids = [o.id for o in opportunities]
                from app.core.task_queue import enqueue_faculty_match

                enqueue_faculty_match(opp_ids)
        except Exception:
            pass
        return {"processed": len(opportunities), "created": created, "updated": updated}


async def rebuild_opportunity_embeddings(
    db: Session, organization_id: str, *, limit: int | None = None
) -> dict[str, int]:
    """Rebuild embeddings for all opportunities visible to the org."""
    scope = or_(
        Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None)
    )
    stmt = select(Opportunity).where(scope).order_by(Opportunity.updated_at.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    opportunities = list(db.scalars(stmt))
    created = 0
    updated = 0
    for opportunity in opportunities:
        existing = db.scalar(
            select(OpportunityEmbedding).where(
                OpportunityEmbedding.opportunity_id == opportunity.id
            )
        )
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
