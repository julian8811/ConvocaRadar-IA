from sqlalchemy import select
from app.db.session import SessionLocal
from app.models import Source, Opportunity, SourceRun
with SessionLocal() as db:
 s=db.scalar(select(Source).where(Source.key=="fonacyt-bolivia"))
 if not s: print("not-found")
 else:
  o=db.scalar(select(Opportunity.id).where(Opportunity.source_id==s.id)); r=db.scalar(select(SourceRun.id).where(SourceRun.source_id==s.id))
  if o or r: raise SystemExit(f"blocked references opportunities={bool(o)} runs={bool(r)}")
  db.delete(s); db.commit(); print("deleted",s.id)
