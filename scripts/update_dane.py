from sqlalchemy import select
from app.db.session import SessionLocal
from app.models import Source
with SessionLocal() as db:
    source = db.scalar(select(Source).where(Source.key == "dane-convocatorias"))
    if source:
        source.base_url = "https://www.dane.gov.co/index.php/component/content/category/275-servicios-al-ciudadano/276-convocatorias-y-contratacion?Itemid=109"
        source.enabled = True
        source.auto_paused = False
        source.last_error = None
        source.selector_failures = 0
        db.commit()
        print("updated", source.key)
