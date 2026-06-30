import hashlib
import math
import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Case, Document, DocumentStatus, DocumentType, ProcessingStatus, UploadStatus, User, DocumentCategory
from app.schemas import (
    DocumentResponse,
    DocumentUploadResponse,
    DocumentUpdateRequest,
    PaginatedResponse,
    BulkDeleteRequest,
    BulkDeleteResponse,
    BulkDownloadRequest,
    BulkMoveRequest,
    BulkMoveResponse,
)
from app.services.storage import StorageBackend, get_storage_backend
from app.utils.metadata import detect_category, extract_pdf_page_count

router = APIRouter(prefix="/documents", tags=["Documents"])

ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "png", "jpg", "jpeg"}
ALLOWED_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
    "image/png",
    "image/jpeg",
}

_SORT_FIELDS = {
    "newest": (Document.created_at, "desc"),
    "oldest": (Document.created_at, "asc"),
    "filename": (Document.filename, "asc"),
    "file_size": (Document.file_size, "asc"),
    "category": (Document.document_category, "asc"),
}

@router.get("", response_model=PaginatedResponse[DocumentResponse], summary="List documents")
async def list_documents(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    document_type: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    tags: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    case_id: Optional[UUID] = Query(None),
    sort: str = Query("newest", description="newest|oldest|filename|file_size|category"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    original: Optional[bool] = Query(None),
    favorite: Optional[bool] = Query(None),
    favorites_first: bool = Query(False),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[DocumentResponse]:
    q = db.query(Document).filter(Document.owner_id == current_user.id)
    
    if case_id:
        q = q.filter(Document.case_id == case_id)
    if status:
        q = q.filter(Document.status == status)
    if document_type:
        q = q.filter(Document.document_type == document_type)
    if category:
        q = q.filter(Document.document_category == category)
    if tags:
        # Search for tags (comma separated)
        q = q.filter(Document.user_tags.ilike(f"%{tags}%"))
    if start_date:
        q = q.filter(Document.created_at >= start_date)
    if end_date:
        q = q.filter(Document.created_at <= end_date)
    if favorite is not None:
        q = q.filter(Document.is_favorite == favorite)
        
    if search:
        term = f"%{search}%"
        q = q.filter(
            or_(
                Document.title.ilike(term),
                Document.filename.ilike(term),
                Document.description.ilike(term),
                Document.user_tags.ilike(term)
            )
        )
        
    # Sorting
    sort_col, sort_dir = _SORT_FIELDS.get(sort, _SORT_FIELDS["newest"])
    if favorites_first:
        q = q.order_by(Document.is_favorite.desc(), sort_col.desc() if sort_dir == "desc" else sort_col.asc())
    else:
        q = q.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())
        
    total = q.count()
    total_pages = max(1, math.ceil(total / page_size))
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    
    return PaginatedResponse[DocumentResponse](
        items=[DocumentResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("/upload", response_model=DocumentUploadResponse, summary="Upload a legal document")
async def upload_document(
    file: UploadFile = File(...),
    case_id: UUID = Form(...),
    title: Optional[str] = Form(None),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage_backend),
) -> DocumentUploadResponse:
    settings = get_settings()

    # 1. Verify case exists and is owned by current user
    assoc_case = db.query(Case).filter(Case.id == case_id, Case.owner_id == current_user.id).first()
    if not assoc_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found or access denied."
        )

    # 2. Check filename extension
    orig_filename = file.filename or "unnamed_file"
    ext = ""
    if "." in orig_filename:
        ext = orig_filename.rsplit(".", 1)[-1].lower()
    
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Allowed formats: PDF, DOCX, TXT, PNG, JPEG/JPG."
        )

    # 3. Validate MIME type
    if file.content_type not in ALLOWED_MIMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid MIME type: {file.content_type}"
        )

    storage_path_str = None
    try:
        # 4. Read file content to validate size and calculate SHA-256
        sha256_hash = hashlib.sha256()
        file_bytes = b""
        total_size = 0
        
        # Read in chunks
        while chunk := await file.read(1024 * 1024):  # 1MB chunks
            total_size += len(chunk)
            if total_size > settings.max_upload_size:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File exceeds maximum upload size of {settings.max_upload_size} bytes."
                )
            sha256_hash.update(chunk)
            file_bytes += chunk

        checksum_str = sha256_hash.hexdigest()

        # Check for duplicates belonging ONLY to the current user
        duplicate_doc = (
            db.query(Document)
            .filter(
                Document.owner_id == current_user.id,
                Document.checksum == checksum_str
            )
            .first()
        )
        if duplicate_doc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "Duplicate document detected.",
                    "duplicate_detected": True,
                    "document_id": str(duplicate_doc.id),
                    "filename": duplicate_doc.filename,
                    "case_id": str(duplicate_doc.case_id) if duplicate_doc.case_id else None,
                    "case_title": duplicate_doc.case.title if duplicate_doc.case else None,
                    "created_at": duplicate_doc.created_at.isoformat() if duplicate_doc.created_at else None,
                }
            )

        # Determine DocumentType enum
        if ext == "pdf":
            doc_type = DocumentType.PDF
        elif ext == "docx":
            doc_type = DocumentType.DOCX
        elif ext == "txt":
            doc_type = DocumentType.TXT
        else:
            doc_type = DocumentType.OTHER

        # Detect DocumentCategory enum
        category_detected = detect_category(orig_filename, file.content_type)

        # Extract lightweight metadata (page count for PDF)
        extracted_page_count = None
        if category_detected == DocumentCategory.PDF:
            extracted_page_count = extract_pdf_page_count(file_bytes)

        # Generate collision-safe stored filename
        stored_name = f"{uuid.uuid4()}.{ext}"

        # 5. Save using storage backend
        storage_path_str = storage.save(file_bytes, stored_name)

        # 6. Save DB record
        doc_title = title or orig_filename
        new_doc = Document(
            title=doc_title,
            filename=orig_filename,
            file_path=storage_path_str,  # Legacy field mapping
            file_size=total_size,
            mime_type=file.content_type,
            document_type=doc_type,
            status=DocumentStatus.UPLOADED,
            page_count=extracted_page_count,
            owner_id=current_user.id,
            case_id=case_id,
            original_filename=orig_filename,
            stored_filename=stored_name,
            storage_path=storage_path_str,
            file_extension=ext,
            checksum=checksum_str,
            upload_status=UploadStatus.COMPLETED,
            processing_status=ProcessingStatus.PENDING,
            document_category=category_detected,
            user_tags=None,
            description=None,
            last_accessed_at=None,
        )
        
        db.add(new_doc)
        db.commit()
        db.refresh(new_doc)
        
    except Exception as e:
        # Cleanup file if saved but database operation failed or was cancelled
        if storage_path_str:
            try:
                storage.delete(storage_path_str)
            except Exception:
                pass
        
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Upload aborted or failed: {str(e)}"
        )

    return DocumentUploadResponse(
        id=new_doc.id,
        title=new_doc.title,
        filename=new_doc.filename,
        status="uploaded",
        message="Document uploaded successfully."
    )



