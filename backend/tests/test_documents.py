import io
import uuid
import pytest
from fastapi.testclient import TestClient

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app
from app.core.config import get_settings

client = TestClient(app)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_and_login(suffix: str = "") -> dict:
    uid = uuid.uuid4().hex[:8]
    email = f"doctest{uid}{suffix}@example.com"
    reg = client.post("/api/auth/register", json={
        "email": email,
        "username": f"doctest{uid}",
        "password": "password123",
        "full_name": "Doc Tester",
    })
    assert reg.status_code == 201, reg.text
    login = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_case(headers: dict, title: str = "Test Case") -> dict:
    payload = {"title": title, "priority": "medium", "status": "open"}
    r = client.post("/api/cases", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_upload_document_success():
    headers = _register_and_login("success")
    case = _create_case(headers, "Success Case")
    
    file_content = b"This is a dummy PDF file content."
    file_obj = io.BytesIO(file_content)
    
    response = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"], "title": "Dummy Document"},
        files={"file": ("dummy.pdf", file_obj, "application/pdf")}
    )
    
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "uploaded"
    assert data["filename"] == "dummy.pdf"
    
    # 2. Get document metadata
    doc_id = data["id"]
    get_resp = client.get(f"/api/documents/{doc_id}", headers=headers)
    assert get_resp.status_code == 200
    doc_data = get_resp.json()
    assert doc_data["title"] == "Dummy Document"
    assert doc_data["file_size"] == len(file_content)
    assert doc_data["file_extension"] == "pdf"
    assert doc_data["checksum"] is not None
    
    # 3. Download document
    dl_resp = client.get(f"/api/documents/{doc_id}/download", headers=headers)
    assert dl_resp.status_code == 200
    assert dl_resp.content == file_content
    assert dl_resp.headers["content-type"] == "application/pdf"
    
    # 4. Delete document
    del_resp = client.delete(f"/api/documents/{doc_id}", headers=headers)
    assert del_resp.status_code == 200
    
    # 5. Check metadata is gone
    get_gone = client.get(f"/api/documents/{doc_id}", headers=headers)
    assert get_gone.status_code == 404


def test_upload_document_invalid_extension():
    headers = _register_and_login("ext")
    case = _create_case(headers, "Ext Case")
    
    response = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("malicious.exe", io.BytesIO(b"binary"), "application/octet-stream")}
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_upload_document_invalid_mime():
    headers = _register_and_login("mime")
    case = _create_case(headers, "Mime Case")
    
    # Send PDF file name but invalid mime type
    response = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("test.pdf", io.BytesIO(b"pdf data"), "application/octet-stream")}
    )
    assert response.status_code == 400
    assert "Invalid MIME type" in response.json()["detail"]


def test_upload_document_oversized():
    headers = _register_and_login("oversized")
    case = _create_case(headers, "Oversized Case")
    
    settings = get_settings()
    original_max = settings.max_upload_size
    # Set limit to 10 bytes temporarily
    settings.max_upload_size = 10
    
    try:
        response = client.post(
            "/api/documents/upload",
            headers=headers,
            data={"case_id": case["id"]},
            files={"file": ("test.txt", io.BytesIO(b"this file is way too long for 10 bytes"), "text/plain")}
        )
        assert response.status_code == 413
        assert "exceeds maximum upload size" in response.json()["detail"]
    finally:
        # Restore settings
        settings.max_upload_size = original_max


def test_upload_document_unowned_case():
    headers_owner = _register_and_login("owner")
    headers_attacker = _register_and_login("attacker")
    
    case_owner = _create_case(headers_owner, "Owner Case")
    
    # Attacker tries to upload to Owner Case
    response = client.post(
        "/api/documents/upload",
        headers=headers_attacker,
        data={"case_id": case_owner["id"]},
        files={"file": ("test.txt", io.BytesIO(b"content"), "text/plain")}
    )
    assert response.status_code == 404
    assert "Case not found" in response.json()["detail"]


