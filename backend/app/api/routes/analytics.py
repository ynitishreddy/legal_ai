import uuid
import io
import csv
import logging
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.analytics import AnalyticsService
from app.schemas.analytics import (
    AnalyticsOverviewResponse,
    CaseAnalyticsResponse,
    DocumentAnalyticsResponse,
    ProcessingAnalyticsResponse,
    EmbeddingAnalyticsResponse,
    VectorDbAnalyticsResponse,
    RetrievalAnalyticsResponse,
    ConversationAnalyticsResponse,
    LlmAnalyticsResponse,
    TokenAnalyticsResponse,
    CostAnalyticsResponse,
    CitationAnalyticsResponse,
    TimelineAnalyticsResponse,
    CaseIntelligenceAnalyticsResponse,
    KnowledgeGraphAnalyticsResponse,
    AiQualityAnalyticsResponse
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("", response_model=AnalyticsOverviewResponse, summary="Get high-level overview metrics")
def get_analytics_overview(
    case_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db)
):
    try:
        service = AnalyticsService(db)
        return service.get_overview(case_id)
    except Exception as exc:
        logger.error("API error loading analytics overview: %s", str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch overview: {str(exc)}"
        )


@router.get("/cases", response_model=CaseAnalyticsResponse, summary="Get Case metric details")
def get_case_analytics(case_id: Optional[uuid.UUID] = Query(None), db: Session = Depends(get_db)):
    service = AnalyticsService(db)
    return service.get_cached_or_compute("cases", case_id)


@router.get("/documents", response_model=DocumentAnalyticsResponse, summary="Get Document metric details")
def get_document_analytics(case_id: Optional[uuid.UUID] = Query(None), db: Session = Depends(get_db)):
    service = AnalyticsService(db)
    return service.get_cached_or_compute("documents", case_id)


@router.get("/processing", response_model=ProcessingAnalyticsResponse, summary="Get Processing metric details")
def get_processing_analytics(case_id: Optional[uuid.UUID] = Query(None), db: Session = Depends(get_db)):
    service = AnalyticsService(db)
    return service.get_cached_or_compute("processing", case_id)


@router.get("/embeddings", response_model=EmbeddingAnalyticsResponse, summary="Get Embedding generation metrics")
def get_embedding_analytics(case_id: Optional[uuid.UUID] = Query(None), db: Session = Depends(get_db)):
    service = AnalyticsService(db)
    return service.get_cached_or_compute("embeddings", case_id)


@router.get("/vector-db", response_model=VectorDbAnalyticsResponse, summary="Get Vector Database sync metrics")
def get_vector_analytics(case_id: Optional[uuid.UUID] = Query(None), db: Session = Depends(get_db)):
    service = AnalyticsService(db)
    return service.get_cached_or_compute("vector-db", case_id)


@router.get("/retrieval", response_model=RetrievalAnalyticsResponse, summary="Get Retriever search metrics")
def get_retrieval_analytics(case_id: Optional[uuid.UUID] = Query(None), db: Session = Depends(get_db)):
    service = AnalyticsService(db)
    return service.get_cached_or_compute("retrieval", case_id)


@router.get("/conversations", response_model=ConversationAnalyticsResponse, summary="Get Chat memory analytics")
def get_conversation_analytics(case_id: Optional[uuid.UUID] = Query(None), db: Session = Depends(get_db)):
    service = AnalyticsService(db)
    return service.get_cached_or_compute("conversations", case_id)


@router.get("/llm", response_model=LlmAnalyticsResponse, summary="Get LLM response latency & statistics")
def get_llm_analytics(case_id: Optional[uuid.UUID] = Query(None), db: Session = Depends(get_db)):
    service = AnalyticsService(db)
    return service.get_cached_or_compute("llm", case_id)


