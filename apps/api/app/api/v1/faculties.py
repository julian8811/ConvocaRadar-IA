from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization
from app.db.session import get_db
from app.models import Faculty, FacultyProfile, InstitutionalAxis, Organization

router = APIRouter()


@router.get("/faculties")
def list_faculties(organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)):
    faculties = list(db.scalars(select(Faculty).order_by(Faculty.key)))
    return {"faculties": [{"id": f.id, "key": f.key, "name": f.name, "slug": f.slug, "color": f.color, "icon": f.icon, "description": f.description} for f in faculties]}


@router.get("/axes")
def list_axes(organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)):
    axes = list(db.scalars(select(InstitutionalAxis).order_by(InstitutionalAxis.key)))
    return {"axes": [{"id": a.id, "key": a.key, "label": a.label, "description": a.description} for a in axes]}


@router.get("/faculty-profiles")
def list_faculty_profiles(organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)):
    profiles = list(db.scalars(select(FacultyProfile)))
    out = []
    for p in profiles:
        out.append({"id": p.id, "faculty_id": p.faculty_id, "axis_id": p.axis_id, "description": p.description, "threshold": p.threshold, "color": p.color, "version": p.version, "source_url": p.source_url})
    return out
