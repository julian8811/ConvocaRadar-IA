"""GenAI batch operations and weekly digest helpers.

Extracted from ``_legacy.py`` (PR B-3). Provides batch summarize/scoring
operations and weekly digest HTML rendering + email sending.

Dependencies on ``summarize_text`` (from ``opportunity.py``) and scoring helpers
(from ``app.services.scoring``) are imported directly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Opportunity,
    OpportunityScore,
    Organization,
    OrganizationProfile,
    Role,
    User,
)

# ── Functions extracted to opportunity.py ────────────────────────────────────
from app.services.opportunity import summarize_text

# ── Already-extracted scoring helpers ───────────────────────────────────────
from app.services.scoring import (
    _compute_score,
    calculate_score,
    priority_for_score,
)


# ── Batch summarize ─────────────────────────────────────────────────────────


def summarize_missing_opportunities(
    db: Session,
    organization_id: str | None,
    *,
    limit: int = 10,
) -> dict[str, int]:
    """Find opportunities without a summary and call ``summarize_text`` for each.

    Limited to ``limit`` per call to stay under the Gemini free-tier quota when
    the LLM provider is configured against ``generativelanguage.googleapis.com``.
    Returns ``{"processed": N, "summarized": M}`` where ``N`` is the number of
    candidates considered and ``M`` is the count that received a new summary.
    """
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    ) if organization_id else Opportunity.organization_id.is_(None)
    stmt = (
        select(Opportunity)
        .where(
            scope,
            or_(Opportunity.summary.is_(None), Opportunity.summary == ""),
        )
        .order_by(Opportunity.created_at.desc())
        .limit(limit)
    )
    candidates = list(db.scalars(stmt))
    summarized = 0
    for opportunity in candidates:
        source_text = (opportunity.raw_text or opportunity.description or "").strip()
        if not source_text:
            continue
        try:
            summary = summarize_text(source_text)
        except Exception:
            # Local fallback is non-throwing; remote calls may still fail. Skip
            # silently and let the next batch pick it up.
            continue
        if not summary:
            continue
        opportunity.summary = summary
        summarized += 1
    if summarized:
        db.commit()
    return {"processed": len(candidates), "summarized": summarized}


# ── Batch rescore ───────────────────────────────────────────────────────────


def rescore_all_opportunities(
    db: Session,
    organization_id: str,
    *,
    limit: int = 10,
) -> dict[str, int]:
    """Recalculate scores for ALL opportunities for this org, overwriting
    existing OpportunityScore rows. Uses the new multi-dimensional scorer.
    """
    organization = db.get(Organization, organization_id)
    profile = db.scalar(
        select(OrganizationProfile).where(OrganizationProfile.organization_id == organization_id)
    )
    if organization is None or profile is None:
        return {"processed": 0, "rescored": 0}

    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    opportunities = list(db.scalars(select(Opportunity).where(scope).limit(limit)))
    processed = len(opportunities)
    rescored = 0
    for opp in opportunities:
        existing = db.scalar(
            select(OpportunityScore).where(
                OpportunityScore.opportunity_id == opp.id,
                OpportunityScore.organization_id == organization_id,
            )
        )
        if existing:
            # Reuse existing row — update in place
            score = _compute_score(opp, profile)
            existing.score = min(round(score["raw"], 1), 100)
            existing.priority = priority_for_score(existing.score)
            existing.reasons = score["reasons"]
            existing.warnings = score["warnings"]
        else:
            new_score = calculate_score(db, opp, profile)
            db.add(new_score)
        rescored += 1
    db.commit()
    return {"processed": processed, "rescored": rescored}


# ── Score unscored ──────────────────────────────────────────────────────────


def score_unscored_opportunities(
    db: Session,
    organization_id: str,
    *,
    limit: int = 10,
) -> dict[str, int]:
    """Score opportunities that have no OpportunityScore row for this org yet.

    Returns ``{"processed": N, "scored": M}`` where ``N`` is the number of
    candidates considered and ``M`` is the count that received a new score.
    """
    # Default profile fallback: if the org has no profile yet, build a minimal
    # in-memory profile so calculate_score has something to compare against.
    organization = db.get(Organization, organization_id)
    profile = db.scalar(
        select(OrganizationProfile).where(OrganizationProfile.organization_id == organization_id)
    )
    if organization is None:
        return {"processed": 0, "scored": 0}

    if profile is None:
        profile = OrganizationProfile(
            organization_id=organization_id,
            country=organization.country or "Colombia",
        )
        db.add(profile)
        db.flush()

    # Use LEFT OUTER JOIN instead of NOT IN (subquery) — sqlite's NOT IN on
    # an empty subquery produces zero rows because NULL is the default, so
    # outer-join + IS NULL is the portable pattern.
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    stmt = (
        select(Opportunity)
        .outerjoin(
            OpportunityScore,
            and_(
                OpportunityScore.opportunity_id == Opportunity.id,
                OpportunityScore.organization_id == organization_id,
            ),
        )
        .where(scope, OpportunityScore.id.is_(None))
        .order_by(Opportunity.created_at.desc())
        .limit(limit)
    )
    candidates = list(db.scalars(stmt))
    scored = 0
    for opportunity in candidates:
        try:
            calculate_score(db, opportunity, profile)
            scored += 1
        except Exception:
            db.rollback()
            continue
    if scored:
        db.commit()
    return {"processed": len(candidates), "scored": scored}


# ── Weekly digest HTML ──────────────────────────────────────────────────────


def build_weekly_digest_html(
    *,
    organization: Organization,
    opportunities: list[Opportunity],
) -> str:
    """Render a simple HTML email for the weekly digest.

    Top 5 opportunities by recency. Intentionally minimal — this is the MVP
    digest, not a magazine layout. The frontend has the real design system.
    """
    rows: list[str] = []
    for item in opportunities[:5]:
        title = escape(item.title or "Convocatoria sin título")
        entity = escape(item.entity or "Sin entidad")
        country = escape(item.country or "")
        summary = escape((item.summary or item.description or "")[:280])
        url = item.official_url or item.application_url or "#"
        rows.append(
            f"<tr><td style='padding:12px 0;border-bottom:1px solid #e2e8f0;'>"
            f"<a href='{escape(url)}' style='font-size:15px;font-weight:600;color:#0f172a;text-decoration:none;'>{title}</a>"
            f"<p style='margin:4px 0 0;font-size:12px;color:#64748b;'>{entity} · {country}</p>"
            f"<p style='margin:6px 0 0;font-size:13px;color:#334155;line-height:1.5;'>{summary}</p>"
            f"</td></tr>"
        )
    body_rows = "".join(rows) or (
        "<tr><td style='padding:16px 0;color:#64748b;'>No se detectaron oportunidades nuevas esta semana.</td></tr>"
    )
    return (
        "<html><body style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f8fafc;padding:24px;'>"
        f"<div style='max-width:640px;margin:0 auto;background:#ffffff;padding:24px;border-radius:12px;border:1px solid #e2e8f0;'>"
        f"<h1 style='margin:0 0 4px;font-size:20px;color:#0f172a;'>Resumen semanal · {escape(organization.name)}</h1>"
        f"<p style='margin:0 0 16px;font-size:13px;color:#64748b;'>"
        f"Top {min(len(opportunities), 5)} convocatorias detectadas en los últimos 7 días."
        f"</p>"
        f"<table style='width:100%;border-collapse:collapse;'>{body_rows}</table>"
        f"<p style='margin:16px 0 0;font-size:12px;color:#94a3b8;'>"
        f"ConvocaRadar IA · Generado automáticamente"
        f"</p></div></body></html>"
    )


# ── Weekly digest send ──────────────────────────────────────────────────────


def send_weekly_digest(db: Session, organization_id: str) -> bool:
    """Send a weekly digest email to the first admin user of the org.

    Returns True if the email was handed off to the SMTP transport (or
    recorded as a dev dry-run), False on hard failure. The digest is
    limited to the most recent 7 days of opportunities visible to the org.
    """
    from app.core.email import send_email

    organization = db.get(Organization, organization_id)
    if organization is None:
        return False

    # Prefer configured default recipient, fall back to first admin user
    settings = get_settings()
    recipient = settings.alert_default_recipient
    if not recipient:
        recipient = db.scalar(
            select(User.email)
            .where(User.organization_id == organization_id, User.role == Role.admin.value)
            .order_by(User.created_at.asc())
            .limit(1)
        )
    if not recipient:
        return False

    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
    scope = or_(
        Opportunity.organization_id == organization_id,
        Opportunity.organization_id.is_(None),
    )
    opportunities = list(
        db.scalars(
            select(Opportunity)
            .where(scope, Opportunity.created_at >= cutoff)
            .order_by(Opportunity.created_at.desc())
            .limit(5)
        )
    )
    html_body = build_weekly_digest_html(organization=organization, opportunities=opportunities)
    subject = f"ConvocaRadar · Resumen semanal ({len(opportunities)} nuevas)"
    try:
        send_email(
            recipient=recipient,
            subject=subject,
            message=html_body,
        )
    except Exception:
        return False
    return True
