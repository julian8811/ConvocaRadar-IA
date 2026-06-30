from datetime import UTC, datetime
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
import structlog

from app.api.deps import TOKEN_COOKIE_NAME, get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.core.task_queue import enqueue_seed_default_sources
from app.db.session import get_db
from app.models import AuditLog, Organization, OrganizationProfile, Role, User
from app.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    Token,
    UserRead,
)
from app.services import slugify

router = APIRouter()
logger = structlog.get_logger(__name__)

# Cookie name and lifetime for JWT auth (SEC-1.5). Name comes from deps to
# avoid an import cycle; the lifetime is local to this module.
TOKEN_COOKIE_MAX_AGE_SECONDS = 3600


def _set_token_cookie(response: Response, token: str) -> None:
    """Set the JWT as an HttpOnly, SameSite=Lax cookie for browser-based auth.

    SEC-1.5: dual-support migration — the cookie is the new primary path; the
    Authorization: Bearer header remains supported by get_current_user for legacy
    clients.
    """
    response.set_cookie(
        key=TOKEN_COOKIE_NAME,
        value=token,
        max_age=TOKEN_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def _clear_token_cookie(response: Response) -> None:
    """Delete the JWT cookie on logout."""
    response.delete_cookie(
        key=TOKEN_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=True,
        samesite="lax",
    )


@router.post("/auth/register", response_model=Token)
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)) -> Token:
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
        role=Role.member.value,
    )
    db.add(user)
    db.commit()
    # GAP-1: decouple source seeding from the request path. The Celery
    # task is idempotent (uses check-then-update on (organization_id, key))
    # so races with the bootstrap.py startup sweep are safe. The helper
    # already logs a warning inside the broker-down path; we also surface
    # a request-path warning when the helper returns None so on-call sees
    # the broker outage even if the helper's internal log is lost.
    task_id = enqueue_seed_default_sources(organization.id)
    if task_id is None:
        logger.warning(
            "seed_default_sources_enqueue_skipped",
            org_id=organization.id,
            user_id=user.id,
            hint="broker may be down; bootstrap.py startup sweep will retry",
        )
    token_str = create_access_token(
        user.id, {"organization_id": organization.id}, scope="access"
    )
    _set_token_cookie(response, token_str)
    # Keep returning the token in the JSON body for legacy clients (SEC-1.5).
    return Token(access_token=token_str)


@router.post("/auth/login", response_model=Token)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> Token:
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token_str = create_access_token(
        user.id, {"organization_id": user.organization_id}, scope="access"
    )
    _set_token_cookie(response, token_str)
    # Keep returning the token in the JSON body for legacy clients (SEC-1.5).
    return Token(access_token=token_str)


@router.post("/auth/logout")
def logout(response: Response) -> dict[str, str]:
    """Clear the JWT cookie. Idempotent — no auth required to drop a session."""
    _clear_token_cookie(response)
    return {"detail": "Sesión cerrada"}


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)) -> User:
    return user


# PR2-3: change-password endpoint. Authenticated (PR1's scope=access is
# enforced by ``get_current_user``). On success we bump
# ``User.password_changed_at`` so PR1-4's JWT claim check invalidates any
# other in-flight session for the same user. The AuditLog row is the
# security trail; the password hash itself is never written to the log.
@router.post("/auth/change-password", status_code=204)
def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    if not verify_password(payload.current_password, user.password_hash):
        # Constant message — do not leak whether the user exists.
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    user.password_changed_at = datetime.now(UTC)
    db.add(
        AuditLog(
            organization_id=user.organization_id,
            user_id=user.id,
            action="change_password",
            resource_type="user",
            resource_id=user.id,
        )
    )
    db.commit()
    logger.info("auth.change_password", user_id=user.id)
    return Response(status_code=204)
