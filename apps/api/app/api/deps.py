from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Organization, OrganizationProfile, User

# SEC-1.5: cookie name for JWT auth. Imported by app.api.v1.auth to set/clear
# the cookie on login/logout/register.
TOKEN_COOKIE_NAME = "convocaradar_token"

# auto_error=False: don't raise when no header is present, so the cookie
# fallback can take over (SEC-1.5 dual-support).
bearer = HTTPBearer(auto_error=False)


def _extract_token(
    credentials: Optional[HTTPAuthorizationCredentials],
    request: Request,
) -> Optional[str]:
    """SEC-1.5: Prefer the cookie (browser auth); fall back to Authorization
    header (legacy clients / direct API users).

    Cookie-first matches the user-facing request flow: the browser auto-sends
    the cookie on same-origin requests, so the cookie path is the primary
    authentication mechanism now.
    """
    cookie_token = request.cookies.get(TOKEN_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    if credentials and credentials.credentials:
        return credentials.credentials
    return None


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    token = _extract_token(credentials, request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    # PR1-4: scope check. Tokens minted for password_reset (or any other
    # non-access purpose) must not authenticate protected routes. Tokens
    # without a scope claim are accepted as scope="access" for backward
    # compatibility with pre-PR1 cookies still in users' browsers.
    token_scope = payload.get("scope", "access")
    if token_scope != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token scope does not allow access to this resource",
        )
    # Expose the scope on request.state so downstream handlers (e.g. the
    # audit log) can read it without re-decoding the token.
    request.state.scope = token_scope
    user_id = payload.get("sub")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def get_current_organization(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Organization:
    if not user.organization_id:
        raise HTTPException(status_code=400, detail="User has no organization")
    organization = db.get(Organization, user.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    return organization


def get_current_profile(
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> OrganizationProfile:
    profile = db.scalar(
        select(OrganizationProfile).where(OrganizationProfile.organization_id == organization.id)
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Organization profile not found")
    return profile
