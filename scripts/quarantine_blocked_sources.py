from sqlalchemy import select
from app.db.session import SessionLocal
from app.models import Source
PATTERNS = ("HTTP 403", "HTTP 404", "Source URL host outside", "Wellcome returned an empty", "Innovamos page unavailable")
with SessionLocal() as db:
    sources = list(db.scalars(select(Source).where(Source.enabled.is_(True))))
    changed = []
    for source in sources:
        if source.last_error and any(source.last_error.startswith(pattern) for pattern in PATTERNS):
            if not source.auto_paused:
                source.auto_paused = True
                changed.append(source.key)
    db.commit()
    print(f"quarantined={len(changed)}")
    print("\n".join(changed))
