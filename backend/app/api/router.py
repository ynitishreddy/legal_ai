from fastapi import APIRouter

from app.api.routes import analytics, auth, cases, chat, dashboard, documents, timeline, users

api_router = APIRouter(prefix="/api")

api_router.include_router(auth.router)
api_router.include_router(cases.router)
api_router.include_router(users.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)
api_router.include_router(timeline.router)
api_router.include_router(analytics.router)
api_router.include_router(dashboard.router)
