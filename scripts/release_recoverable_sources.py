from sqlalchemy import select
from app.db.session import SessionLocal
from app.models import Source
KEYS = {"argentina-investigacion", "cfe-uruguay", "uniandes-investigacion", "world-bank-procurement"}
with SessionLocal() as db:
    sources = list(db.scalars(select(Source).where(Source.key.in_(KEYS))))
    for source in sources:
        source.auto_paused = False
        source.selector_failures = 0
        source.last_error = None
    db.commit()
    print("released", [s.key for s in sources])
