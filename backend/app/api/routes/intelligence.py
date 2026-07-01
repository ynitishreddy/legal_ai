import uuid
import json
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import LegalFact, LegalEntity, LegalEvidence, ClaimDefense, EntityRelationship
from app.schemas.intelligence import (
    LegalFactResponse,
    LegalEntityResponse,
    LegalEvidenceResponse,
    ClaimDefenseResponse,
    KnowledgeGraphResponse,
    CaseIntelligenceStatsResponse,
    ExtractionTriggerRequest,
    GraphNeighborsResponse,
    PathStep,
    GraphAnalyticsResponse
)
from app.services.case_intelligence.service import CaseIntelligenceService
from app.services.case_intelligence.graph_query import KnowledgeGraphQueryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intelligence", tags=["Case Intelligence"])


# 1. POST /api/intelligence/extract
@router.post(
    "/extract",
    status_code=status.HTTP_200_OK,
    summary="Triggers a single Case Intelligence extraction pass on a processed document"
)
def extract_document_knowledge(
    payload: ExtractionTriggerRequest,
    db: Session = Depends(get_db)
):
    try:
        service = CaseIntelligenceService(db)
        counts = service.extract_case_knowledge(payload.case_id, payload.document_id)
        return {"success": True, "message": "Extraction completed", "counts": counts}
    except Exception as exc:
        logger.error("API error during manual case intelligence extraction: %s", str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to run extraction pipeline: {str(exc)}"
        )


