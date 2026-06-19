China SMM OS — Project State Summary
Architecture
Layer	Stack
Backend
FastAPI, SQLAlchemy async, PostgreSQL, Alembic + dev create_tables() column ensures
Frontend
Next.js App Router, React Query, Tailwind
Infra
Docker Compose: postgres, backend (:8000), frontend (:3000)
Storage
Local ./media_storage (volume china-smm-os_media_storage), served at /media; S3 optional
AI
OpenAI (gpt-4o), DEMO_MODE for placeholder captions
API layout

Admin/authenticated-style: /api/v1/* (clients, media, content, calendar, generate, telegram webhook, assistant, workflow)
Public (no login): /public/review/{token}
Key services

telegram_service.py — webhook routing (private vs group)
telegram_group_agent_service.py — buffer + assemble
telegram_instruction_service.py — admin NL instructions, task memory
content_service.py — CRUD, video pipeline (burn/voice/final)
context_ai_service.py — category detection
workflow_service.py — “Prepare Everything” (in-memory progress)
content_readiness_service.py — approval checklist
content_review_service.py — client review links
Implemented Features
Core SMM
Clients with brand profile (tone, CTAs, languages, logo, etc.)
Content items: multi-platform, captions RU/UZ/EN, hashtags, notes
Media upload, content list/detail, manual approve, calendar schedule/publish
AI caption generation (/generate, /content/{id}/generate)
Video pipeline
Transcription → SRT (CN + translated RU/UZ/EN)
Burn subtitles into video
AI voiceover (fitted / extended)
Final export (subtitles + voice combined)
Telegram
Private chat: media/text → auto ContentItem (source=telegram)
Groups: role-based routing (admin vs client), ignorable chat filtered
Group agent buffer mode (default for unmapped groups)
Task memory: clients.telegram_active_content_id + fallback to latest draft/ready group content
Admin NL instructions → patch captions/notes, regenerate, schedule heuristics, buffer photo removal
Instruction timeline stored in telegram_instructions JSON
Update dedup via telegram_processed_updates
UI
Dashboard: clients, content list, content detail, calendar
Content detail: workflow panel, publishing checklist, multi-photo gallery (selected_media), Context AI override, instruction timeline, client review link
Floating AI assistant (context-aware chat + optional patch apply)
Public client review page: /review/[token]
Quality gates
Publishing checklist — blocks Approve/Schedule until critical items pass
Client review link — separate from admin approve; sets client_approved_at or changes_requested
Telegram Workflow
Private message → create ContentItem (telegram)
Group message
  ├─ workflow_mode = admin_controlled_buffer (default if unset)
  │    ├─ Client media/text → buffer only → "📥 Materials buffered..."
  │    ├─ Admin @bot + assemble → ONE ContentItem (source=tg_group_buffer)
  │    └─ Admin follow-up → update active task (not new item unless "новый контент")
  │
  └─ workflow_mode = auto_create_from_media
       ├─ Client media → one ContentItem per message (telegram_group)
       └─ Client text → attach to recent / pending
Admin instruction routing (buffer mode)

Explicit new post keywords → assemble from buffer
Assemble + no active task → create from buffer
Assemble + active task → apply to active (no duplicate)
Otherwise → apply_group_instruction() on active task
Config

TELEGRAM_ADMIN_ID — comma-separated; empty = no admin in buffer mode
TELEGRAM_GROUP_DEFAULT_BUFFER=true — groups without mode default to buffer
AI Assistant Abilities
Dashboard assistant (POST /assistant/chat, /assistant/apply)

Rewrite/shorten/formalize captions, sales tone, translate RU/UZ/EN
Hashtag suggestions, posting time advice
Context: current page, client, content item, brand profile
suggested_patch for caption/hashtag/notes fields only (never status/platforms/schedule/publish)
Context AI (context_ai_service.py)

Categories: food, auto_service, technology, beauty, construction, retail, education, real_estate, logistics, medical, generic_business
Signals: OCR, transcript, caption, visual (GPT vision), Telegram instructions
Confidence scoring; marker in internal_notes; manual override on content detail
Used in caption generation + workflow
Workflow “Prepare Everything”

Steps: subtitles → translations → captions → hashtags → post time → voice → final export → ready_for_approval
Progress in memory (_workflows dict), poll via /workflow/progress
Database Entities
Table	Purpose
clients
Company, brand profile, telegram_id, telegram_group_id, telegram_workflow_mode, telegram_active_content_id
media_files
Uploaded files per client
content_items
Posts: captions, status, source, Telegram fields, buffer refs, review token, client approval fields
calendar_entries
Scheduled posts linked to content
telegram_group_buffer_messages
Buffered group messages/media (50 msg / 24h window)
telegram_processed_updates
Webhook dedup by update_id
Content source values: manual, telegram, telegram_group, tg_group_buffer (VARCHAR 20)

Content status values: draft, ready, ready_for_approval, approved, scheduled, published, failed, changes_requested

Workflow Modes
Mode	Client setting	Behavior
admin_controlled_buffer
Explicit or default when unset
Buffer → admin assembles one post
auto_create_from_media
Explicit on client
Legacy: media auto-creates ContentItems
Set per client in UI (ClientFormModal) or DB.

Important Implementation Details
Dual approval: Admin approve → status=approved; client link → client_approved_at only (no auto-publish)
Active task: Pinned on buffer create; updated on each instruction apply; fallback query for latest group draft/ready
Buffer refs: JSON in telegram_buffer_refs; primary media in media_file_id; gallery via build_selected_media()
Internal notes layers: client source, admin instruction marker, Context AI marker, client review notes — parsing respects prefixes
Docker DB: volume china-smm-os_pgdata; backend in Docker uses postgres:5432; local .env uses localhost:5432
Startup logs: [DB] DATABASE_URL target, client/content counts
Review links: PUBLIC_APP_URL (default http://localhost:3000) + secrets.token_urlsafe(32)
Known Bugs / Caveats
Workflow progress lost on backend restart (in-memory only).
TELEGRAM_ADMIN_ID empty → buffer mode treats nobody as admin.
Existing DB clients may still have telegram_workflow_mode=auto_create_from_media from before default change.
Multi-photo posts — one ContentItem with refs; only primary media used for video workflow/subtitles.
Client approve ≠ admin approve — checklist doesn’t require client_approved_at; two parallel approval tracks.
Schedule timezone — heuristic “завтра 18:00” stored as UTC, not Tashkent-local.
No auth on admin API/dashboard (dev/internal assumption).
Alembic vs dev ensures — prod should run migrations; dev relies on create_tables() + database.py patches.
Unfinished / Not Implemented
Auto-publish to social platforms
True multi-image carousel publish (single primary media for processing)
Admin notification when client approves/requests changes via link
Checklist integration with client review status
Persistent workflow job state (Redis/DB)
Auth / RBAC for dashboard
Replacing placeholder “Telegram Group: …” auto-created clients with real client records (operational, not coded)
Group buffer: attach multiple photos as grouped Telegram album in one ContentItem model field (refs exist, not full album API)
Next Recommended Steps
Wire client review into operator flow — show “client approved” on checklist; optional gate admin Approve on client_approved_at.
Persist workflow progress — DB or Redis so Prepare Everything survives restarts.
Telegram notifications — bot message to admin on client review actions / changes_requested.
Migrate legacy group clients — set admin_controlled_buffer on known groups in DB/UI.
Production hardening — run Alembic migrations, add API auth, set PUBLIC_APP_URL / MEDIA_BASE_URL for real domain.
Video on buffer-assembled posts — clarify which ref drives subtitle/voice pipeline when multiple images + one video in buffer.
E2E test path — buffer → assemble → prepare → checklist → review link → client approve → admin approve → schedule.
Docker quick start: docker compose up -d → frontend :3000, API :8000, Postgres volume china-smm-os_pgdata. Ensure TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_ID, OPENAI_API_KEY in backend/.env.

# China SMM OS — Current Progress

## Telegram workflow completed

Implemented admin-controlled Telegram group workflow.

Current flow:

Client sends:
- text
- photos
- videos

↓

Content goes to Telegram buffer

↓

NO ContentItem created immediately

↓

Admin sends instruction:

@China_SMM_bot create only one post and use first + third image

↓

System creates ONE ContentItem from buffer

↓

Admin reviews

↓

Prepare Everything

↓

Publishing


## Telegram fixes completed

Fixed major Telegram issues:

- bot listens only to admin instructions
- no auto-publish before admin response
- group buffer mode working
- linked Telegram groups visible in client profile
- chat_id now detected and stored
- Telegram Debug logging added
- duplicate Telegram debug logs removed
- webhook issues fixed
- ngrok + webhook connected correctly
- Telegram group now successfully linked


Working state:

Telegram group:

Name:
Фантики

Workflow:
Buffer (admin-controlled)

Group ID successfully received and stored.


## Multi-media improvements

Implemented:

- multiple images in one ContentItem
- image selection from buffer
- selected image count visible
- Media 1/2 view
- can review several selected images


## Publishing system implemented

Backend:

Publishing accounts:
- Telegram
- Instagram
- Facebook
- TikTok
- LinkedIn

Added:

PublishingAccount model
PublishAttempt model
Publishing history
Mock publishing

Frontend:

Publishing page
Publishing accounts page
Test publish block
Platform selection
Publish history


Behavior:

Test publish works without changing content state.

Platform dropdown now includes:
content platforms
+
connected publishing accounts

Telegram appears even if content platform != Telegram.


## Current project status

Working:

Telegram → Buffer
Admin instruction
Content generation
Prepare Everything
Publishing page
Publishing history
Telegram group linking

Not completed:

Client Review workflow

Planned:

After admin approve:

Send preview to client:

media
caption
publish date

Buttons:

✅ Approve
✏ Request changes
❌ Regenerate

DB:

content.client_review_status:

pending
approved
changes_requested


## Startup

docker compose up -d --build

check:

docker compose ps

backend:
8000

frontend:
3000

postgres:
5432


## Important

Do NOT rewrite architecture.

Continue incrementally only.

Return changed files only.

## LAST SESSION STATE — Publishing + Scheduler

Date: 2026-05-28

### Completed recently

Implemented / tested:

- Publishing accounts page
- Mock publishing accounts:
  - Telegram
  - Instagram
  - Facebook
  - TikTok
  - LinkedIn
- Publish attempts/history
- Test publish flow
- Real Telegram publishing adapter started
- Telegram publisher supports:
  - mock mode
  - connected mode
  - Telegram channel/account_id
- Telegram debug helper added:
  - `/chat_id`
  - webhook debug logs
- Duplicate Telegram debug logging removed
- Webhook/ngrok issue fixed:
  - previous Telegram webhook returned 404
  - setWebhook fixed with current ngrok URL
  - Telegram group linking works again
- Telegram group linked successfully:
  - group name: Фантики
  - workflow: Buffer/admin-controlled
  - group ID stored in client profile
- Client Review workflow implemented
- Scheduled Publisher Worker implemented
- Publish Safety Guard implemented
- Scheduled Publish Diagnostics implemented:
  - endpoint: `/api/v1/publishing/scheduled-debug`
  - shows skip_reason and scheduler readiness

### Current scheduler diagnosis

Scheduler is running correctly.

Logs show:

[Scheduler Publish] tick:
[Scheduler Publish] due found: 0

Debug endpoint result showed:

- item status: scheduled
- admin approved: true
- platforms: instagram, telegram
- publishing accounts available: Instagram Mock, Telegram Channel Mock
- has_media: true
- has_caption: true
- skip_reason: scheduled_for in future

Root cause found:

Timezone bug.

Example:

Current backend UTC:
2026-05-28T18:10Z

User selected local Tashkent time:
23:10

Backend stored:
2026-05-28T23:10Z

This is wrong because Tashkent = UTC+5.
The backend thinks publish time is 5 hours later.

### Next task

Fix scheduled_for timezone handling.

Goal:

Frontend should treat selected datetime as local browser time and convert it to UTC before sending to backend.

Requirements:

- User selects local time in UI.
- Frontend converts local datetime to UTC ISO.
- Backend stores UTC.
- UI displays scheduled_for back in local time.
- Scheduled debug should show:
  - local_time
  - utc_time
  - is_due
- Add UI note:
  "Times are shown in your local timezone"
- Do not change publish workflow.
- Preserve manual publish, scheduled publish, mock publish, Telegram publish.

### Prompt to continue

Use this prompt next:

Fix scheduled_for timezone handling.

Current issue:
User schedules post for local time, but backend stores it as UTC incorrectly.
Example:
Current UTC: 18:10
User schedules 23:10 local Tashkent
Backend stores scheduled_for: 23:10 UTC
So scheduler thinks it is 5 hours in the future.

Goal:
Frontend local time should be converted to UTC before saving.

Requirements:
1. Treat user-selected datetime as local browser time.
2. Convert to UTC ISO before sending to backend.
3. Backend stores UTC.
4. UI displays scheduled_for back in local time.
5. Scheduled debug should show:
   local_time
   utc_time
   is_due
6. Add timezone note:
   "Times are shown in your local timezone"
7. Do not change publish workflow.
8. Return changed files only.

### Important rules

- Do NOT rewrite architecture.
- Continue incrementally only.
- Preserve existing DB content.
- Do not reset Docker volumes.
- Do not break Telegram group buffer workflow.
- Do not break client review workflow.
- Do not break manual/mock publishing.