def test_document_list_pagination():
    headers = _register_and_login("pagination")
    case = _create_case(headers, "Paged Case")
    
    # Upload 3 documents with unique content to avoid duplicate detection
    for i in range(3):
        client.post(
            "/api/documents/upload",
            headers=headers,
            data={"case_id": case["id"], "title": f"Doc {i}"},
            files={"file": (f"doc_{i}.txt", io.BytesIO(f"test content {i}".encode("utf-8")), "text/plain")}
        )
        
    # Query with page size 2
    response = client.get(f"/api/documents?case_id={case['id']}&page=1&page_size=2", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total"] == 3
    assert data["total_pages"] == 2


def test_upload_partial_cleanup_on_db_error(monkeypatch):
    headers = _register_and_login("db_fail")
    case = _create_case(headers, "DB Fail Case")
    
    from sqlalchemy.orm import Session
    
    def mock_commit(self):
        raise Exception("Database transaction error simulation")
        
    monkeypatch.setattr(Session, "commit", mock_commit)
    
    file_content = b"Content that should be cleaned up on DB failure."
    response = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("cleanup.txt", io.BytesIO(file_content), "text/plain")}
    )
    
    assert response.status_code == 400
    assert "Upload aborted or failed" in response.json()["detail"]
    
    # Check that there are no files on disk matching the content
    settings = get_settings()
    upload_dir = settings.upload_directory
    files_on_disk = os.listdir(upload_dir) if os.path.exists(upload_dir) else []
    
    found_orphaned_file = False
    for filename in files_on_disk:
        path = os.path.join(upload_dir, filename)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                if f.read() == file_content:
                    found_orphaned_file = True
                    break
    assert not found_orphaned_file, "Orphaned file was found on disk after a failed DB commit!"


def test_document_metadata_update_success():
    headers = _register_and_login("meta_up")
    case = _create_case(headers, "Meta Case")
    
    # 1. Upload doc
    response = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("doc.txt", io.BytesIO(b"hello text"), "text/plain")}
    )
    assert response.status_code == 200
    doc_id = response.json()["id"]
    
    # 2. Patch metadata
    patch_resp = client.patch(
        f"/api/documents/{doc_id}",
        headers=headers,
        json={"tags": ["important", "case-study"], "description": "This is a brief text doc description."}
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["description"] == "This is a brief text doc description."
    assert "important" in data["user_tags"]
    assert "case-study" in data["user_tags"]
    
    # 3. Validation limits: description too long
    long_desc = "x" * 1001
    bad_resp = client.patch(
        f"/api/documents/{doc_id}",
        headers=headers,
        json={"description": long_desc}
    )
    assert bad_resp.status_code == 422
    
    # 4. Validation limits: tag too long
    bad_tag_resp = client.patch(
        f"/api/documents/{doc_id}",
        headers=headers,
        json={"tags": ["a" * 51]}
    )
    assert bad_tag_resp.status_code == 422


def test_document_metadata_filtering_and_sorting():
    headers = _register_and_login("filter_sort")
    case = _create_case(headers, "Query Case")
    
    # Upload PDF
    client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("report.pdf", io.BytesIO(b"%PDF-1.4 dummy contents"), "application/pdf")}
    )
    
    # Upload Image
    client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("screenshot.png", io.BytesIO(b"\x89PNG\r\n\x1a\n dummy bytes"), "image/png")}
    )
    
    # 1. Filter by category PDF
    pdf_list = client.get(f"/api/documents?category=pdf&case_id={case['id']}", headers=headers)
    assert pdf_list.status_code == 200
    items = pdf_list.json()["items"]
    assert len(items) == 1
    assert items[0]["filename"] == "report.pdf"
    assert items[0]["document_category"] == "pdf"
    
    # 2. Filter by category IMAGE
    img_list = client.get(f"/api/documents?category=image&case_id={case['id']}", headers=headers)
    assert img_list.status_code == 200
    assert len(img_list.json()["items"]) == 1
    
    # 3. Sort by filename
    sorted_list = client.get(f"/api/documents?sort=filename&case_id={case['id']}", headers=headers)
    names = [doc["filename"] for doc in sorted_list.json()["items"]]
    # report.pdf (R) should come before screenshot.png (S) in ASC sorting
    assert names == ["report.pdf", "screenshot.png"]


# ── Preview & Thumbnail Tests ──────────────────────────────────────────────