@router.get("/tokens", response_model=TokenAnalyticsResponse, summary="Get Prompt/Completion token metrics")
def get_token_analytics(case_id: Optional[uuid.UUID] = Query(None), db: Session = Depends(get_db)):
    service = AnalyticsService(db)
    return service.get_cached_or_compute("tokens", case_id)


@router.get("/costs", response_model=CostAnalyticsResponse, summary="Get accumulated AI spend trends")
def get_cost_analytics(case_id: Optional[uuid.UUID] = Query(None), db: Session = Depends(get_db)):
    service = AnalyticsService(db)
    return service.get_cached_or_compute("costs", case_id)


@router.get("/citations", response_model=CitationAnalyticsResponse, summary="Get citation metrics")
def get_citation_analytics(case_id: Optional[uuid.UUID] = Query(None), db: Session = Depends(get_db)):
    service = AnalyticsService(db)
    return service.get_cached_or_compute("citations", case_id)


@router.get("/timeline", response_model=TimelineAnalyticsResponse, summary="Get legal events timeline statistics")
def get_timeline_analytics(case_id: Optional[uuid.UUID] = Query(None), db: Session = Depends(get_db)):
    service = AnalyticsService(db)
    return service.get_cached_or_compute("timeline", case_id)


@router.get("/intelligence", response_model=CaseIntelligenceAnalyticsResponse, summary="Get extracted entity stats")
def get_intelligence_analytics(case_id: Optional[uuid.UUID] = Query(None), db: Session = Depends(get_db)):
    service = AnalyticsService(db)
    return service.get_cached_or_compute("intelligence", case_id)


@router.get("/knowledge-graph", response_model=KnowledgeGraphAnalyticsResponse, summary="Get graph edge counts")
def get_graph_analytics(case_id: Optional[uuid.UUID] = Query(None), db: Session = Depends(get_db)):
    service = AnalyticsService(db)
    return service.get_cached_or_compute("knowledge-graph", case_id)


@router.get("/quality", response_model=AiQualityAnalyticsResponse, summary="Get average confidence score details")
def get_quality_analytics(case_id: Optional[uuid.UUID] = Query(None), db: Session = Depends(get_db)):
    service = AnalyticsService(db)
    return service.get_cached_or_compute("quality", case_id)


@router.post("/refresh", summary="Forces snapshot recomputations for the case or globally")
def force_refresh_snapshots(
    case_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db)
):
    try:
        service = AnalyticsService(db)
        service.refresh_snapshots(case_id)
        return {"success": True, "message": "All cached metrics updated successfully"}
    except Exception as exc:
        logger.error("API error during manual analytics refresh: %s", str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refresh cached values: {str(exc)}"
        )


@router.get("/export", summary="Exports metric reports as download stream")
def export_analytics_csv(
    category: str = Query(..., description="One of the metric providers category keys"),
    case_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db)
):
    try:
        service = AnalyticsService(db)
        data = service.get_cached_or_compute(category, case_id)
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write Title
        writer.writerow(["ChronoLegal Analytics Report", category.upper(), datetime.now().isoformat()])
        writer.writerow([])
        
        # Write Metrics
        writer.writerow(["METRIC NAME", "VALUE", "UNIT"])
        for m in data.get("metrics", []):
            writer.writerow([m.get("name"), m.get("value"), m.get("unit", "")])
        
        writer.writerow([])
        
        # Write first chart if present
        for key in data.keys():
            if key != "metrics" and isinstance(data[key], list) and len(data[key]) > 0:
                first_item = data[key][0]
                if isinstance(first_item, dict) and "label" in first_item:
                    writer.writerow([key.upper() + " DISTRIBUTION"])
                    writer.writerow(["LABEL", "VALUE"])
                    for item in data[key]:
                        writer.writerow([item.get("label"), item.get("value")])
                    writer.writerow([])

        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=chronolegal_analytics_{category}.csv"}
        )
    except Exception as exc:
        logger.error("API error exporting CSV report: %s", str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compile report: {str(exc)}"
        )
