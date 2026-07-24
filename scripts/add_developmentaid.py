from sqlalchemy import select
from app.db.session import SessionLocal
from app.models import Source
with SessionLocal() as db:
 s=db.scalar(select(Source).where(Source.key=="developmentaid-tenders"))
 if not s:
  s=Source(name="DevelopmentAid — Licitaciones y convocatorias",key="developmentaid-tenders",base_url="https://www.developmentaid.org/tenders/search?hiddenAdvancedFilters=0&locations=4&statuses=2,3,8,9,10",country="International",region="LatAm",source_type="html",category=["tenders","grants"],enabled=True,scraping_frequency="daily",allowed_domains=["developmentaid.org","www.developmentaid.org"],tier="strategic")
  db.add(s); db.commit(); print("created")
 else: print("exists")
