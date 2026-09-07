"""Temporary PR29 diagnostic for shared pytest database visibility."""

from __future__ import annotations

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Opportunity, Organization, Source, User


def test_zzz_dump_visibility_state() -> None:
    db = SessionLocal()
    try:
        orgs = [
            (org.id, org.slug)
            for org in db.scalars(select(Organization).order_by(Organization.slug))
        ]
        users = [
            (user.email, user.organization_id, user.role)
            for user in db.scalars(
                select(User).where(User.email == "admin@convocaradar.io").order_by(User.id)
            )
        ]
        sources = [
            (source.id, source.key, source.organization_id)
            for source in db.scalars(select(Source).where(Source.key == "grants-gov"))
        ]
        fixtures = [
            (
                opp.id,
                opp.organization_id,
                opp.source_id,
                opp.external_id,
                opp.title,
                opp.close_date.isoformat() if opp.close_date else None,
                opp.status,
            )
            for opp in db.scalars(
                select(Opportunity)
                .where(
                    (Opportunity.external_id == "fixture-grants-2026")
                    | Opportunity.title.like("Test N+1 Opportunity%")
                    | Opportunity.title.like("Health %")
                )
                .order_by(Opportunity.created_at)
            )
        ]
    finally:
        db.close()

    raise AssertionError(
        "PR29_STATE "
        f"organizations={orgs!r} users={users!r} grants_sources={sources!r} "
        f"fixtures={fixtures!r}"
    )
