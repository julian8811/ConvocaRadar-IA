#!/usr/bin/env python3
"""Maintenance tasks for ConvocaRadar-IA.

Usage:
    python scripts/maintenance.py --cleanup-runs     # Delete old failed runs
    python scripts/maintenance.py --fix-countries     # Fix 'Por validar' countries
    python scripts/maintenance.py --all               # Run all tasks
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

from sqlalchemy import select, func, and_

from app.connectors.common import infer_country_from_entity
from app.db.session import SessionLocal
from app.models import Opportunity, SourceRun


def cleanup_failed_runs(dry_run: bool = True) -> int:
    """Delete old failed SourceRun records (older than 7 days)."""
    from datetime import UTC, datetime, timedelta

    db = SessionLocal()
    try:
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
        old_failed = list(
            db.scalars(
                select(SourceRun).where(
                    SourceRun.status.in_(["failed", "degraded"]),
                    SourceRun.finished_at.isnot(None),
                    SourceRun.finished_at < cutoff,
                )
            )
        )
        count = len(old_failed)
        if not dry_run:
            for run in old_failed:
                db.delete(run)
            db.commit()
            print(f"Deleted {count} old failed runs")
        else:
            print(f"Would delete {count} old failed runs (use --no-dry-run to execute)")
        return count
    finally:
        db.close()


def fix_countries(dry_run: bool = True) -> int:
    """Fix opportunities with 'Por validar' or empty country."""
    db = SessionLocal()
    try:
        bad = list(
            db.scalars(
                select(Opportunity).where(
                    Opportunity.country.in_(["Por validar", "Sin dato", ""])
                )
            )
        )
        fixed = 0
        for opp in bad:
            inferred = infer_country_from_entity(
                getattr(opp, "entity", None),
                getattr(opp, "official_url", None),
            )
            if inferred and inferred not in ("Por validar", "Sin dato", ""):
                if not dry_run:
                    opp.country = inferred
                fixed += 1

        if not dry_run:
            db.commit()
            print(f"Fixed {fixed} opportunities with wrong country")
        else:
            print(f"Would fix {fixed}/{len(bad)} opportunities (use --no-dry-run to execute)")
        return fixed
    finally:
        db.close()


if __name__ == "__main__":
    dry_run = "--no-dry-run" not in sys.argv

    if "--cleanup-runs" in sys.argv or "--all" in sys.argv:
        cleanup_failed_runs(dry_run=dry_run)
    if "--fix-countries" in sys.argv or "--all" in sys.argv:
        fix_countries(dry_run=dry_run)
