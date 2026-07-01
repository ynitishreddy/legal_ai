from fastapi import APIRouter

from app.api.routes import analytics, auth, cases, chat, dashboard, documents, processing, timeline, users, document_cleaning, document_chunking, embeddings, vectors, retrieval

api_router = APIRouter(prefix="/api")

api_router.include_router(auth.router)
api_router.include_router(cases.router)
api_router.include_router(users.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)
api_router.include_router(timeline.router)
api_router.include_router(analytics.router)
api_router.include_router(dashboard.router)
api_router.include_router(processing.router)
api_router.include_router(document_cleaning.router)
api_router.include_router(document_chunking.router)
api_router.include_router(embeddings.router)
api_router.include_router(vectors.router)
api_router.include_router(retrieval.router)




