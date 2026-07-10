"""Search and query-building for opportunities.

Extracted from ``app/services.py`` (Change 3 — Architecture Refactor).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import Select, and_, func as sa_func, or_, select
from sqlalchemy.orm import Session

from app.core.ai import build_embedding, cosine_similarity
from app.models import Opportunity, OpportunityEmbedding


def build_opportunity_query(
    organization_id: str,
    *,
    country: str | None = None,
    category: str | None = None,
    status: str | None = None,
    source_id: str | None = None,
    priority: str | None = None,
    search: str | None = None,
    close_date_from: str | None = None,
    close_date_to: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
) -> Select[tuple[Opportunity]]:
    """Build a SELECT query for opportunities with the given filters."""
    from app.models import OpportunityScore

    stmt = select(Opportunity).where(
        or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None))
    )
    if country:
        stmt = stmt.where(Opportunity.country == country)
    if category:
        stmt = stmt.where(Opportunity.categories.contains([category]))
    if status:
        stmt = stmt.where(Opportunity.status == status)
    if source_id:
        stmt = stmt.where(Opportunity.source_id == source_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                Opportunity.title.ilike(like),
                Opportunity.entity.ilike(like),
                Opportunity.summary.ilike(like),
                Opportunity.description.ilike(like),
                Opportunity.raw_text.ilike(like),
                Opportunity.official_url.ilike(like),
                Opportunity.application_url.ilike(like),
            )
        )
    stmt = stmt.where(~Opportunity.title.ilike("%@%"))
    stmt = stmt.where(~Opportunity.title.ilike("http%"))
    if close_date_from:
        try:
            from_date = datetime.strptime(close_date_from, "%Y-%m-%d")
            stmt = stmt.where(Opportunity.close_date >= from_date)
        except ValueError:
            pass
    if close_date_to:
        try:
            to_date = datetime.strptime(close_date_to, "%Y-%m-%d")
            stmt = stmt.where(Opportunity.close_date <= to_date.replace(hour=23, minute=59, second=59))
        except ValueError:
            pass
    if min_amount is not None:
        stmt = stmt.where(Opportunity.funding_amount_value.isnot(None), Opportunity.funding_amount_value >= min_amount)
    if max_amount is not None:
        stmt = stmt.where(Opportunity.funding_amount_value.isnot(None), Opportunity.funding_amount_value <= max_amount)
    if priority:
        stmt = stmt.join(OpportunityScore, OpportunityScore.opportunity_id == Opportunity.id).where(
            OpportunityScore.organization_id == organization_id,
            OpportunityScore.priority == priority,
        )
    stmt = stmt.where(
        ~Opportunity.title.ilike("%color:%"),
        ~Opportunity.title.ilike("%background-color:%"),
        ~Opportunity.title.ilike("%font-weight:%"),
        ~Opportunity.title.ilike("%display:%"),
        ~Opportunity.title.ilike("%justify-content:%"),
        ~Opportunity.title.ilike("%budgetYearsColumns%"),
        ~Opportunity.title.ilike("%plannedOpeningDate%"),
        ~Opportunity.title.ilike("%deadlineDate%"),
        ~Opportunity.title.ilike("%expectedGrants%"),
    )
    return stmt.order_by(Opportunity.close_date.asc().nullslast(), Opportunity.created_at.desc())


def _text_search_opportunities(
    db: Session,
    organization_id: str,
    query: str,
    *,
    limit: int = 10,
) -> list[tuple[Opportunity, float]]:
    """Full-text ILIKE search on title, entity, country, and summary.

    Searches on individual query tokens so partial and accented matches work
    (e.g. ``innovacion`` matches ``innovación``).
    """
    scope = or_(Opportunity.organization_id == organization_id, Opportunity.organization_id.is_(None))
    _ACCENT_MAP = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")
    tokens = [t.translate(_ACCENT_MAP) for t in re.findall(r"[a-zA-ZáéíóúñüÁÉÍÓÚÑÜ]+", query) if len(t) >= 2]
    if not tokens:
        return []
    stmt = select(Opportunity).where(scope)
    _unaccent = lambda col: sa_func.replace(sa_func.replace(sa_func.replace(sa_func.replace(
        sa_func.replace(sa_func.replace(sa_func.replace(sa_func.replace(
            sa_func.replace(sa_func.replace(sa_func.replace(sa_func.replace(
                col, "á", "a"), "é", "e"), "í", "i"), "ó", "o"), "ú", "u"),
            "ñ", "n"), "Á", "A"), "É", "E"), "Í", "I"), "Ó", "O"), "Ú", "U"), "Ñ", "N")
    filters = []
    for token in tokens:
        like = f"%{token}%"
        filters.append(
            or_(
                _unaccent(Opportunity.title).ilike(like),
                _unaccent(Opportunity.entity).ilike(like),
                _unaccent(Opportunity.country).ilike(like),
                _unaccent(Opportunity.summary).ilike(like),
            )
        )
    stmt = stmt.where(and_(*filters))
    stmt = stmt.order_by(Opportunity.created_at.desc()).limit(limit)
    rows = list(db.scalars(stmt))
    return [(row, 1.0) for row in rows]


def _lexical_search_score(query_terms: set[str], opportunity: Opportunity) -> float:
    """Compute a lexical match score for an opportunity against query terms."""
    if not query_terms:
        return 0.0
    haystack_parts = [
        opportunity.title,
        opportunity.entity,
        opportunity.country,
        opportunity.summary,
        opportunity.description,
        opportunity.raw_text,
        " ".join(opportunity.categories or []),
        " ".join(opportunity.topics or []),
        " ".join(opportunity.requirements or []),
        opportunity.official_url or "",
        opportunity.application_url or "",
    ]
    haystack = " ".join(part for part in haystack_parts if part).lower()
    if not haystack.strip():
        return 0.0
    haystack_terms = set(re.findall(r"[a-z0-9]+", haystack))
    overlap = len(query_terms & haystack_terms)
    coverage = overlap / max(len(query_terms), 1)
    title_boost = 0.15 if any(term in opportunity.title.lower() for term in query_terms) else 0.0
    category_boost = 0.1 if any(term in " ".join(opportunity.categories or []).lower() for term in query_terms) else 0.0
    return round(min(1.0, coverage + title_boost + category_boost), 4)


async def semantic_search_opportunities(
    db: Session,
    organization_id: str,
    query: str,
    *,
    limit: int = 10,
) -> list[tuple[Opportunity, float]]:
    """Search opportunities by combining text ILIKE with embedding similarity.

    1. First runs a text ILIKE search on title, entity, country, summary.
    2. Then re-ranks results using embedding cosine similarity when available.
    """
    text_results = _text_search_opportunities(db, organization_id, query, limit=limit * 3)
    if not text_results:
        return []

    query_vector = await build_embedding(query)
    scored: list[tuple[Opportunity, float]] = []
    for opportunity, _ in text_results:
        embedding = db.scalar(select(OpportunityEmbedding).where(OpportunityEmbedding.opportunity_id == opportunity.id))
        if embedding and embedding.embedding:
            similarity = cosine_similarity(query_vector, list(embedding.embedding))
        else:
            similarity = 0.0
        lexical = _lexical_search_score(
            {token for token in re.findall(r"[a-z0-9]+", query.lower()) if token},
            opportunity,
        )
        combined = round(min(1.0, (similarity * 0.6) + (lexical * 0.4)), 4)
        scored.append((opportunity, combined))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]