# 2. GET /api/intelligence/case/{case_id}
@router.get(
    "/case/{case_id}",
    response_model=KnowledgeGraphResponse,
    summary="Fetches formatted nodes and links for the interactive Legal Knowledge Graph visualization"
)
def get_case_knowledge_graph(
    case_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    try:
        service = CaseIntelligenceService(db)
        return service.get_knowledge_graph_data(case_id)
    except Exception as exc:
        logger.error("API error fetching knowledge graph data for case %s: %s", case_id, str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compile graph schema: {str(exc)}"
        )


# 3. GET /api/intelligence/facts
@router.get(
    "/facts",
    response_model=List[LegalFactResponse],
    summary="Retrieves paginated, searchable and filterable Legal Facts explorer items"
)
def list_case_facts(
    case_id: uuid.UUID = Query(...),
    document_id: Optional[uuid.UUID] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    query = db.query(LegalFact).filter(LegalFact.case_id == case_id)
    if document_id:
        query = query.filter(LegalFact.document_id == document_id)
    if search:
        query = query.filter(LegalFact.fact_text.ilike(f"%{search}%"))

    offset = (page - 1) * page_size
    return query.order_by(LegalFact.created_at.desc()).offset(offset).limit(page_size).all()


# 4. GET /api/intelligence/entities
@router.get(
    "/entities",
    response_model=List[LegalEntityResponse],
    summary="Retrieves paginated Case Entities matching category filters"
)
def list_case_entities(
    case_id: uuid.UUID = Query(...),
    entity_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    query = db.query(LegalEntity).filter(LegalEntity.case_id == case_id)
    if entity_type:
        query = query.filter(LegalEntity.entity_type == entity_type)
    if search:
        query = query.filter(LegalEntity.name.ilike(f"%{search}%"))

    offset = (page - 1) * page_size
    return query.order_by(LegalEntity.name.asc()).offset(offset).limit(page_size).all()


# 5. GET /api/intelligence/evidence
@router.get(
    "/evidence",
    response_model=List[LegalEvidenceResponse],
    summary="Retrieves paginated Legal Evidence list for the explorer panel"
)
def list_case_evidence(
    case_id: uuid.UUID = Query(...),
    evidence_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    query = db.query(LegalEvidence).filter(LegalEvidence.case_id == case_id)
    if evidence_type:
        query = query.filter(LegalEvidence.evidence_type == evidence_type)

    offset = (page - 1) * page_size
    return query.order_by(LegalEvidence.created_at.desc()).offset(offset).limit(page_size).all()


# 6. GET /api/intelligence/claims
@router.get(
    "/claims",
    response_model=List[ClaimDefenseResponse],
    summary="Retrieves paginated Claims and Defenses explorer items"
)
def list_case_claims(
    case_id: uuid.UUID = Query(...),
    type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    query = db.query(ClaimDefense).filter(ClaimDefense.case_id == case_id)
    if type:
        query = query.filter(ClaimDefense.type == type)

    offset = (page - 1) * page_size
    return query.order_by(ClaimDefense.created_at.desc()).offset(offset).limit(page_size).all()


# 7. GET /api/intelligence/statistics
@router.get(
    "/statistics",
    response_model=CaseIntelligenceStatsResponse,
    summary="Gets Case Intelligence extraction stats breakdown count metrics"
)
def get_case_intelligence_stats(
    case_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db)
):
    try:
        service = CaseIntelligenceService(db)
        return service.get_intelligence_statistics(case_id)
    except Exception as exc:
        logger.error("API error gathering intelligence metrics for case %s: %s", case_id, str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compile extraction stats: {str(exc)}"
        )


# 8. GET /api/intelligence/graph/neighbors
@router.get(
    "/graph/neighbors",
    response_model=GraphNeighborsResponse,
    summary="Fetches directly connected neighboring nodes and relationship edges for a specific graph node"
)
def get_node_neighbors(
    case_id: uuid.UUID = Query(...),
    node_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db)
):
    try:
        query_service = KnowledgeGraphQueryService(db)
        return query_service.get_neighbors(case_id, node_id)
    except Exception as exc:
        logger.error("API error loading node neighbors: %s", str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch neighbors: {str(exc)}"
        )


# 9. GET /api/intelligence/graph/path
@router.get(
    "/graph/path",
    response_model=List[PathStep],
    summary="Computes the shortest connection path between two node points in the Knowledge Graph"
)
def find_shortest_path(
    case_id: uuid.UUID = Query(...),
    start_node_id: uuid.UUID = Query(...),
    end_node_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db)
):
    try:
        query_service = KnowledgeGraphQueryService(db)
        return query_service.find_shortest_path(case_id, start_node_id, end_node_id)
    except Exception as exc:
        logger.error("API error computing node path: %s", str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compute path steps: {str(exc)}"
        )


# 10. GET /api/intelligence/graph/analytics
@router.get(
    "/graph/analytics",
    response_model=GraphAnalyticsResponse,
    summary="Computes structural node degree centralities and graph rankings"
)
def get_graph_analytics(
    case_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db)
):
    try:
        query_service = KnowledgeGraphQueryService(db)
        centrality = query_service.get_centrality_metrics(case_id)
        total_nodes = db.query(LegalEntity).filter(LegalEntity.case_id == case_id).count()
        total_edges = db.query(EntityRelationship).filter(EntityRelationship.case_id == case_id).count()
        
        return {
            "case_id": case_id,
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "centrality_ranking": centrality
        }
    except Exception as exc:
        logger.error("API error gathering graph analytics metrics: %s", str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compile graph metrics: {str(exc)}"
        )


# 11. GET /api/intelligence/entity/{id}/history
@router.get(
    "/entity/{entity_id}/history",
    summary="Fetches transaction resolution merge history for a resolved canonical entity"
)
def get_entity_merge_history(
    entity_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    entity = db.query(LegalEntity).filter(LegalEntity.id == entity_id).first()
    if not entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Entity not found"
        )
    
    merge_log = []
    if entity.merge_metadata:
        try:
            merge_log = json.loads(entity.merge_metadata)
        except Exception:
            pass

    return {
        "entity_id": str(entity_id),
        "name": entity.name,
        "resolution_status": entity.resolution_status,
        "merge_history": merge_log
    }