# ── Recent Documents Endpoint ───────────────────────────────────────────────

@router.get("/recent", response_model=List[DocumentResponse], summary="Get recently accessed documents")
async def get_recent_documents(
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> List[DocumentResponse]:
    docs = (
        db.query(Document)
        .filter(Document.owner_id == current_user.id)
        .order_by(
            Document.last_accessed_at.desc().nullslast(),
            Document.created_at.desc()
        )
        .limit(limit)
        .all()
    )
    return [DocumentResponse.model_validate(doc) for doc in docs]


# ── Favorite Toggle Endpoint ────────────────────────────────────────────────

@router.patch("/{document_id}/favorite", response_model=DocumentResponse, summary="Toggle favorite status")
async def toggle_favorite(
    document_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    doc = db.query(Document).filter(Document.id == document_id, Document.owner_id == current_user.id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found."
        )
    doc.is_favorite = not doc.is_favorite
    doc.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(doc)
    return DocumentResponse.model_validate(doc)


# ── Bulk Delete Endpoint ────────────────────────────────────────────────────

@router.delete("/bulk", response_model=BulkDeleteResponse, summary="Bulk delete documents")
async def bulk_delete_documents(
    payload: BulkDeleteRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage_backend),
) -> BulkDeleteResponse:
    try:
        # Fetch requested documents
        docs = db.query(Document).filter(Document.id.in_(payload.document_ids)).all()
        doc_map = {doc.id: doc for doc in docs}
        
        # Verify ownership and existence of every document
        for doc_id in payload.document_ids:
            if doc_id not in doc_map:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Document {doc_id} not found."
                )
            if doc_map[doc_id].owner_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Unauthorized to delete document {doc_id}."
                )
        
        # Delete physical files & database records
        paths_to_delete = []
        thumbs_to_delete = []
        for doc_id in payload.document_ids:
            doc = doc_map[doc_id]
            if doc.storage_path and os.path.exists(doc.storage_path):
                paths_to_delete.append(doc.storage_path)
            
            thumb_path = os.path.join(get_settings().upload_directory, "thumbnails", f"{doc.id}.png")
            if os.path.exists(thumb_path):
                thumbs_to_delete.append(thumb_path)
                
            db.delete(doc)
            
        # Perform physical deletions
        # If any physical deletion fails, raise exception to trigger database transaction rollback!
        for path in paths_to_delete:
            try:
                os.remove(path)
            except Exception as e:
                raise Exception(f"Failed to delete physical file: {str(e)}")
                
        for path in thumbs_to_delete:
            try:
                os.remove(path)
            except Exception:
                pass
                
        db.commit()
        return BulkDeleteResponse(
            deleted_count=len(payload.document_ids),
            skipped_count=0,
            failures=[]
        )
    except HTTPException as he:
        db.rollback()
        raise he
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bulk delete aborted: {str(e)}"
        )


