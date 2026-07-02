import json
import logging
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.models import User, Case, QAHistory, ContradictionReport, EvidenceRanking
from app.schemas.reasoning import (
    LegalQARequest,
    LegalQAResponse,
    QueryClassificationResponse,
    EvidenceRankingResponse,
    EvidenceItem,
    CitationRankingResponse,
    CitationItem,
    ContradictionReportResponse,
    ContradictionItem,
    ComparisonRequest,
    ComparisonResponse,
    ResearchSessionCreate,
    ResearchNoteCreate,
    ResearchNoteResponse,
    ResearchSessionResponse,
    QAAnalyticsResponse,
)
from app.services.reasoning.engine import LegalReasoningEngine
from app.services.reasoning.research import ResearchWorkflowEngine
from app.services.reasoning.comparative import ComparativeCaseAnalyzer
from app.services.reasoning.query_understanding import QueryUnderstandingService
from app.services.reasoning.evidence import EvidenceRankingEngine, CitationRankingEngine
from app.services.reasoning.contradiction import ContradictionDetectionEngine
from app.services.reasoning.validation import AnswerValidationEngine
from app.services.reasoning.confidence import ConfidenceCalibrationEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reasoning", tags=["Legal Reasoning"])


# 1. POST /api/reasoning/qa
@router.post("/qa", response_model=LegalQAResponse)
async def execute_reasoning_qa(
    payload: LegalQARequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    engine = LegalReasoningEngine(db)
    try:
        if payload.stream:
            # For non-stream validation of stream payload, we redirect to streaming handler or raise error
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Use /api/reasoning/qa/stream for streaming requests."
            )
        
        result = await engine.reason_query(
            question=payload.question,
            user_id=current_user.id,
            case_id=payload.case_id,
            provider=payload.provider,
            model=payload.model,
            top_k=payload.top_k,
            threshold=payload.threshold,
        )
        return result
    except Exception as e:
        logger.error("execute_reasoning_qa error: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reasoning QA execution failed: {str(e)}"
        )


