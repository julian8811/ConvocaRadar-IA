from fastapi import APIRouter, Depends

from app.api.deps import verify_csrf
from app.api.v1 import admin, ai, alerts, auth, dashboard, internal, opportunities, ops, organizations, reports, sources, tasks

api_router = APIRouter(prefix="/api/v1")

# Auth routes need no CSRF — there is no session to protect yet.
api_router.include_router(auth.router, tags=["auth"])

# Public-facing routes: require X-CSRF-Protection on state-changing requests.
# Custom headers trigger a CORS preflight that validates the origin against
# the allowlist, preventing cross-site request forgery.
api_router.include_router(dashboard.router, tags=["dashboard"], dependencies=[Depends(verify_csrf)])
api_router.include_router(organizations.router, tags=["organizations"], dependencies=[Depends(verify_csrf)])
api_router.include_router(sources.router, tags=["sources"], dependencies=[Depends(verify_csrf)])
api_router.include_router(opportunities.router, tags=["opportunities"], dependencies=[Depends(verify_csrf)])
api_router.include_router(reports.router, tags=["reports"], dependencies=[Depends(verify_csrf)])
api_router.include_router(alerts.router, tags=["alerts"], dependencies=[Depends(verify_csrf)])
api_router.include_router(ai.router, tags=["ai"], dependencies=[Depends(verify_csrf)])
api_router.include_router(admin.router, tags=["admin"], dependencies=[Depends(verify_csrf)])
api_router.include_router(ops.router, tags=["ops"], dependencies=[Depends(verify_csrf)])
api_router.include_router(tasks.router, tags=["tasks"], dependencies=[Depends(verify_csrf)])

# Internal routes use an API key, not a cookie — no CSRF needed.
api_router.include_router(internal.router)
