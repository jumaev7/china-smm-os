# Social Listening Phase 4 — Production Operations and Webhooks

Phase 4 adds a signed, durable Meta webhook inbox to the existing governed
Facebook Page comments and tagged-mentions sources. It does not add Instagram,
global keyword discovery, competitor-wide Facebook coverage, or provider writes.

## Processing contract

1. Meta verifies `GET /api/webhooks/meta-listening` using
   `LISTENING_META_WEBHOOK_VERIFY_TOKEN`.
2. POST bodies are capped at 1 MB and require `X-Hub-Signature-256`, verified
   with `META_APP_SECRET` before JSON parsing or database writes.
3. Page ids route only to enabled `facebook_page_comments` and
   `facebook_page_mentions` sources whose `provider_resource_ref` matches.
   Tenant identity is taken from the matched source, never from the payload.
4. Each source/change pair has a deterministic SHA-256 event key and a database
   uniqueness constraint. Duplicate delivery is acknowledged without duplicate work.
5. Only a bounded operational summary is retained. Message text, author data,
   tokens, secrets, and the raw payload are not persisted in the inbox.
6. Processing invokes the existing GET-only live adapter under its committed DB
   lease. The webhook is a freshness signal; provider reads remain canonical.
7. Claims are atomic; abandoned `processing` claims become recoverable after five
   minutes. Failed events use bounded exponential retry and then become `dead_letter`.
   Tenant owners/managers can replay them. Polling remains reconciliation fallback.

## Operations

Authenticated endpoints:

- `GET /api/v1/listening/ops/webhook-events`
- `POST /api/v1/listening/ops/webhook-events/process`
- `POST /api/v1/listening/ops/webhook-events/{event_id}/replay`

The Listening Runs screen exposes inbox status, attempts, sanitized error codes,
processing, and replay. No endpoint can reply, react, publish, or otherwise mutate
Meta content.

## Required external setup

- Set `META_APP_SECRET` and a distinct `LISTENING_META_WEBHOOK_VERIFY_TOKEN`.
- Expose the HTTPS callback and subscribe the approved Meta app/Page fields.
- Complete Meta App Review and Advanced Access for production permissions.
- Enable `LISTENING_WORKER_ENABLED=true` and run
  `python backend/scripts/run_listening_worker.py`. The worker drains webhook
  retries and performs polling reconciliation. The authenticated process endpoint
  remains available for controlled operations and development verification.
