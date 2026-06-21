from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.db.seed import seed_default_sources
from app.models import Organization, OrganizationProfile, User
from app.schemas import LoginRequest, RegisterRequest, Token, UserRead
from app.services import slugify

router = APIRouter()


@router.post("/auth/register", response_model=Token)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> Token:
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    organization = Organization(
        name=payload.organization_name,
        slug=slugify(payload.organization_name),
        type=payload.organization_type,
        country=payload.country,
    )
    db.add(organization)
    db.flush()
    db.add(
        OrganizationProfile(
            organization_id=organization.id,
            country=payload.country,
            organization_type=payload.organization_type,
            areas_of_interest=["innovación", "emprendimiento"],
            funding_types=["grant", "cofinancing"],
            preferred_currencies=["COP", "USD"],
        )
    )
    user = User(
        email=payload.email,
        name=payload.name,
        password_hash=hash_password(payload.password),
        organization_id=organization.id,
        role="admin",
    )
    db.add(user)
    seed_default_sources(db, organization)
    db.commit()
    return Token(access_token=create_access_token(user.id, {"organization_id": organization.id}))


@router.post("/auth/login", response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> Token:
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return Token(access_token=create_access_token(user.id, {"organization_id": user.organization_id}))


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)) -> User:
    return user