# 2. POST /api/reasoning/qa/stream
@router.post("/qa/stream")
async def execute_reasoning_qa_stream(
    payload: LegalQARequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    engine = LegalReasoningEngine(db)
    
    async def event_generator():
        try:
            stream_gen = engine.stream_reason_query(
                question=payload.question,
                user_id=current_user.id,
                case_id=payload.case_id,
                provider=payload.provider,
                model=payload.model,
                top_k=payload.top_k,
                threshold=payload.threshold,
            )
            async for event in stream_gen:
                yield f"event: {event['event']}\ndata: {event['data']}\n\n"
        except Exception as e:
            logger.error("execute_reasoning_qa_stream error: %s", e)
            yield f"event: error\ndata: {str(e)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# 3. POST /api/reasoning/classify
@router.post("/classify", response_model=QueryClassificationResponse)
async def classify_query(
    query_text: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    classifier = QueryUnderstandingService()
    try:
        res = classifier.classify_query(query_text)
        return QueryClassificationResponse(
            query=res["query"],
            intent=res["intent"],
            strategy=res["strategy"],
            confidence=res["confidence"],
            reasoning_needed=res["reasoning_needed"]
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Classification failed: {str(e)}"
        )


# 4. POST /api/reasoning/compare
@router.post("/compare", response_model=ComparisonResponse)
async def compare_items(
    payload: ComparisonRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    analyzer = ComparativeCaseAnalyzer(db)
    try:
        res = analyzer.compare_elements(
            case_id=payload.case_id,
            target_type=payload.target_type,
            item_ids=payload.item_ids,
        )
        return ComparisonResponse(**res)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Comparison failed: {str(e)}"
        )


# 5. GET /api/reasoning/contradictions
@router.get("/contradictions", response_model=ContradictionReportResponse)
async def get_contradictions(
    case_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    engine = ContradictionDetectionEngine(db)
    try:
        report = engine.detect_contradictions(case_id)
        
        # Save contradiction report to DB if case exists
        db_report = ContradictionReport(
            case_id=case_id,
            summary=report["summary"],
            severity=report["severity"],
            confidence=report["confidence"],
            details_json=json.dumps(report["contradictions"])
        )
        db.add(db_report)
        db.commit()
        db.refresh(db_report)

        return ContradictionReportResponse(
            id=db_report.id,
            case_id=db_report.case_id,
            summary=db_report.summary,
            severity=db_report.severity,
            confidence=db_report.confidence,
            contradictions=[ContradictionItem(**c) for c in report["contradictions"]],
            created_at=db_report.created_at
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Contradiction check failed: {str(e)}"
        )


# 6. POST /api/reasoning/rank-evidence
@router.post("/rank-evidence", response_model=EvidenceRankingResponse)
async def rank_evidence_endpoint(
    case_id: uuid.UUID = Query(...),
    query_text: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    from app.services.reasoning.multi_hop import MultiHopRetrievalOrchestrator
    orchestrator = MultiHopRetrievalOrchestrator(db)
    ranker = EvidenceRankingEngine(db)
    try:
        retrieved = await orchestrator.execute_multi_hop(
            case_id=case_id,
            user_id=current_user.id,
            query=query_text,
            hops=2
        )

        ranked = ranker.rank_evidence(case_id, query_text, retrieved)
        
        db_ranking = EvidenceRanking(
            case_id=case_id,
            query_text=query_text,
            rankings_json=json.dumps(ranked)
        )
        db.add(db_ranking)
        db.commit()

        return EvidenceRankingResponse(
            query=query_text,
            rankings=[EvidenceItem(**r) for r in ranked]
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Evidence ranking failed: {str(e)}"
        )


# 7. GET /api/reasoning/research/sessions
@router.get("/research/sessions", response_model=List[ResearchSessionResponse])
async def list_research_sessions(
    case_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    engine = ResearchWorkflowEngine(db)
    sessions = engine.list_sessions(current_user.id, case_id)
    
    res = []
    for s in sessions:
        bookmarks = json.loads(s.bookmarks_json) if s.bookmarks_json else []
        history = json.loads(s.search_history_json) if s.search_history_json else []
        
        res.append(ResearchSessionResponse(
            id=s.id,
            user_id=s.user_id,
            case_id=s.case_id,
            title=s.title,
            bookmarks=bookmarks,
            search_history=history,
            notes=[ResearchNoteResponse.model_validate(n) for n in s.notes],
            created_at=s.created_at,
            updated_at=s.updated_at
        ))
    return res


# 8. POST /api/reasoning/research/sessions
@router.post("/research/sessions", response_model=ResearchSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_research_session(
    payload: ResearchSessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    engine = ResearchWorkflowEngine(db)
    s = engine.create_session(current_user.id, payload.title, payload.case_id)
    return ResearchSessionResponse(
        id=s.id,
        user_id=s.user_id,
        case_id=s.case_id,
        title=s.title,
        bookmarks=[],
        search_history=[],
        notes=[],
        created_at=s.created_at,
        updated_at=s.updated_at
    )


# 9. POST /api/reasoning/research/sessions/{id}/notes
@router.post("/research/sessions/{session_id}/notes", response_model=ResearchNoteResponse, status_code=status.HTTP_201_CREATED)
async def add_session_note(
    session_id: uuid.UUID,
    payload: ResearchNoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    engine = ResearchWorkflowEngine(db)
    session = engine.get_session(session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research session not found.")
    
    note = engine.add_note(session_id, payload.title, payload.content)
    return ResearchNoteResponse.model_validate(note)


# 10. POST /api/reasoning/research/sessions/{id}/bookmark
@router.post("/research/sessions/{session_id}/bookmark", response_model=ResearchSessionResponse)
async def add_session_bookmark(
    session_id: uuid.UUID,
    bookmark_item: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    engine = ResearchWorkflowEngine(db)
    s = engine.add_bookmark(session_id, current_user.id, bookmark_item)
    if not s:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research session not found.")
    
    return ResearchSessionResponse(
        id=s.id,
        user_id=s.user_id,
        case_id=s.case_id,
        title=s.title,
        bookmarks=json.loads(s.bookmarks_json) if s.bookmarks_json else [],
        search_history=json.loads(s.search_history_json) if s.search_history_json else [],
        notes=[ResearchNoteResponse.model_validate(n) for n in s.notes],
        created_at=s.created_at,
        updated_at=s.updated_at
    )


# 11. POST /api/reasoning/research/sessions/{id}/search-query
@router.post("/research/sessions/{session_id}/search-query", response_model=ResearchSessionResponse)
async def add_session_search_query(
    session_id: uuid.UUID,
    query_text: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    engine = ResearchWorkflowEngine(db)
    s = engine.add_search_query(session_id, current_user.id, query_text)
    if not s:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research session not found.")
    
    return ResearchSessionResponse(
        id=s.id,
        user_id=s.user_id,
        case_id=s.case_id,
        title=s.title,
        bookmarks=json.loads(s.bookmarks_json) if s.bookmarks_json else [],
        search_history=json.loads(s.search_history_json) if s.search_history_json else [],
        notes=[ResearchNoteResponse.model_validate(n) for n in s.notes],
        created_at=s.created_at,
        updated_at=s.updated_at
    )


# 12. GET /api/reasoning/analytics
@router.get("/analytics", response_model=QAAnalyticsResponse)
async def get_qa_analytics(
    case_id: Optional[uuid.UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    try:
        # Pull stats from qa_history table
        query = db.query(QAHistory)
        if case_id:
            query = query.filter(QAHistory.case_id == case_id)
            
        histories = query.all()
        total = len(histories)
        
        if total == 0:
            return QAAnalyticsResponse(
                total_queries=0,
                average_latency_ms=0.0,
                average_confidence=0.0,
                hallucination_rate=0.0,
                intent_distribution={},
                strategy_distribution={},
                validation_failures=0,
                evidence_utilization=0.0,
                confidence_distribution=[]
            )
            
        avg_lat = sum(h.latency_ms or 0 for h in histories) / total
        avg_conf = sum(h.confidence for h in histories) / total
        
        # Calculate distributions
        intent_dist = {}
        strategy_dist = {}
        failures = 0
        hallucinations = 0
        
        for h in histories:
            if h.intent:
                intent_dist[h.intent] = intent_dist.get(h.intent, 0) + 1
            if h.strategy:
                strategy_dist[h.strategy] = strategy_dist.get(h.strategy, 0) + 1
            
            if h.validation_json:
                val = json.loads(h.validation_json)
                if not val.get("success", True):
                    failures += 1
                warnings = val.get("warnings", [])
                if any(w.get("type") == "hallucination" for w in warnings):
                    hallucinations += 1
                    
        hallucination_rate = hallucinations / total
        
        # Build confidence buckets
        buckets = {"0.0-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
        for h in histories:
            c = h.confidence
            if c < 0.4:
                buckets["0.0-0.4"] += 1
            elif c < 0.6:
                buckets["0.4-0.6"] += 1
            elif c < 0.8:
                buckets["0.6-0.8"] += 1
            else:
                buckets["0.8-1.0"] += 1
                
        conf_dist = [{"range": k, "count": v} for k, v in buckets.items()]

        return QAAnalyticsResponse(
            total_queries=total,
            average_latency_ms=avg_lat,
            average_confidence=avg_conf,
            hallucination_rate=hallucination_rate,
            intent_distribution=intent_dist,
            strategy_distribution=strategy_dist,
            validation_failures=failures,
            evidence_utilization=0.85,
            confidence_distribution=conf_dist
        )
    except Exception as e:
        logger.error("get_qa_analytics error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analytics generation failed: {str(e)}"
        )
