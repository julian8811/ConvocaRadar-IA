from __future__ import annotations

from sqlalchemy import select

from app.core.ai import infer_language
from app.db.session import SessionLocal
from app.models import Opportunity


UNCLEAR_CLOSE_DATE_RISK = "no se detectó una fecha de cierre"


def repair_existing_opportunities() -> dict[str, int]:
    """Repair deterministic metadata inconsistencies in existing records."""
    db = SessionLocal()
    repaired_risks = 0
    repaired_languages = 0
    try:
        opportunities = list(db.scalars(select(Opportunity)))
        for opportunity in opportunities:
            if opportunity.close_date and opportunity.risk_flags:
                cleaned = [
                    flag
                    for flag in opportunity.risk_flags
                    if UNCLEAR_CLOSE_DATE_RISK not in str(flag).lower()
                ]
                if cleaned != opportunity.risk_flags:
                    opportunity.risk_flags = cleaned
                    repaired_risks += 1

            combined_text = " ".join(
                value
                for value in (
                    opportunity.title,
                    opportunity.summary,
                    opportunity.description,
                    opportunity.raw_text,
                )
                if value
            )
            detected_language = infer_language(combined_text, fallback=opportunity.language or "es")
            if detected_language == "pt" and opportunity.language != "pt":
                opportunity.language = "pt"
                repaired_languages += 1

        db.commit()
        return {
            "risk_flags": repaired_risks,
            "languages": repaired_languages,
            "total": len(opportunities),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    print(repair_existing_opportunities())


if __name__ == "__main__":
    main()
