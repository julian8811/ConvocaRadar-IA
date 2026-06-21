from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization, get_current_user
from app.db.session import get_db
from app.models import Organization, OrganizationProfile, User
from app.schemas import OrganizationProfileRead, OrganizationProfileUpsert, OrganizationRead, OrganizationUpdate

router = APIRouter()


@router.get("/organizations/current", response_model=OrganizationRead)
def get_current(organization: Organization = Depends(get_current_organization)) -> Organization:
    return organization


@router.patch("/organizations/current", response_model=OrganizationRead)
def update_current(
    payload: OrganizationUpdate,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> Organization:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(organization, key, value)
    db.commit()
    db.refresh(organization)
    return organization


@router.get("/organizations/current/profile", response_model=OrganizationProfileRead)
def get_profile(
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> OrganizationProfile:
    profile = db.scalar(
        select(OrganizationProfile).where(OrganizationProfile.organization_id == organization.id)
    )
    if not profile:
        profile = OrganizationProfile(organization_id=organization.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


@router.put("/organizations/current/profile", response_model=OrganizationProfileRead)
def upsert_profile(
    payload: OrganizationProfileUpsert,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrganizationProfile:
    profile = db.scalar(
        select(OrganizationProfile).where(OrganizationProfile.organization_id == organization.id)
    )
    if not profile:
        profile = OrganizationProfile(organization_id=organization.id)
        db.add(profile)
    for key, value in payload.model_dump().items():
        setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile
