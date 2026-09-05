from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization, get_current_user
from app.db.session import get_db
from app.models import Faculty, FacultyProfile, InstitutionalAxis, OpportunityAxisMatch, Organization, Role

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


@router.get("/faculties/matrix")
def faculty_matrix(organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)):
    """4x6 heatmap counts per faculty/axis for org."""
    rows = list(
        db.execute(
            select(OpportunityAxisMatch.faculty_id, OpportunityAxisMatch.axis_id, func.count(OpportunityAxisMatch.id))
            .where(OpportunityAxisMatch.organization_id == organization.id)
            .group_by(OpportunityAxisMatch.faculty_id, OpportunityAxisMatch.axis_id)
        ).all()
    )
    cells = [{"faculty_id": r[0], "axis_id": r[1], "count": r[2]} for r in rows]
    return {"cells": cells, "total": sum(c["count"] for c in cells)}


class ProfileUpdate(BaseModel):
    threshold: float | None = None
    description: str | None = None
    color: str | None = None


@router.put("/faculty-profiles/{profile_id}")
def update_profile(profile_id: str, payload: ProfileUpdate, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user.role != Role.admin.value:
        raise HTTPException(status_code=403, detail="Admin only")
    profile = db.get(FacultyProfile, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if payload.threshold is not None:
        if not 0 <= payload.threshold <= 1:
            raise HTTPException(status_code=422, detail="threshold must be 0..1")
        profile.threshold = payload.threshold
    if payload.description is not None:
        profile.description = payload.description
        profile.version += 1
        # Recompute embedding async? For sync use hash vec fallback
        try:
            from app.core.ai import build_embedding_sync

            profile.embedding = build_embedding_sync(payload.description, dimensions=1024)
        except Exception:
            pass
    if payload.color is not None:
        profile.color = payload.color
    db.commit()
    return {"id": profile.id, "threshold": profile.threshold, "description": profile.description, "color": profile.color, "version": profile.version}
