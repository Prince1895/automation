# Workflow: Lead intake and routing

## Objective

Accept leads from the website form, Google Forms, Gmail enquiries, WhatsApp
Cloud API and Instagram Messaging; normalise and deduplicate them; score them
HOT/WARM/COLD; and route each lead to the Sheet, Calendar/Meet, branded PDF,
Drive and Gmail. Webhooks must return immediately so provider retries never
lose a lead.

## Required inputs

- A source payload, one of:
  - Website form JSON posted to `POST /webhooks/form`
  - Meta webhook posted to `POST /webhooks/meta` (WhatsApp or Instagram)
  - Gmail/IMAP enquiry discovered by the email poller
  - Google Forms response discovered by the Forms poller
- `.env` configured for the live run, or `DRY_RUN=1` for a local run.
- For CLI testing: a JSON fixture and its source name.

## Tools used

- `service/main.py` — FastAPI intake, signature/token checks, queue insertion.
- `service/worker.py` — background queue processor with retries and dead-letter.
- `tools/process_queue.py` — one-shot CLI queue drain.
- `tools/ingest_lead.py` — ingest a fixture directly (no HTTP).
- `tools/poll_now.py` — poll Forms and/or the enquiry inbox on demand.
- `tools/replay_failed.py` — reset retry/dead events.
- `tools/queue_status.py` — queue depth, job status, leads by tier.
- `tools/init_db.py` — create the SQLite schema.
- `tools/reply.py` — list, approve or reject first-reply drafts.
- `tools/delete_lead.py` — GDPR-style erasure of a lead.
- `tools/lib/*` — normalisation, scoring, PDF, Sheet, Drive, Gmail, Calendar, replies.

## Steps

1. Start the service: `uvicorn service.main:app --host 0.0.0.0 --port 8080`.
   The worker and scheduler start with it unless disabled in `.env`.
2. The intake endpoint validates the request (Meta HMAC or form token/HMAC),
   writes an idempotent event to SQLite and returns `200` immediately.
3. The worker claims the event, normalises every lead, merges duplicates by
   phone then email, and deletes completed routing steps so a repeat enquiry is
   routed again.
4. Scoring runs deterministic rules first. If `OPENROUTER_API_KEY` is set, a
   sanitised free-text extraction is schema-validated and may adjust intent by
   at most ±10; any failure silently falls back to rules-only.
5. Spam leads are written to the Quarantine tab and get no PDF or email.
6. HOT and WARM (and COLD only when `COLD_EMAIL_ENABLED=1`) get: branded PDF →
   Drive → Calendar hold + Meet link → Sheet upsert → compact HTML email with
   the PDF attached. COLD leads go to the Sheet only.
7. In `FIRST_REPLY_MODE=approval` (default), the pipeline drafts a first reply
   for leads with an email or phone number and waits for a human. Approving an
   email draft sends it; approving a phone-only draft records manual contact.
   `FIRST_REPLY_MODE=auto` sends email drafts immediately and marks phone-only
   drafts approved; `off` skips drafting. `reply.py approve` records the
   measured response time.
8. The worker marks the event done. On failure it retries with backoff; after
   `MAX_EVENT_ATTEMPTS` the event becomes `dead` and is visible in
   `queue_status.py`. Dead-letter growth triggers `monitor.py` alerts.
9. For a local check run:
   `DRY_RUN=1 python3 tools/ingest_lead.py --source form --file tests/fixtures/form_lead.json`
   then inspect `.tmp/outbox/` and `.tmp/archive/`.

## Expected output

- SQLite (`DB_PATH`) is the source of truth for leads, events and steps.
- Google Sheet: one row per lead with tier, score, reasons, status, Meet and
  PDF links. Spam goes to the Quarantine tab.
- Drive: one branded PDF per notified lead.
- Gmail: one compact factual email per notified lead, PDF attached.
- Calendar: an internal 30-minute hold with a Meet link for HOT/WARM leads.
- Logs: redacted JSONL under `LOG_DIR`; LLM cost rows in `logs/costs.jsonl`.
- SQLite: first-reply drafts, response metrics and WAL-mode backups.

## Edge cases and known issues

- Meta requires a public HTTPS URL. Use Cloudflare Tunnel for local testing.
- Instagram DM and WhatsApp production sending need app review/business
  verification; local tests work only for users with app roles and the test
  number.
- Google Forms has no webhook: poll every `FORM_POLL_SECONDS`.
- A duplicate webhook is ignored by `(source, external_id)`. A genuine repeat
  enquiry (new external ID, same phone/email) updates the lead and reruns
  routing.
- Missing values are stored as `NULL` and rendered as “Not provided”; the
  pipeline never invents budget, location or contact details.
- If no calendar slot exists in the horizon, the lead still gets its Sheet row
  and email; the calendar step is marked skipped.
- A failed Gmail/Drive/Calendar call leaves completed steps in place; replay
  resumes from the failed step.
- Free LLM limits or outages trigger rules-only scoring automatically.

## Cost estimate

- Deterministic code, SQLite, Sheets, Drive, Gmail, Calendar and inbound Meta:
  $0 within quotas.
- OpenRouter free model: $0; rate limits fall back to rules.
- Expected volume: up to a few hundred leads/month. `MAX_COST_PER_RUN`,
  `MAX_COST_PER_DAY` and `MAX_COST_PER_MONTH` are enforced before paid calls.
- Hard caps in `.env.example`: $1.00/run, $10.00/day, $100.00/month.

## Human approval required?

- No for intake, scoring, Sheet, PDF, Drive and internal sales email.
- Yes before enabling customer-facing replies/outbound WhatsApp templates,
  bulk replays that consume paid credits, or exposing webhooks publicly.
- Sales confirms the meeting with the lead before the Meet link is shared.

## Changelog

- 2026-10-23: Initial intake workflow; dry-run support; deterministic free-text
  extraction for budget, timeline, property type and location.
- 2026-10-23: Added approval-mode first replies, deletion and backup/alert tools.
