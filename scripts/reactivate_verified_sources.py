from sqlalchemy import select
from app.db.session import SessionLocal
from app.models import Source
KEYS = {
 "aecid-espana", "agrosavia-convocatorias", "celac-convocatorias", "dian-contratacion",
 "faperj-brasil", "innpulsa-colombia-startup", "invima-convocatorias",
 "minagricultura-convocatorias", "parlatino-convocatorias", "javeriana-investigacion",
 "sennova-sena", "sgc-colombia", "world-bank-procurement"
}
with SessionLocal() as db:
    sources=list(db.scalars(select(Source).where(Source.key.in_(KEYS))))
    for s in sources:
        s.enabled=True; s.auto_paused=False; s.selector_failures=0; s.last_error=None
    db.commit(); print('reactivated', len(sources), [s.key for s in sources])
