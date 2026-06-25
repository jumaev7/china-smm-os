# China SMM OS — Phase 1

> Internal AI-powered social media management system for Chinese companies in Uzbekistan.
> Allows one operator to manage 100–300 clients with AI assistance.

---

## What's included (Phase 1)

| Feature | Status |
|---|---|
| Client management (add/edit/delete) | ✅ |
| Media upload (image + video) | ✅ |
| Platform selection (Instagram / Facebook / TikTok) | ✅ |
| AI content generation (RU + UZ + EN, short + long captions, hashtags) | ✅ |
| Content status workflow (Draft → Ready → Approved) | ✅ |
| Content calendar (monthly view + scheduling) | ✅ |
| Approve button | ✅ |
| Auto-posting | 🔜 Phase 2 |

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind CSS, React Query |
| Backend | FastAPI, Python 3.12, SQLAlchemy 2 (async), Pydantic v2 |
| Database | PostgreSQL 16 |
| Storage | Local filesystem (dev) / S3-compatible (prod) |
| AI | OpenAI GPT-4o |
| Infrastructure | Docker + Docker Compose |

---

## Project structure

```
china-smm-os/
├── backend/                  FastAPI application
│   ├── app/
│   │   ├── api/v1/           Route handlers (clients, media, content, calendar, generate)
│   │   ├── core/             Config, database engine, storage abstraction
│   │   ├── models/           SQLAlchemy ORM models
│   │   ├── schemas/          Pydantic request/response schemas
│   │   └── services/         Business logic layer
│   ├── migrations/           Alembic async migrations
│   ├── .env.example
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/                 Next.js application
│   ├── app/
│   │   ├── (dashboard)/
│   │   │   ├── clients/      Client list + client detail
│   │   │   ├── content/      Content list + content detail + AI generation
│   │   │   └── calendar/     Monthly calendar view
│   ├── components/           Reusable UI components
│   ├── lib/
│   │   ├── api.ts            Typed API client
│   │   └── utils.ts          Helpers, status configs
│   ├── .env.example
│   └── Dockerfile
│
└── docker-compose.yml        Full local stack
```

---

## Quick start (Docker Compose)

### 1. Clone and configure

```bash
git clone <your-repo>
cd china-smm-os

# Backend env
cp backend/.env.example backend/.env
# Edit backend/.env — set your OPENAI_API_KEY

# Frontend env (optional override)
cp frontend/.env.example frontend/.env.local
```

### 2. Start everything

```bash
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs

---

## Quick start (manual / no Docker)

### Prerequisites

- Python 3.12+
- Node.js 20+
- PostgreSQL 16 running locally

### Backend

```bash
cd backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env: set DATABASE_URL and OPENAI_API_KEY

# Create the database
createdb china_smm_os   # or via psql

# Run (tables auto-created in dev mode)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The backend auto-creates all tables on first startup in `APP_ENV=development`.

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Configure
cp .env.example .env.local
# Edit .env.local if your backend runs on a different port

# Start dev server
npm run dev
```

Open http://localhost:3000

---

## Local Telegram live webhook workflow

Telegram delivers updates only to an HTTPS webhook URL. For local dev, expose the backend with a **cloudflared quick tunnel** (not ngrok free — its browser interstitial returns 503/HTML to Telegram POSTs).

### 1. Start backend

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Ensure `TELEGRAM_BOT_TOKEN` is set in `backend/.env`.

### 2. Start cloudflared quick tunnel

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

Copy the `https://xxxx.trycloudflare.com` URL from the tunnel output. **This URL changes every time cloudflared restarts** — re-run the sync script after each restart.

### 3. Sync Telegram webhook

From `backend/` (with venv active):

```bash
# Auto-detect tunnel URL from cloudflared metrics (:20241)
python scripts/sync_cloudflared_telegram_webhook.py

# Or pass the URL explicitly
python scripts/sync_cloudflared_telegram_webhook.py --public-url https://xxxx.trycloudflare.com
```

The script checks backend `/health`, calls `setWebhook`, verifies `getWebhookInfo` matches, probes the public webhook path, and prints **READY** when you can send a live test message.

