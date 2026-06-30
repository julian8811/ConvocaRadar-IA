from datetime import UTC, datetime
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
import structlog

from app.api.deps import TOKEN_COOKIE_NAME, get_current_user
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import create_access_token, hash_password, verify_password
from app.core.task_queue import enqueue_seed_default_sources
from app.db.session import get_db
from app.models import AuditLog, Organization, OrganizationProfile, Role, User
from app.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
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

# PR2-4: in-process rate limiter for the forgot-password endpoint. 5
# requests per email per hour is the documented contract (spec:
# "6th request in an hour is throttled"). The limiter is module-level so
# state survives across requests within a single process; a process
# restart resets the bucket, which is acceptable for the MVP per design
# §4. Tests clear the bucket between cases via ``forgot_limiter._buckets.clear()``.
forgot_limiter = SlidingWindowLimiter(max_requests=5, window_seconds=3600)


def _password_changed_at_epoch(user: User) -> int:
    """Return ``user.password_changed_at`` as epoch seconds, or 0 when NULL.

    Used by both ``forgot-password`` (to embed the claim in the reset
    JWT) and ``reset-password`` (to compare against the claim). Keeping
    the conversion in one place ensures the two endpoints agree on the
    semantics — both treat NULL as the floor (epoch 0) so a user who
    has never changed their password can still request a reset.
    """
    if user.password_changed_at is None:
        return 0
    return int(user.password_changed_at.timestamp())


def _password_reset_url(token: str) -> str:
    """Build the user-facing reset URL the endpoint logs at info level.

    Centralized so the frontend route (``/reset?token=...``) and the
    backend stay in sync — the design §"reset_version" links the two.
    """
    from app.core.config import get_settings

    settings = get_settings()
    base = settings.frontend_url.rstrip("/")
    return f"{base}/reset?token={token}"


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


# PR2-4: forgot-password endpoint. Public, rate-limited, constant
# response. Signs a ``scope="password_reset"`` JWT for known emails and
# logs the reset URL at info level (or, when SMTP is configured, calls
# ``send_email``). Unknown emails are silently ignored — no DB write,
# no email, no audit log. The constant 200 response prevents email
# enumeration.
@router.post("/auth/forgot-password")
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    # Key the limiter on the lowercased email so case variations
    # ("Alice@..." vs "alice@...") share the same budget. EmailStr
    # normalizes the form via Pydantic, but lower() is the explicit
    # signal that we want this.
    email_key = payload.email.lower()
    if not forgot_limiter.check(email_key):
        # 429 — but DO NOT log or write audit; the throttling itself
        # is the only side effect. Logging here would create a noisy
        # audit trail under attack without adding security value.
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Try again later.",
        )

    # Constant detail — the response body for a known email is
    # IDENTICAL to the body for an unknown email so a phishing site
    # cannot enumerate which addresses are registered.
    detail = "If the email exists, a reset link was sent"

    user = db.scalar(select(User).where(User.email == email_key))
    if user is not None:
        # Sign a password-reset JWT carrying the current
        # ``password_changed_at`` epoch. The reset-password endpoint
        # compares this claim against the live row to reject tokens
        # issued before the most recent change.
        token = create_access_token(
            user.id,
            extra={"password_changed_at": _password_changed_at_epoch(user)},
            scope="password_reset",
        )
        reset_url = _password_reset_url(token)
        logger.info(
            "auth.forgot_password",
            user_id=user.id,
            reset_url=reset_url,
            smtp_configured=bool(get_settings_smtp_configured()),
        )
        # When SMTP is wired (future change), call ``send_email`` here
        # with the reset URL as the body. The dry-run fallback in
        # ``app.core.email.send_email`` returns ``status="sent",
        # dry_run=True`` when no host is configured — the same return
        # shape as a real send, so the call site is stable.
        try:
            from app.core.email import send_email

            send_email(
                recipient=user.email,
                subject="Reset your ConvocaRadar IA password",
                message=(
                    "You (or someone using your email) requested a password "
                    "reset. Click the link below within 1 hour:\n\n"
                    f"{reset_url}\n\n"
                    "If you did not request this, you can safely ignore this "
                    "message — your password will not change."
                ),
            )
        except Exception as exc:  # noqa: BLE001 — never let SMTP errors leak to the user
            # SMTP must never break the forgot-password contract. The
            # reset URL is already in the log; the user can still copy
            # it from their inbox in a real environment, and the 200
            # response keeps the enumeration contract intact.
            logger.warning("auth.forgot_password.email_failed", error=str(exc))
        db.add(
            AuditLog(
                organization_id=user.organization_id,
                user_id=user.id,
                action="forgot_password_requested",
                resource_type="user",
                resource_id=user.id,
                metadata_json={"ip": _client_ip(request)},
            )
        )
        db.commit()
    return {"detail": detail}


def get_settings_smtp_configured() -> str:
    """Tiny helper: return the SMTP host (or empty string) for the audit log.

    Kept as a function so tests can mock it without monkey-patching the
    settings module global.
    """
    from app.core.config import get_settings

    return get_settings().smtp_host or ""


def _client_ip(request: Request) -> str:
    """Best-effort client IP extraction for the audit log.

    Honors ``X-Forwarded-For`` (the first hop) when present — Render
    injects this — and falls back to the socket address. Never raises.
    """
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        # First entry is the originating client; subsequent entries are
        # intermediate proxies.
        return xff.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
