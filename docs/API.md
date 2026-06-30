# ChronoLegal API Documentation

Base URL: `http://localhost:8000`

Interactive docs: `/docs` (Swagger) | `/redoc` (ReDoc)

---

## Health

### GET /health

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "environment": "development"
}
```

---

## Dashboard

### GET /api/dashboard

**Response:**

```json
{
  "totalCases": 0,
  "totalDocuments": 0,
  "activeCases": 0,
  "timelineEvents": 0
}
```

---

## Authentication

### POST /api/auth/register

**Request:**

```json
{
  "email": "user@example.com",
  "username": "johndoe",
  "password": "securepass123",
  "full_name": "John Doe"
}
```

**Response:** `UserResponse`

### POST /api/auth/login

**Request:**

```json
{
  "email": "user@example.com",
  "password": "securepass123"
}
```

**Response:**

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

### POST /api/auth/refresh

**Request:**

```json
{
  "refresh_token": "eyJ..."
}
```

**Response:** `TokenResponse`

### POST /api/auth/logout

**Response:**

```json
{
  "message": "Logged out successfully",
  "success": true
}
```

### GET /api/auth/me

**Response:** `UserResponse`

---

## Users

### GET /api/users/profile

**Response:** `UserResponse`

### PUT /api/users/profile

**Request:**

```json
{
  "full_name": "John Doe",
  "username": "johndoe",
  "avatar_url": "https://..."
}
```

### POST /api/users/change-password

**Request:**

```json
{
  "current_password": "oldpass123",
  "new_password": "newpass456"
}
```

---

## Documents

### GET /api/documents

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| search | string | Search by title/filename |
| status | string | uploaded, processing, processed, failed |
| document_type | string | pdf, docx, txt |
| case_id | UUID | Filter by case |
| page | int | Page number (default: 1) |
| page_size | int | Items per page (default: 10) |

**Response:**

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 10,
  "total_pages": 0
}
```

### POST /api/documents/upload

**Request:** `multipart/form-data`

| Field | Type | Required |
|-------|------|----------|
| file | File | Yes |
| title | string | No |
| case_id | UUID | No |

**Response:**

```json
{
  "id": "uuid",
  "title": "Contract.pdf",
  "filename": "Contract.pdf",
  "status": "uploaded",
  "message": "Document uploaded successfully (mock)."
}
```

### GET /api/documents/{document_id}

**Response:** `DocumentResponse`

### DELETE /api/documents/{document_id}

---

## Timeline

### GET /api/timeline

**Query Parameters:**

| Param | Type |
|-------|------|
| case_id | UUID |
| event_type | string |
| start_date | datetime |
| end_date | datetime |

**Response:**

```json
{
  "events": [],
  "total": 0,
  "case_id": null
}
```

### GET /api/timeline/events/{event_id}

**Response:** `TimelineEventResponse`

---

## Chat

### GET /api/chat/sessions

**Response:**

```json
{
  "sessions": [],
  "total": 0
}
```

### POST /api/chat/sessions

**Query:** `case_id` (optional UUID)

**Response:** `ChatSessionResponse`

### POST /api/chat/query

**Request:**

```json
{
  "content": "What are the key dates in this case?",
  "session_id": "uuid (optional)",
  "case_id": "uuid (optional)"
}
```

**Response:**

```json
{
  "session_id": "uuid",
  "user_message": { "id": "...", "content": "...", "role": "user", "session_id": "...", "created_at": "..." },
  "assistant_message": { "id": "...", "content": "...", "role": "assistant", "session_id": "...", "created_at": "..." }
}
```

### GET /api/chat/sessions/{session_id}/messages

---

## Analytics

### GET /api/analytics

**Query Parameters:** `case_id`, `category`, `start_date`, `end_date`

**Response:**

```json
{
  "metrics": [
    { "name": "Total Cases", "value": 0, "unit": "cases", "change_percent": 0, "trend": "neutral" }
  ],
  "charts": [
    { "title": "Cases by Status", "chart_type": "pie", "data": [{ "label": "Active", "value": 0 }] }
  ],
  "summary": {
    "total_cases": 0,
    "total_documents": 0,
    "total_events": 0,
    "processing_success_rate": 0.0
  }
}
```

### GET /api/analytics/metrics

### GET /api/analytics/charts

---

## Shared Schemas

### UserResponse

```json
{
  "id": "uuid",
  "email": "user@example.com",
  "username": "johndoe",
  "full_name": "John Doe",
  "role": "user",
  "is_active": true,
  "is_verified": false,
  "avatar_url": null,
  "created_at": "2026-01-01T00:00:00Z"
}
```

### DocumentResponse

```json
{
  "id": "uuid",
  "title": "Contract",
  "filename": "contract.pdf",
  "file_size": 1024,
  "mime_type": "application/pdf",
  "document_type": "pdf",
  "status": "uploaded",
  "page_count": null,
  "case_id": null,
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z"
}
```

### TimelineEventResponse

```json
{
  "id": "uuid",
  "title": "Court Hearing",
  "description": "Initial hearing scheduled",
  "event_date": "2026-01-15T10:00:00Z",
  "event_type": "hearing",
  "confidence_score": 0.95,
  "case_id": "uuid",
  "document_id": "uuid"
}
```
