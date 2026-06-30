# ChronoLegal — Legal Question Answering and Case Analytics

> **Phase 1 Foundation** — Production-quality monorepo architecture with mock API responses. No AI, OCR, RAG, embeddings, or database persistence yet.

## Project Structure

```
legal_ai/
├── frontend/          # Next.js 16 + React 19 + TypeScript + Tailwind + Shadcn UI
├── backend/           # FastAPI + SQLAlchemy + Alembic + Pydantic
├── docs/              # Architecture and API documentation
└── README.md
```

## Tech Stack

| Layer    | Technologies |
|----------|-------------|
| Frontend | Next.js 15+, React, TypeScript, Tailwind CSS, Shadcn UI, React Query, Axios, Zustand |
| Backend  | FastAPI, SQLAlchemy, Alembic, PostgreSQL (schema-ready), Pydantic, JWT-ready |
| Database | PostgreSQL (models + migrations ready; not connected in Phase 1) |

## Quick Start

### Prerequisites

- Node.js 18+ (tested with v22)
- Python 3.11+
- PostgreSQL 14+ (optional for Phase 1 — only needed when running migrations)

### 1. Backend

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # Windows
# cp .env.example .env   # macOS/Linux

uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### 2. Frontend

```bash
cd frontend
npm install
copy .env.example .env.local   # Windows
# cp .env.example .env.local     # macOS/Linux

npm run dev
```

App: [http://localhost:3000](http://localhost:3000)

### 3. Run Tests (Backend)

```bash
cd backend
pytest tests/ -v
```

## Frontend Pages

| Route | Description |
|-------|-------------|
| `/login` | User authentication |
| `/register` | New account registration |
| `/dashboard` | Overview widgets (cases, documents, events) |
| `/documents` | Upload area, search, filters, document table |
| `/timeline` | Timeline visualization + event cards |
| `/chat` | ChatGPT-like legal chat interface |
| `/analytics` | Analytics cards and chart placeholders |
| `/settings` | Theme and preferences |
| `/profile` | User profile management |

## API Endpoints (Mock)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/dashboard` | Dashboard statistics |
| POST | `/api/auth/register` | Register user |
| POST | `/api/auth/login` | Login (returns JWT tokens) |
| GET | `/api/auth/me` | Current user |
| GET | `/api/documents` | List documents |
| POST | `/api/documents/upload` | Upload document |
| GET | `/api/timeline` | Timeline events |
| POST | `/api/chat/query` | Send chat message |
| GET | `/api/analytics` | Analytics overview |
| GET | `/api/users/profile` | User profile |

See [docs/API.md](docs/API.md) for full API contracts.

## Database (Migration-Ready)

SQLAlchemy models are defined for: `User`, `Case`, `Document`, `TimelineEvent`, `ChatSession`, `ChatMessage`, `AnalyticsRecord`.

When PostgreSQL is available:

```bash
cd backend
alembic upgrade head
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for ER diagram and relationships.

## Phase 2 Expansion Points

- PostgreSQL persistence layer
- JWT authentication enforcement
- Document storage (S3/local)
- OCR and text extraction
- ChronoLegal event extraction
- Temporal graph construction
- Vector database + RAG pipeline
- LLM integration for legal reasoning
- Real-time analytics and charting

## License

Academic project — Final Year AIML.