# ── Bulk Download Endpoint ──────────────────────────────────────────────────

@router.post("/bulk-download", summary="Bulk download documents as ZIP")
async def bulk_download_documents(
    payload: BulkDownloadRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    import zipfile
    docs = db.query(Document).filter(Document.id.in_(payload.document_ids)).all()
    doc_map = {doc.id: doc for doc in docs}
    
    # Verify ownership and physical existence
    valid_docs = []
    for doc_id in payload.document_ids:
        if doc_id not in doc_map:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document {doc_id} not found.")
        doc = doc_map[doc_id]
        if doc.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Unauthorized to download document {doc_id}.")
        if not doc.storage_path or not os.path.exists(doc.storage_path):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Physical file for {doc.filename} not found.")
        valid_docs.append(doc)
        
    # Generate on-demand ZIP archive
    settings = get_settings()
    os.makedirs(os.path.join(settings.upload_directory, "temp"), exist_ok=True)
    temp_zip_path = os.path.join(settings.upload_directory, "temp", f"bulk_{uuid.uuid4()}.zip")
    
    try:
        seen_filenames = {}
        with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for doc in valid_docs:
                orig_name = doc.filename
                # Handle duplicate filenames inside ZIP
                if orig_name in seen_filenames:
                    seen_filenames[orig_name] += 1
                    name, ext = os.path.splitext(orig_name)
                    zip_filename = f"{name} ({seen_filenames[orig_name]}){ext}"
                else:
                    seen_filenames[orig_name] = 0
                    zip_filename = orig_name
                zipf.write(doc.storage_path, zip_filename)
    except Exception as e:
        if os.path.exists(temp_zip_path):
            os.remove(temp_zip_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate ZIP archive: {str(e)}"
        )
        
    # Schedule removal of temporary ZIP file in background tasks
    def remove_file(path: str):
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
                
    background_tasks.add_task(remove_file, temp_zip_path)
    
    return FileResponse(
        temp_zip_path,
        media_type="application/zip",
        filename="documents_bulk.zip"
    )


# ── Bulk Move Endpoint ──────────────────────────────────────────────────────

@router.patch("/bulk-move", response_model=BulkMoveResponse, summary="Bulk move documents to another case")
async def bulk_move_documents(
    payload: BulkMoveRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> BulkMoveResponse:
    # Verify destination case ownership
    dest_case = db.query(Case).filter(Case.id == payload.destination_case_id, Case.owner_id == current_user.id).first()
    if not dest_case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Destination case not found."
        )
        
    # Fetch requested documents
    docs = db.query(Document).filter(Document.id.in_(payload.document_ids)).all()
    doc_map = {doc.id: doc for doc in docs}
    
    # Verify ownership of every document
    for doc_id in payload.document_ids:
        if doc_id not in doc_map:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document {doc_id} not found."
            )
        if doc_map[doc_id].owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Unauthorized to move document {doc_id}."
            )
            
    # Perform move update
    moved_count = 0
    for doc in docs:
        doc.case_id = payload.destination_case_id
        doc.updated_at = datetime.now(timezone.utc)
        moved_count += 1
        
    db.commit()
    return BulkMoveResponse(
        moved_count=moved_count,
        skipped_count=0,
        failures=[]
    )


