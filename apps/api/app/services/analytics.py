"""Backfill helpers and analytics distribution functions.

Extracted from ``_legacy.py`` (PR B-2). Provides regex-based and AI-assisted
backfill of ``close_date`` and ``funding_amount`` for existing opportunities,
plus dashboard distribution/breakdown queries (score, funding, source,
timeline, category).

Dependencies on ``inferred_opportunity_status``, ``_parse_ai_close_date``,
``_parse_funding_amount``, and ``create_ai_extraction`` are imported from
``_legacy.py`` — they will be extracted to their own module in later PRs.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Opportunity, OpportunityScore, Source
from app.schemas import DashboardBreakdownItem

# ── Functions still in _legacy.py (not yet extracted) ──────────────────────
from app.services._legacy import (
    _parse_ai_close_date,
    _parse_funding_amount,
    create_ai_extraction,
    inferred_opportunity_status,
)

logger = logging.getLogger(__name__)


# ── Score distribution ─────────────────────────────────────────────────────


def get_score_distribution(db: Session, organization_id: str) -> list[DashboardBreakdownItem]:
    """Group opportunities by their score range: 0-25, 25-50, 50-75, 75-100."""
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    buckets = {"0-25": 0, "25-50": 0, "50-75": 0, "75-100": 0}
    rows = (
        db.execute(
            select(OpportunityScore.score)
            .join(Opportunity, OpportunityScore.opportunity_id == Opportunity.id)
            .where(scope, OpportunityScore.organization_id == organization_id)
        )
        .scalars()
        .all()
    )
    for score in rows:
        if score is None:
            continue
        if score < 25:
            buckets["0-25"] += 1
        elif score < 50:
            buckets["25-50"] += 1
        elif score < 75:
            buckets["50-75"] += 1
        else:
            buckets["75-100"] += 1
    return [
        DashboardBreakdownItem(name=k, total=v)
        for k, v in buckets.items()
        if v > 0
    ]


# ── Regex backfill — close date ────────────────────────────────────────────


def _backfill_close_date_text(opp: Opportunity) -> str:
    """Combine all text fields for close_date regex extraction."""
    return " ".join(part for part in [opp.title, opp.summary, opp.description, opp.raw_text] if part)


def backfill_close_dates(db: Session, organization_id: str, *, limit: int = 500) -> dict[str, int]:
    """Extract ``close_date`` from existing text for opportunities that have
    ``close_date IS NULL``. Uses the same regex-based ``extract_close_date``
    function used during scraping (no AI calls).
    """
    from app.connectors.common import extract_close_date

    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    stmt = (
        select(Opportunity)
        .where(scope, Opportunity.close_date.is_(None))
        .limit(limit)
    )
    opportunities = list(db.scalars(stmt))
    updated = 0
    for opp in opportunities:
        text = _backfill_close_date_text(opp)
        parsed = extract_close_date(text)
        if parsed:
            opp.close_date = parsed
            opp.status = inferred_opportunity_status(
                parsed,
                " ".join([opp.summary or "", opp.raw_text or ""]),
            )
            opp.updated_at = datetime.now(UTC).replace(tzinfo=None)
            updated += 1
    db.commit()
    return {"total": len(opportunities), "updated": updated}


# ── Regex backfill — funding amount ────────────────────────────────────────


def backfill_funding_amounts(db: Session, organization_id: str, *, limit: int = 500) -> dict[str, int]:
    """Parse ``funding_amount_raw`` into ``funding_amount_value`` + ``funding_amount_currency``
    for existing opportunities that have raw text but no parsed value yet.
    Uses the local regex parser only — no AI calls.
    """
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    stmt = (
        select(Opportunity)
        .where(
            scope,
            Opportunity.funding_amount_raw.isnot(None),
            Opportunity.funding_amount_value.is_(None),
        )
        .limit(limit)
    )
    opportunities = list(db.scalars(stmt))
    updated = 0
    for opp in opportunities:
        parsed_value, parsed_currency = _parse_funding_amount(opp.funding_amount_raw)
        if parsed_value is not None:
            opp.funding_amount_value = parsed_value
            opp.funding_amount_currency = parsed_currency
            updated += 1
    db.commit()
    return {"total": len(opportunities), "updated": updated}


# ── AI backfill — close date ───────────────────────────────────────────────


def _opportunity_combined_text(opp: Opportunity) -> str:
    """Combine all text fields of an opportunity for AI extraction."""
    return " ".join(
        part for part in [opp.title, opp.summary, opp.description, opp.raw_text]
        if part
    )


async def backfill_close_dates_ai(db: Session, organization_id: str, *, limit: int = 100) -> dict[str, int]:
    """Use AI (LLM) to extract close_date for opportunities that are missing it.

    Calls ``create_ai_extraction`` on each opportunity's combined text and
    updates the record if a close_date is found. More expensive than the
    regex-based backfill but can find dates in free-form text that the
    regex patterns miss.

    Processes up to ``limit`` opportunities per call. Each AI call costs
    tokens so keep batches small (10-50 recommended).
    """
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    stmt = (
        select(Opportunity)
        .where(scope, Opportunity.close_date.is_(None))
        .order_by(Opportunity.updated_at.desc())
        .limit(limit)
    )
    opportunities = list(db.scalars(stmt))
    processed = 0
    updated = 0
    for opp in opportunities:
        try:
            text = _opportunity_combined_text(opp)
            if not text.strip():
                continue
            processed += 1
            extraction = await create_ai_extraction(text)
            close_date = _parse_ai_close_date(extraction.get("close_date"))
            if close_date:
                opp.close_date = close_date
                opp.status = inferred_opportunity_status(
                    close_date,
                    " ".join([opp.summary or "", opp.raw_text or ""]),
                )
                opp.updated_at = datetime.now(UTC).replace(tzinfo=None)
                updated += 1
        except Exception:
            logger.warning("backfill_close_dates_ai.skip", opportunity_id=opp.id)
            continue
    db.commit()
    return {"total": len(opportunities), "processed": processed, "updated": updated}


# ── AI backfill — funding amount ───────────────────────────────────────────


async def backfill_funding_amounts_ai(db: Session, organization_id: str, *, limit: int = 100) -> dict[str, int]:
    """Use AI (LLM) to extract ``funding_amount_raw`` for opportunities missing it.

    Calls ``create_ai_extraction`` on each opportunity's combined text and
    updates ``funding_amount_raw`` + ``funding_amount_value`` +
    ``funding_amount_currency`` if parsed. Regex is tried first; AI is the
    fallback. Batch small (10-50) due to token cost.
    """
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    stmt = (
        select(Opportunity)
        .where(scope, Opportunity.funding_amount_raw.is_(None))
        .order_by(Opportunity.confidence_score.desc())
        .limit(limit)
    )
    opportunities = list(db.scalars(stmt))
    processed = 0
    updated = 0
    for opp in opportunities:
        try:
            text = _opportunity_combined_text(opp)
            if not text.strip():
                continue
            processed += 1
            extraction = await create_ai_extraction(text)
            raw = extraction.get("funding_amount_raw")
            if raw and isinstance(raw, str) and raw.strip():
                opp.funding_amount_raw = raw.strip()
                parsed_value, parsed_currency = _parse_funding_amount(raw)
                if parsed_value is not None:
                    opp.funding_amount_value = parsed_value
                    opp.funding_amount_currency = parsed_currency
                opp.updated_at = datetime.now(UTC).replace(tzinfo=None)
                updated += 1
        except Exception:
            logger.warning("backfill_funding_amounts_ai.skip", opportunity_id=opp.id)
            continue
    db.commit()
    return {"total": len(opportunities), "processed": processed, "updated": updated}


# ── Funding ranges distribution ────────────────────────────────────────────


def get_funding_ranges(db: Session, organization_id: str) -> list[DashboardBreakdownItem]:
    """Group opportunities by their funding amount range."""
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    buckets = {
        "<$100K": 0,
        "$100K-$500K": 0,
        "$500K-$1M": 0,
        "$1M-$5M": 0,
        ">$5M": 0,
    }
    rows = (
        db.execute(
            select(Opportunity.funding_amount_value)
            .where(scope, Opportunity.funding_amount_value.isnot(None))
        )
        .scalars()
        .all()
    )
    for amount in rows:
        if amount is None:
            continue
        if amount < 100_000:
            buckets["<$100K"] += 1
        elif amount < 500_000:
            buckets["$100K-$500K"] += 1
        elif amount < 1_000_000:
            buckets["$500K-$1M"] += 1
        elif amount < 5_000_000:
            buckets["$1M-$5M"] += 1
        else:
            buckets[">$5M"] += 1
    return [
        DashboardBreakdownItem(name=k, total=v)
        for k, v in buckets.items()
        if v > 0
    ]


# ── Source contribution ─────────────────────────────────────────────────────


def get_source_contribution(db: Session, organization_id: str) -> list[DashboardBreakdownItem]:
    """Top 10 sources by the number of opportunities they contributed."""
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    rows = (
        db.execute(
            select(Source.name, func.count())
            .join(Opportunity, Opportunity.source_id == Source.id)
            .where(scope)
            .group_by(Source.name)
            .order_by(func.count().desc())
            .limit(10)
        )
        .all()
    )
    return [DashboardBreakdownItem(name=name or "Unknown", total=count) for name, count in rows]


# ── Timeline ────────────────────────────────────────────────────────────────


def get_opportunities_timeline(db: Session, organization_id: str) -> list[DashboardBreakdownItem]:
    """Count opportunities scraped per month (last 12 months)."""
    from datetime import datetime as dt

    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    cutoff = dt.now(UTC).replace(tzinfo=None) - timedelta(days=365)
    rows = (
        db.execute(
            select(
                func.date_trunc("month", Opportunity.created_at).label("month"),
                func.count(),
            )
            .where(scope, Opportunity.created_at >= cutoff)
            .group_by("month")
            .order_by("month")
        )
        .all()
    )
    return [
        DashboardBreakdownItem(
            name=str(month.strftime("%Y-%m")) if month else "Unknown",
            total=count,
        )
        for month, count in rows
    ]


# ── Category distribution ──────────────────────────────────────────────────


def get_category_distribution(db: Session, organization_id: str) -> list[DashboardBreakdownItem]:
    """Count opportunities grouped by their source's category tags.

    Source.category is a JSON array stored as a PostgreSQL JSONB column.
    Some PG versions (Supabase free tier) do not support cross-join
    lateral with jsonb_array_elements_text in SQLAlchemy. We fall back to
    fetching the raw rows and unnesting in Python.
    """
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    rows = (
        db.execute(
            select(Source.category)
            .join(Opportunity, Opportunity.source_id == Source.id)
            .where(scope)
        )
        .scalars()
        .all()
    )

    # Normalize category tags from English/mixed to Spanish.
    CATEGORY_MAP: dict[str, str] = {
        "grants": "subvenciones",
        "research": "investigación",
        "innovation": "innovación",
        "development": "desarrollo",
        "education": "educación",
        "health": "salud",
        "agriculture": "agricultura",
        "environment": "medio ambiente",
        "energy": "energía",
        "technology": "tecnología",
        "infrastructure": "infraestructura",
        "social": "social",
        "culture": "cultura",
        "science": "ciencia",
        "sustainability": "sostenibilidad",
        "entrepreneurship": "emprendimiento",
        "startup": "startup",
        "cooperation": "cooperación",
        "funding": "financiamiento",
        "investment": "inversión",
        "procurement": "contratación",
        "humanitarian": "humanitario",
        "climate": "clima",
        "digital": "digital",
        "mobility": "movilidad",
        "tourism": "turismo",
        "security": "seguridad",
        "defense": "defensa",
        "space": "espacio",
        "oceans": "océanos",
        "biodiversity": "biodiversidad",
        "water": "agua",
        "food": "alimentos",
        "healthcare": "salud",
        "pharma": "farmacéutica",
        "biotech": "biotecnología",
        "nanotech": "nanotecnología",
        "robotics": "robótica",
        "blockchain": "blockchain",
        "iot": "iot",
        "big data": "big data",
        "cybersecurity": "ciberseguridad",
        "cloud": "nube",
        "quantum": "cuántica",
        "semiconductors": "semiconductores",
        "renewable": "renovable",
        "nuclear": "nuclear",
        "hydrogen": "hidrógeno",
        "carbon": "carbono",
        "circular economy": "economía circular",
        "waste": "residuos",
        "recycling": "reciclaje",
        "gender": "género",
        "inclusion": "inclusión",
        "youth": "juventud",
        "indigenous": "indígena",
        "rural": "rural",
        "urban": "urbano",
        "migration": "migración",
        "peace": "paz",
        "governance": "gobernanza",
        "transparency": "transparencia",
        "anticorruption": "anticorrupción",
        "tax": "impuestos",
        "trade": "comercio",
        "exports": "exportaciones",
        "creative industries": "industrias creativas",
        "media": "medios",
        "sports": "deportes",
        "federal funding": "fondos federales",
        "horizon europe": "horizonte europa",
        "becas": "becas",
        "convocatorias": "convocatorias",
        "formacion": "formación",
        "financiamiento": "financiamiento",
        "garantias": "garantías",
        "tic": "tic",
        "agro": "agro",
        "pyme": "pyme",
        "capital-semilla": "capital semilla",
        "industria": "industria",
        "productividad": "productividad",
        "solidaria": "economía solidaria",
        "comunitario": "comunitario",
        "estadual": "estadual",
        "filantropia": "filantropía",
        "internet": "internet",
    }
    counter: Counter[str] = Counter()
    for category_list in rows:
        if isinstance(category_list, list):
            for cat in category_list:
                if isinstance(cat, str) and cat.strip():
                    translated = CATEGORY_MAP.get(cat.strip().lower(), cat.strip().lower())
                    counter[translated] += 1
    items = counter.most_common(12)
    return [DashboardBreakdownItem(name=cat, total=count) for cat, count in items]