def test_preview_document_success():
    headers = _register_and_login("preview_ok")
    case = _create_case(headers, "Preview Case")
    
    response = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")}
    )
    assert response.status_code == 200
    doc_id = response.json()["id"]
    
    preview_resp = client.get(f"/api/documents/{doc_id}/preview", headers=headers)
    assert preview_resp.status_code == 200
    assert preview_resp.content == b"hello world"
    assert "text/plain" in preview_resp.headers["content-type"]
    assert "inline" in preview_resp.headers["content-disposition"]
    
    token = headers["Authorization"].split(" ")[1]
    preview_resp_qp = client.get(f"/api/documents/{doc_id}/preview?token={token}")
    assert preview_resp_qp.status_code == 200
    assert preview_resp_qp.content == b"hello world"
    
def test_preview_document_unauthorized():
    headers = _register_and_login("preview_unauth")
    case = _create_case(headers, "Preview Case Unauth")
    
    response = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")}
    )
    assert response.status_code == 200
    doc_id = response.json()["id"]
    
    preview_resp = client.get(f"/api/documents/{doc_id}/preview")
    assert preview_resp.status_code == 401
    
    preview_resp_invalid = client.get(f"/api/documents/{doc_id}/preview?token=invalid_token")
    assert preview_resp_invalid.status_code == 401

def test_preview_document_not_found():
    headers = _register_and_login("preview_nf")
    random_id = uuid.uuid4()
    
    preview_resp = client.get(f"/api/documents/{random_id}/preview", headers=headers)
    assert preview_resp.status_code == 404
    
    headers_other = _register_and_login("preview_nf_other")
    case = _create_case(headers_other, "Other Case")
    response = client.post(
        "/api/documents/upload",
        headers=headers_other,
        data={"case_id": case["id"]},
        files={"file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")}
    )
    assert response.status_code == 200
    doc_id = response.json()["id"]
    
    preview_resp_attacker = client.get(f"/api/documents/{doc_id}/preview", headers=headers)
    assert preview_resp_attacker.status_code == 404

def test_thumbnail_generation_and_caching():
    headers = _register_and_login("thumbnail_ok")
    case = _create_case(headers, "Thumbnail Case")
    
    response = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("doc.txt", io.BytesIO(b"hello world"), "text/plain")}
    )
    assert response.status_code == 200
    doc_id = response.json()["id"]
    
    thumb_resp = client.get(f"/api/documents/{doc_id}/thumbnail", headers=headers)
    assert thumb_resp.status_code == 200
    assert thumb_resp.headers["content-type"] == "image/png"
    
    settings = get_settings()
    thumb_path = os.path.join(settings.upload_directory, "thumbnails", f"{doc_id}.png")
    assert os.path.exists(thumb_path)
    
    thumb_resp_cached = client.get(f"/api/documents/{doc_id}/thumbnail", headers=headers)
    assert thumb_resp_cached.status_code == 200
    
    response_pdf = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 dummy"), "application/pdf")}
    )
    assert response_pdf.status_code == 200
    pdf_id = response_pdf.json()["id"]
    
    thumb_pdf = client.get(f"/api/documents/{pdf_id}/thumbnail", headers=headers)
    assert thumb_pdf.status_code == 200
    assert thumb_pdf.headers["content-type"] == "image/png"
    
    from PIL import Image
    import io as python_io
    img = Image.new("RGB", (10, 10), "red")
    img_bytes = python_io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)
    
    response_img = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("img.png", img_bytes, "image/png")}
    )
    assert response_img.status_code == 200
    img_id = response_img.json()["id"]
    
    thumb_img = client.get(f"/api/documents/{img_id}/thumbnail", headers=headers)
    assert thumb_img.status_code == 200
    assert thumb_img.headers["content-type"] == "image/png"


# ── Duplicate Detection Tests ──────────────────────────────────────────────