Check-only (no register):

```bash
python scripts/setup_telegram_webhook.py --check-only
```

### 4. Human photo test

When the sync script reports READY, send a photo + caption in the configured Telegram group (see script output for chat id).

### Stable tunnel (later)

For a URL that does not change on restart, use a **named Cloudflare tunnel** or a **paid static domain** instead of the ephemeral `trycloudflare.com` quick tunnel.

---

## Production migrations (Alembic)

In production, use Alembic instead of auto-create:

```bash
cd backend

# Generate a migration from model changes
alembic revision --autogenerate -m "initial schema"

# Apply migrations
alembic upgrade head
```

---

## API reference

Full interactive docs at `http://localhost:8000/docs` (Swagger UI).

### Key endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/clients` | Create client |
| `GET` | `/api/v1/clients` | List all clients |
| `GET` | `/api/v1/clients/{id}` | Get single client |
| `PATCH` | `/api/v1/clients/{id}` | Update client |
| `DELETE` | `/api/v1/clients/{id}` | Delete client |
| `POST` | `/api/v1/media/upload/{client_id}` | Upload image/video |
| `GET` | `/api/v1/media/client/{client_id}` | List client media |
| `DELETE` | `/api/v1/media/{id}` | Delete media |
| `POST` | `/api/v1/content` | Create content item |
| `GET` | `/api/v1/content` | List content (filterable by client/status) |
| `GET` | `/api/v1/content/{id}` | Get content item |
| `PATCH` | `/api/v1/content/{id}` | Update captions/status |
| `POST` | `/api/v1/content/{id}/approve` | Approve content |
| `DELETE` | `/api/v1/content/{id}` | Delete content |
| `POST` | `/api/v1/generate` | Generate AI captions |
| `POST` | `/api/v1/calendar/schedule` | Schedule content |
| `GET` | `/api/v1/calendar/month/{year}/{month}` | Get calendar month |

---

## Content status workflow

```
DRAFT → READY → APPROVED
         ↑         |
         └─────────┘  (can move back to ready from approved)
```

AI generation automatically moves status from `draft` → `ready`.

---

## Database schema

| Table | Key fields |
|---|---|
| `clients` | id, company_name, source_language, business_category, content_style |
| `media_files` | id, client_id, file_type, storage_path, thumbnail_path, file_size |
| `content_items` | id, client_id, media_file_id, platforms[], status, captions (RU/UZ/EN short+long), hashtags |
| `calendar_entries` | id, content_item_id, scheduled_date, time_slot |

---

## Phase roadmap

| Phase | Focus | Status |
|---|---|---|
| Phase 1 | MVP — clients, media, AI generation, calendar, approve | ✅ Complete |
| Phase 2 | Auto-publishing to Instagram, Facebook, TikTok | 🔜 Next |
| Phase 3 | Multi-operator auth, client portal, bulk generation | 🔜 Future |
| Phase 4 | Vision AI, brand voice profiles, A/B testing | 🔜 Future |

---

## Environment variables reference

### Backend (`backend/.env`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | ✅ | — | PostgreSQL async URL |
| `OPENAI_API_KEY` | ✅ | — | OpenAI API key |
| `OPENAI_MODEL` | — | `gpt-4o` | Model to use |
| `USE_S3` | — | `false` | Enable S3 storage |
| `MEDIA_LOCAL_PATH` | — | `./media_storage` | Local storage directory |
| `S3_BUCKET` | — | — | S3 bucket name |
| `S3_ENDPOINT_URL` | — | — | S3 endpoint (for MinIO etc.) |
| `S3_ACCESS_KEY` | — | — | S3 access key |
| `S3_SECRET_KEY` | — | — | S3 secret key |
| `APP_ENV` | — | `development` | `development` or `production` |
| `SECRET_KEY` | — | — | App secret (future auth) |
| `CORS_ORIGINS` | — | `http://localhost:3000` | Allowed frontend origins |

### Frontend (`frontend/.env.local`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | — | `http://localhost:8000/api/v1` | Backend API URL |
