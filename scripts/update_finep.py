from sqlalchemy import select
from app.db.session import SessionLocal
from app.models import Source
with SessionLocal() as db:
 s=db.scalar(select(Source).where(Source.key=="finep-brasil"))
 if s:
  s.base_url="https://www.finep.gov.br/oportunidades"; s.enabled=True; s.auto_paused=False; s.last_error=None; s.selector_failures=0; db.commit(); print("updated",s.key,s.base_url)