def test_upload_duplicate_same_case():
    headers = _register_and_login("dup_same")
    case = _create_case(headers, "Duplicate Case")
    
    file_data = b"Some unique file contents for duplicate testing."
    # 1. First upload (succeeds)
    response1 = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"], "title": "First File"},
        files={"file": ("test.txt", io.BytesIO(file_data), "text/plain")}
    )
    assert response1.status_code == 200
    doc_id1 = response1.json()["id"]
    
    # 2. Second upload (fails with 409)
    response2 = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"], "title": "Duplicate File"},
        files={"file": ("test.txt", io.BytesIO(file_data), "text/plain")}
    )
    assert response2.status_code == 409
    data = response2.json()["detail"]
    assert data["duplicate_detected"] is True
    assert data["document_id"] == doc_id1
    assert data["filename"] == "test.txt"
    assert data["case_id"] == case["id"]
    assert data["case_title"] == "Duplicate Case"
    assert data["created_at"] is not None

def test_upload_duplicate_different_case():
    headers = _register_and_login("dup_diff")
    case1 = _create_case(headers, "Case One")
    case2 = _create_case(headers, "Case Two")
    
    file_data = b"Another set of unique file contents."
    # 1. Upload to case 1
    response1 = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case1["id"]},
        files={"file": ("doc.txt", io.BytesIO(file_data), "text/plain")}
    )
    assert response1.status_code == 200
    doc_id1 = response1.json()["id"]
    
    # 2. Upload same to case 2 (fails with 409)
    response2 = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case2["id"]},
        files={"file": ("doc.txt", io.BytesIO(file_data), "text/plain")}
    )
    assert response2.status_code == 409
    data = response2.json()["detail"]
    assert data["duplicate_detected"] is True
    assert data["document_id"] == doc_id1
    assert data["case_id"] == case1["id"]

def test_upload_duplicate_different_user():
    headers_owner = _register_and_login("dup_owner")
    headers_other = _register_and_login("dup_other")
    
    case_owner = _create_case(headers_owner, "Owner Case")
    case_other = _create_case(headers_other, "Other Case")
    
    file_data = b"Shared content uploaded by different users."
    # 1. Owner uploads
    response1 = client.post(
        "/api/documents/upload",
        headers=headers_owner,
        data={"case_id": case_owner["id"]},
        files={"file": ("doc.txt", io.BytesIO(file_data), "text/plain")}
    )
    assert response1.status_code == 200
    
    # 2. Other user uploads same file (succeeds normally, preserving isolation)
    response2 = client.post(
        "/api/documents/upload",
        headers=headers_other,
        data={"case_id": case_other["id"]},
        files={"file": ("doc.txt", io.BytesIO(file_data), "text/plain")}
    )
    assert response2.status_code == 200
    assert response2.json()["id"] != response1.json()["id"]

def test_upload_duplicate_database_rollback():
    headers = _register_and_login("dup_rollback")
    case = _create_case(headers, "Rollback Case")
    
    file_data = b"Rollback duplicate check file contents."
    # 1. Upload once
    response1 = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("rollback.txt", io.BytesIO(file_data), "text/plain")}
    )
    assert response1.status_code == 200
    
    # Check upload directory files on disk before attempt
    settings = get_settings()
    upload_dir = settings.upload_directory
    files_before = os.listdir(upload_dir) if os.path.exists(upload_dir) else []
    
    # 2. Upload duplicate
    response2 = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("rollback.txt", io.BytesIO(file_data), "text/plain")}
    )
    assert response2.status_code == 409
    
    # Verify no new files written on disk
    files_after = os.listdir(upload_dir) if os.path.exists(upload_dir) else []
    assert len(files_before) == len(files_after), "New files were written on disk for duplicate upload attempt!"


# ── Bulk Operations & Polish Tests ──────────────────────────────────────────

