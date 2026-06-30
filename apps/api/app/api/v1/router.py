from fastapi import APIRouter

from app.api.v1 import admin, ai, alerts, auth, dashboard, internal, opportunities, ops, organizations, reports, sources, tasks

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(dashboard.router, tags=["dashboard"])
api_router.include_router(organizations.router, tags=["organizations"])
api_router.include_router(sources.router, tags=["sources"])
api_router.include_router(opportunities.router, tags=["opportunities"])
api_router.include_router(reports.router, tags=["reports"])
api_router.include_router(alerts.router, tags=["alerts"])
api_router.include_router(ai.router, tags=["ai"])
api_router.include_router(admin.router, tags=["admin"])
api_router.include_router(ops.router, tags=["ops"])
api_router.include_router(tasks.router, tags=["tasks"])
api_router.include_router(internal.router)