@router.get("/{document_id}", response_model=DocumentResponse, summary="Get document by ID")
async def get_document(
    document_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    doc = db.query(Document).filter(Document.id == document_id, Document.owner_id == current_user.id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found."
        )
        
    # Update last accessed timestamp
    doc.last_accessed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(doc)
    
    return DocumentResponse.model_validate(doc)


@router.patch("/{document_id}", response_model=DocumentResponse, summary="Update document metadata")
async def update_document_metadata(
    document_id: UUID,
    payload: DocumentUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    doc = db.query(Document).filter(Document.id == document_id, Document.owner_id == current_user.id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found."
        )

    updates = payload.model_dump(exclude_unset=True)
    
    if "description" in updates:
        doc.description = updates["description"]
        
    if "tags" in updates:
        tags_list = updates["tags"]
        if tags_list is not None:
            # Map List[str] to comma-separated string
            doc.user_tags = ", ".join(tags_list) if tags_list else None

    doc.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(doc)
    
    return DocumentResponse.model_validate(doc)


@router.get("/{document_id}/download", summary="Download a document")
async def download_document(
    document_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    doc = db.query(Document).filter(Document.id == document_id, Document.owner_id == current_user.id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found."
        )

    if not doc.storage_path or not os.path.exists(doc.storage_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Physical file not found on disk."
        )

    # Update last accessed timestamp
    doc.last_accessed_at = datetime.now(timezone.utc)
    db.commit()

    return FileResponse(
        path=doc.storage_path,
        media_type=doc.mime_type or "application/octet-stream",
        filename=doc.filename,
    )


@router.delete("/{document_id}", summary="Delete a document")
async def delete_document(
    document_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage_backend),
) -> dict:
    doc = db.query(Document).filter(Document.id == document_id, Document.owner_id == current_user.id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found."
        )

    # 1. Delete physical file
    if doc.storage_path:
        try:
            storage.delete(doc.storage_path)
        except Exception:
            pass

    # 2. Delete database record
    db.delete(doc)
    db.commit()

    return {"message": "Document deleted successfully.", "id": str(document_id)}


# ── Preview & Thumbnail Endpoints ──────────────────────────────────────────

from fastapi import Header
from app.core.security import decode_token
from pathlib import Path
import io
from PIL import Image, ImageDraw
from pypdf import PdfReader

def get_current_user_for_preview(
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    actual_token = None
    if authorization and authorization.startswith("Bearer "):
        actual_token = authorization.split(" ", 1)[1]
    elif token:
        actual_token = token
        
    if not actual_token:
        raise credentials_exception
        
    payload = decode_token(actual_token)
    if payload is None:
        raise credentials_exception
        
    if payload.get("type") != "access":
        raise credentials_exception
        
    user_id: Optional[str] = payload.get("sub")
    if user_id is None:
        raise credentials_exception
        
    try:
        uid = UUID(user_id)
    except ValueError:
        raise credentials_exception
        
    user: Optional[User] = db.get(User, uid)
    if user is None:
        raise credentials_exception
        
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )
        
    return user


def generate_placeholder_thumbnail(doc_type: str, output_path: Path):
    width, height = 150, 200
    image = Image.new("RGB", (width, height), "#F8FAFC")
    draw = ImageDraw.Draw(image)
    
    # Border
    draw.rectangle([0, 0, width - 1, height - 1], outline="#CBD5E1", width=1)
    
    doc_type = doc_type.upper()
    if doc_type == "PDF":
        badge_color = "#EF4444"
        text_color = "#FFFFFF"
    elif doc_type in ("DOCX", "DOC", "WORD"):
        badge_color = "#3B82F6"
        text_color = "#FFFFFF"
    elif doc_type in ("TXT", "TEXT"):
        badge_color = "#F59E0B"
        text_color = "#FFFFFF"
    elif doc_type in ("PNG", "JPG", "JPEG", "IMAGE"):
        badge_color = "#10B981"
        text_color = "#FFFFFF"
    else:
        badge_color = "#6B7280"
        text_color = "#FFFFFF"
        
    try:
        draw.rounded_rectangle([25, 80, 125, 120], radius=4, fill=badge_color)
        draw.text((75, 100), doc_type, fill=text_color, anchor="mm")
    except Exception:
        draw.rectangle([25, 80, 125, 120], fill=badge_color)
        draw.text((45, 95), doc_type, fill=text_color)
        
    # Text lines simulation
    draw.line([30, 40, 120, 40], fill="#E2E8F0", width=2)
    draw.line([30, 50, 100, 50], fill="#E2E8F0", width=2)
    draw.line([30, 60, 110, 60], fill="#E2E8F0", width=2)
    
    draw.line([30, 140, 120, 140], fill="#E2E8F0", width=2)
    draw.line([30, 150, 90, 150], fill="#E2E8F0", width=2)
    draw.line([30, 160, 110, 160], fill="#E2E8F0", width=2)
    
    image.save(output_path, "PNG")


def create_thumbnail_file(doc: Document, thumbnail_path: Path):
    if doc.document_category == DocumentCategory.IMAGE:
        try:
            with Image.open(doc.storage_path) as img:
                img.thumbnail((150, 200))
                img.save(thumbnail_path, "PNG")
                return True
        except Exception:
            pass
            
    elif doc.document_category == DocumentCategory.PDF:
        try:
            reader = PdfReader(doc.storage_path)
            if len(reader.pages) > 0:
                page = reader.pages[0]
                if page.images:
                    img_data = page.images[0].data
                    with Image.open(io.BytesIO(img_data)) as img:
                        img.thumbnail((150, 200))
                        img.save(thumbnail_path, "PNG")
                        return True
        except Exception:
            pass
            
    # Fallback for DOCX, TXT, etc. or if above generation failed
    try:
        generate_placeholder_thumbnail(doc.file_extension or "TXT", thumbnail_path)
        return True
    except Exception:
        return False


@router.get("/{document_id}/preview", summary="Stream file preview inline")
async def preview_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user_for_preview),
    db: Session = Depends(get_db),
) -> FileResponse:
    doc = db.query(Document).filter(Document.id == document_id, Document.owner_id == current_user.id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found."
        )

    if not doc.storage_path or not os.path.exists(doc.storage_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Physical file not found on disk."
        )

    return FileResponse(
        path=doc.storage_path,
        media_type=doc.mime_type or "application/octet-stream",
        filename=doc.filename,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, max-age=3600",
        }
    )


@router.get("/{document_id}/thumbnail", summary="Get document thumbnail")
async def get_document_thumbnail(
    document_id: UUID,
    current_user: User = Depends(get_current_user_for_preview),
    db: Session = Depends(get_db),
) -> FileResponse:
    doc = db.query(Document).filter(Document.id == document_id, Document.owner_id == current_user.id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found."
        )

    if not doc.storage_path or not os.path.exists(doc.storage_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Physical file not found on disk."
        )

    settings = get_settings()
    upload_dir = Path(settings.upload_directory).resolve()
    thumbnails_dir = upload_dir / "thumbnails"
    thumbnails_dir.mkdir(parents=True, exist_ok=True)
    
    thumbnail_path = (thumbnails_dir / f"{doc.id}.png").resolve()

    if not thumbnail_path.exists():
        success = create_thumbnail_file(doc, thumbnail_path)
        if not success or not thumbnail_path.exists():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate thumbnail."
            )

    return FileResponse(
        path=thumbnail_path,
        media_type="image/png",
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, max-age=86400",
        }
    )