def test_toggle_favorite():
    headers = _register_and_login("toggle_fav")
    case = _create_case(headers, "Fav Case")
    
    # Upload document
    response = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("fav.txt", io.BytesIO(b"favorite text"), "text/plain")}
    )
    assert response.status_code == 200
    doc_id = response.json()["id"]
    
    # 1. Toggle to True
    response = client.patch(f"/api/documents/{doc_id}/favorite", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_favorite"] is True
    
    # 2. Toggle back to False
    response = client.patch(f"/api/documents/{doc_id}/favorite", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_favorite"] is False

def test_get_recent_documents():
    headers = _register_and_login("get_recent")
    case = _create_case(headers, "Recent Case")
    
    # Upload 2 documents
    response1 = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("recent1.txt", io.BytesIO(b"recent 1"), "text/plain")}
    )
    assert response1.status_code == 200
    
    response2 = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("recent2.txt", io.BytesIO(b"recent 2"), "text/plain")}
    )
    assert response2.status_code == 200
    
    # Fetch recent
    response = client.get("/api/documents/recent?limit=5", headers=headers)
    assert response.status_code == 200
    items = response.json()
    assert len(items) >= 2
    # The first item should be the most recently uploaded/accessed
    assert items[0]["filename"] == "recent2.txt"

def test_bulk_delete_success():
    headers = _register_and_login("bulk_del")
    case = _create_case(headers, "Bulk Del Case")
    
    # Upload 2 documents
    response1 = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("del1.txt", io.BytesIO(b"del 1"), "text/plain")}
    )
    doc_id1 = response1.json()["id"]
    
    response2 = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("del2.txt", io.BytesIO(b"del 2"), "text/plain")}
    )
    doc_id2 = response2.json()["id"]
    
    # Bulk delete them
    response = client.request(
        "DELETE",
        "/api/documents/bulk",
        headers=headers,
        json={"document_ids": [doc_id1, doc_id2]}
    )
    assert response.status_code == 200
    assert response.json()["deleted_count"] == 2
    
    # Check that they are gone from db
    response = client.get(f"/api/documents/{doc_id1}", headers=headers)
    assert response.status_code == 404

def test_bulk_delete_rollback():
    headers = _register_and_login("bulk_del_roll")
    case = _create_case(headers, "Bulk Roll Case")
    
    # Upload 1 valid document
    response1 = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("valid.txt", io.BytesIO(b"valid content"), "text/plain")}
    )
    doc_id1 = response1.json()["id"]
    
    # Perform bulk delete with one valid ID and one fake UUID to trigger failure/rollback!
    fake_id = str(uuid.uuid4())
    response = client.request(
        "DELETE",
        "/api/documents/bulk",
        headers=headers,
        json={"document_ids": [doc_id1, fake_id]}
    )
    assert response.status_code == 404
    
    # Verify that valid.txt WAS NOT deleted (transaction rolled back!)
    response = client.get(f"/api/documents/{doc_id1}", headers=headers)
    assert response.status_code == 200

def test_bulk_move_success():
    headers = _register_and_login("bulk_move")
    case1 = _create_case(headers, "Source Case")
    case2 = _create_case(headers, "Dest Case")
    
    # Upload document to case 1
    response = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case1["id"]},
        files={"file": ("move.txt", io.BytesIO(b"move content"), "text/plain")}
    )
    doc_id = response.json()["id"]
    
    # Bulk move to case 2
    response = client.patch(
        "/api/documents/bulk-move",
        headers=headers,
        json={"document_ids": [doc_id], "destination_case_id": case2["id"]}
    )
    assert response.status_code == 200
    assert response.json()["moved_count"] == 1
    
    # Verify document is in case 2 now
    response = client.get(f"/api/documents/{doc_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["case_id"] == case2["id"]

def test_bulk_download_success():
    headers = _register_and_login("bulk_dl")
    case = _create_case(headers, "DL Case")
    
    # Upload 2 files
    response1 = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("f1.txt", io.BytesIO(b"file 1"), "text/plain")}
    )
    doc_id1 = response1.json()["id"]
    
    response2 = client.post(
        "/api/documents/upload",
        headers=headers,
        data={"case_id": case["id"]},
        files={"file": ("f2.txt", io.BytesIO(b"file 2"), "text/plain")}
    )
    doc_id2 = response2.json()["id"]
    
    # Bulk download ZIP
    response = client.post(
        "/api/documents/bulk-download",
        headers=headers,
        json={"document_ids": [doc_id1, doc_id2]}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    
    # Read zip bytes and confirm it has both files
    import zipfile
    zip_bytes = io.BytesIO(response.content)
    with zipfile.ZipFile(zip_bytes) as zf:
        file_list = zf.namelist()
        assert "f1.txt" in file_list
        assert "f2.txt" in file_list





