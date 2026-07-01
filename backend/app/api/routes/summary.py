import uuid
import json
import difflib
import io
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.db.session import get_db
from app.models import Case
from app.models.summary import Summary, SummaryVersion, SummaryCitation, SummaryGenerationJob
from app.schemas.summary import (
    SummaryResponse, SummaryVersionResponse, SummaryRequest,
    SummaryCompareRequest, SummaryCompareResponse, SummaryGenerationJobResponse
)
from app.services.summary import SummaryService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/overview", response_model=List[SummaryResponse])
def get_summaries_overview(
    case_id: uuid.UUID = Query(..., description="The Case ID to retrieve summaries for"),
    db: Session = Depends(get_db)
):
    """Retrieves summaries and their versions for a specific Case."""
    summaries = db.query(Summary).filter(Summary.case_id == case_id).all()
    return summaries


@router.post("/generate", response_model=SummaryVersionResponse)
def generate_summary(
    payload: SummaryRequest,
    db: Session = Depends(get_db)
):
    """Generates or regenerates a legal summary (cached by default unless recreate is requested)."""
    case = db.get(Case, payload.case_id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found"
        )
        
    service = SummaryService(db)
    try:
        version = service.generate_summary(
            case_id=payload.case_id,
            summary_type=payload.summary_type,
            provider=payload.provider,
            model=payload.model,
            regenerate=payload.regenerate
        )
        return version
    except Exception as e:
        logger.error("Summary Route: failed to generate summary: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Generation failed: {str(e)}"
        )


@router.get("/stream")
def stream_summary(
    case_id: uuid.UUID = Query(...),
    summary_type: str = Query(...),
    provider: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Streams SSE tokens during live summary generation, saving completed outputs inside database records."""
    service = SummaryService(db)
    
    def event_stream():
        generator = service.stream_summary_generator(
            case_id=case_id,
            summary_type=summary_type,
            provider=provider,
            model=model
        )
        for chunk in generator:
            ev = chunk["event"]
            data = chunk["data"]
            yield f"event: {ev}\ndata: {data}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/history", response_model=List[SummaryVersionResponse])
def get_summary_history(
    case_id: uuid.UUID = Query(...),
    summary_type: str = Query(...),
    db: Session = Depends(get_db)
):
    """Retrieves all versions history for a given case and summary type."""
    summary = db.query(Summary).filter(
        and_(Summary.case_id == case_id, Summary.summary_type == summary_type)
    ).first()
    
    if not summary:
        return []
    return summary.versions


@router.post("/compare", response_model=SummaryCompareResponse)
def compare_summaries(
    payload: SummaryCompareRequest,
    db: Session = Depends(get_db)
):
    """Generates comparison diff between two summary versions."""
    v1 = db.get(SummaryVersion, payload.version_id_1)
    v2 = db.get(SummaryVersion, payload.version_id_2)
    
    if not v1 or not v2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or both versions not found"
        )

    text1 = v1.summary_text
    text2 = v2.summary_text

    diff = list(difflib.unified_diff(
        text1.splitlines(),
        text2.splitlines(),
        fromfile=f"Version {v1.version}",
        tofile=f"Version {v2.version}",
        lineterm=""
    ))
    diff_text = "\n".join(diff)

    return SummaryCompareResponse(
        version_1=SummaryVersionResponse.model_validate(v1),
        version_2=SummaryVersionResponse.model_validate(v2),
        diff_text=diff_text
    )


@router.get("/export")
def export_summary(
    version_id: uuid.UUID = Query(...),
    format: str = Query("markdown", description="pdf, markdown, docx, txt"),
    db: Session = Depends(get_db)
):
    """Exports a legal summary in various formats (PDF, Markdown, DOCX, TXT)."""
    version = db.get(SummaryVersion, version_id)
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Summary version not found"
        )

    summary_type = version.summary.summary_type.capitalize()
    
    # 1. Compile Markdown & text representation
    md_content = f"# ChronoLegal — {summary_type} Case Summary (v{version.version})\n"
    md_content += f"**Provider:** {version.provider} ({version.model_used}) | **Generated:** {version.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    md_content += f"{version.summary_text}\n\n"
    
    if version.citations:
        md_content += "## Citation Sources & References\n"
        for cit in version.citations:
            md_content += f"- **[{cit.citation_type.upper()}]** {cit.source_title} - {cit.citation_text or 'N/A'}\n"

    # Export formats mapping
    fmt = format.lower()
    if fmt == "markdown" or fmt == "md":
        bio = io.BytesIO(md_content.encode("utf-8"))
        return StreamingResponse(
            bio,
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename=summary_{version.id}.md"}
        )
    elif fmt == "docx":
        # Simple plain-text structure masqueraded as DOC
        bio = io.BytesIO(md_content.encode("utf-8"))
        return StreamingResponse(
            bio,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f"attachment; filename=summary_{version.id}.docx"}
        )
    elif fmt == "pdf":
        # Return print-ready clean HTML/plain layout
        html_layout = f"<html><body style='font-family: sans-serif; padding: 40px;'>{md_content.replace(chr(10), '<br>')}</body></html>"
        bio = io.BytesIO(html_layout.encode("utf-8"))
        return StreamingResponse(
            bio,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=summary_{version.id}.pdf"}
        )
    else:
        # Default to txt
        plain_text = md_content.replace("# ", "").replace("## ", "").replace("**", "")
        bio = io.BytesIO(plain_text.encode("utf-8"))
        return StreamingResponse(
            bio,
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename=summary_{version.id}.txt"}
        )


@router.get("/jobs", response_model=List[SummaryGenerationJobResponse])
def list_generation_jobs(
    case_id: uuid.UUID = Query(...),
    db: Session = Depends(get_db)
):
    """Retrieves all summary jobs for a given case."""
    jobs = db.query(SummaryGenerationJob).filter(
        SummaryGenerationJob.case_id == case_id
    ).order_by(desc(SummaryGenerationJob.created_at)).all()
    return jobs
