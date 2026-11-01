# InstantLead

Lead automation for a real-estate sales team, built with the **WAT framework**:
Markdown workflows define the process, the agent coordinates and recovers, and
deterministic Python tools do the work.

## What it does

1. **Intakes** leads from a website form, Google Forms, Gmail enquiries,
   WhatsApp Cloud API and Instagram Messaging.
2. **Normalises and deduplicates** every lead into SQLite.
3. **Scores** each lead HOT/WARM/COLD with explainable rules. An optional free
   OpenRouter model can read free-text intent, is schema-validated, may adjust
   intent by at most ±10, and silently falls back to rules.
4. **Mirrors** leads into a branded Google Sheet with status dropdowns, filters,
   tier colours and an SLA flag.
5. **Books** an internal Calendar hold with a Google Meet link for HOT/WARM
   leads in the next free business slot.
6. **Creates a branded A4 PDF brief** with score breakdown and provenance,
   archives it in Drive, links it in the Sheet, and emails it to sales.
7. **Sends a daily digest PDF + email at the configured local time** (default 19:30 IST) with KPIs and all leads.
8. **Drafts the first customer reply at ingestion** for leads with an email or
   phone number. Approval mode queues email drafts for human review; approved
   replies send through Gmail and response times are recorded.
9. **Alerts on SLA breaches** for uncontacted HOT/WARM leads, with retries,
   dead-letter handling and replay.

The email is a compact fact card. The PDF is the explained brief. Both are
rendered from the same `lead_facts` object, so they cannot disagree.

```
Website form ─┐
Google Forms ─┤
Gmail inbox ──┼─► FastAPI intake ─► SQLite queue ─► worker
WhatsApp ─────┤   (validate/sign)        │
Instagram ────┘                          ▼
                            normalize → dedupe → score
                                             │
              ┌──────────────────────────────┼──────────────────────┐
              ▼                              ▼                      ▼
      HOT/WARM routing              Per-lead branded PDF      Google Sheet
      Calendar + Meet               Drive archive + link      team view
              │                              │
              └──────────► Gmail alert to sales ◄───────────────┘
                                             │
                              configured digest time: digest PDF + SLA report
```

## Layout

```
InstantLead/
├── AGENTS.md              # Agent operating rules
├── README.md
├── service/
│   ├── main.py            # FastAPI: /webhooks/meta, /webhooks/form, /healthz
│   ├── worker.py          # queue processor, retries, dead-letter
│   ├── scheduler.py       # pollers, digest, backups, alerts, SLA checks
│   ├── pipeline.py        # score → PDF → Drive → Calendar → Sheet → email
│   ├── pollers.py         # Gmail/IMAP, Google Forms, Sheet status sync, SLA
│   └── digest.py          # daily digest delivery
├── tools/
│   ├── lib/               # db, config, normalise, scoring, PDF, email, Google
│   ├── init_db.py
│   ├── ingest_lead.py
│   ├── process_queue.py
│   ├── poll_now.py
│   ├── sla_check.py
│   ├── send_digest.py
│   ├── generate_pdf.py
│   ├── google_auth.py
│   ├── setup_sheet.py
│   ├── replay_failed.py
│   ├── queue_status.py
│   ├── reply.py           # list/approve/reject first replies
│   ├── delete_lead.py     # GDPR-style lead erasure
│   ├── backup_db.py       # verified SQLite backup
│   ├── monitor.py         # healthz + dead-letter alerts
│   ├── seed_demo.py       # isolated demo data
│   └── benchmark.py       # labelled 100-lead benchmark
├── templates/             # Jinja2 HTML/CSS for email, PDF and digest
├── assets/                # logo and palette
├── config/brand.yaml      # company, colours, scoring bands, service areas
├── tests/                 # fixtures for all 5 sources + unit/integration tests
├── workflows/             # lead-intake, daily-digest, setup-google
├── config/clients/        # second sample locale (coastal-realty.yaml)
├── benchmarks/latest.json # generated benchmark result
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example           # variable names and safe default caps
```

CI lives at the repository root: `automation/.github/workflows/ci.yml`.

## Setup

```bash
cd InstantLead
cp .env.example .env
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python tools/init_db.py
```

Edit `.env` for local or live mode. Never commit `.env` or print its values.
`config/brand.yaml` holds the company name, logo, colours, service areas and
budget bands; replace the placeholders before a live run.

### Dry run (no credentials required)

```bash
DRY_RUN=1 python3 tools/ingest_lead.py --source form \
  --file tests/fixtures/form_lead.json
```

Artifacts appear in `.tmp/outbox/` (`.eml` emails, Sheet rows) and
`.tmp/archive/` (PDFs). `DRY_RUN=1` writes emails and Drive links as local
files and never calls Google or Meta.

### Live run

1. Complete `workflows/setup-google.md` (OAuth, Sheet, Drive, Calendar).
2. Set the Meta app secret, verify token and WhatsApp/Instagram credentials in
   `.env`.
3. Set `SALES_EMAILS`, `SENDER_EMAIL`, `SHEET_ID`, `DRIVE_FOLDER_ID` and
   `CALENDAR_ID`.
4. Start the service:

   ```bash
   .venv/bin/uvicorn service.main:app --host 0.0.0.0 --port 8080
   ```

   This starts the worker and scheduler too. Expose the webhook URL over HTTPS
   (Cloudflare Tunnel locally, a VPS later) and register it with Meta.

## Commands

| Command | Purpose |
|---|---|
| `.venv/bin/python -m pytest -q tests` | Run all tests |
| `python3 tools/init_db.py` | Create/upgrade the SQLite schema |
| `python3 tools/ingest_lead.py --source form --file <json>` | Ingest a fixture or captured payload |
| `python3 tools/process_queue.py --max-events 10` | Drain queued events once |
| `python3 tools/poll_now.py --source both` | Poll Forms and email now |
| `python3 tools/send_digest.py --date YYYY-MM-DD --force` | Send/resend a digest |
| `python3 tools/sla_check.py` | Run SLA checks now |
| `python3 tools/queue_status.py` | Queue depth, jobs, leads by tier |
| `python3 tools/replay_failed.py` | Reset retry/dead events |
| `python3 tools/generate_pdf.py --lead-id <id>` | Re-render a lead brief |
| `python3 tools/setup_sheet.py --create` | Create and format the Google Sheet |
| `python3 tools/google_auth.py` | Authorize Google OAuth |
| `python3 tools/reply.py list` | List pending first-reply drafts |
| `python3 tools/reply.py approve --lead-id <id> --yes` | Send an approved first reply |
| `python3 tools/reply.py stats` | First-reply response-time metrics |
| `python3 tools/delete_lead.py --email <email> --yes` | Erase a lead and local artifacts |
| `python3 tools/backup_db.py` | Take a verified SQLite backup |
| `python3 tools/monitor.py` | Check /healthz and dead-letter alerts |
| `python3 tools/seed_demo.py --reset` | Load an isolated demo dataset |
| `python3 tools/benchmark.py --leads 100` | Reproduce the benchmark |

## Scoring

Score 0–100: contactability 20, intent 30, budget 20, timeline 20, source and
engagement 10, minus penalties (no contact, outside service area, spam).

- **HOT** ≥70, or ≥60 with a ≤30-day timeline and a phone number
- **WARM** 40–69
- **COLD** <40
- **Spam** quarantined; no PDF or email

HOT and WARM leads are routed immediately. COLD leads go to the Sheet and daily
digest only unless `COLD_EMAIL_ENABLED=1`. Score reasons and a factor-by-factor
breakdown are stored and shown in the PDF and Sheet.

## Data integrity and privacy

- Missing values are stored as `NULL` and rendered as “Not provided”; nothing is
  guessed or invented.
- Free-text extraction is deterministic and grounded. LLM output is
  schema-validated and discarded unless grounded in the source message.
- Only the lead message is sent to OpenRouter, with emails and phone numbers
  removed. `LLM_ENABLED=0` or an empty key forces rules-only.
- Logs redact names, phone numbers, emails, tokens and keys. Runtime files
  (`.env`, `.tmp/`, `logs/`) are never committed.
- `RETENTION_DAYS` defaults to 365; events are pruned by the worker.
- High-impact actions (bulk sends, customer-facing replies, paid runs) require
  explicit approval per `AGENTS.md`.

## Workflows

- `workflows/lead-intake.md` — intake, scoring, routing and retries
- `workflows/daily-digest.md` — digest, backups and SLA/alerts
- `workflows/setup-google.md` — OAuth, Sheet, Drive, Gmail and Calendar setup


## First replies (approval mode)

Leads with an email address or phone number get a first-reply draft created at
ingestion time. Email drafts can be sent through Gmail; phone-only drafts are
approved to record manual contact. Drafts live in `first_replies` and are
listed/approved via:

```bash
.venv/bin/python tools/reply.py list
.venv/bin/python tools/reply.py approve --lead-id <id> --yes
.venv/bin/python tools/reply.py approve --all --yes
.venv/bin/python tools/reply.py stats
```

- `FIRST_REPLY_MODE=approval` (default): leads with email or phone get a draft; approving an email draft sends it via Gmail, while approving a phone-only draft records manual contact.
- `FIRST_REPLY_MODE=auto`: sends email drafts directly and marks phone-only drafts approved for manual contact (high-impact; use with caution).
- `FIRST_REPLY_MODE=off`: no drafts.
- `/healthz` reports `pending_replies` and first-reply response-time metrics. Response time runs from lead creation to Gmail send or manual approval.

## GDPR / delete a lead

Erase a lead and local personal data (DB rows, queue events, PDFs/emails,
artifacts). Remote Google copies must be removed with Google's tooling.

```bash
.venv/bin/python tools/delete_lead.py --email person@example.com        # plan
.venv/bin/python tools/delete_lead.py --email person@example.com --yes  # erase
.venv/bin/python tools/delete_lead.py --lead-id <id> --phone +91... --yes
```

## Backups and alerts

- SQLite uses WAL mode. Backups run via `tools/backup_db.py` / scheduler job `db_backup` (online `.backup()`).
- `tools/monitor.py` checks `/healthz` and dead-letter count, alerts via email/webhook with cooldowns.
- Health endpoint: `GET /healthz` includes `wal`, `pending_replies`, `dead_letter`, `last_backup`.

## Demo and benchmark

```bash
.venv/bin/python tools/seed_demo.py --reset --approve-replies 3 --digest
.venv/bin/python tools/benchmark.py --leads 100 --seed 42
```

### Benchmark results (100 leads, seed 42)

| Metric | Value |
|---|---|
| Leads processed | 100 / 100 |
| Total time | 27.69 s |
| Mean per lead | 276.9 ms |
| p50 / p95 | 320.9 ms / 464.5 ms |
| Throughput | 3.61 leads/s |
| Tier accuracy | 100.0% |
| Spam accuracy | 100.0% |
| Cost per lead | $0.000000 (rules-only) |
| First replies drafted (email + phone-only) | 90 |
| Sent via Gmail / marked manual | 45 / 45 |
| Median / p90 response time (send or approval) | 12.5 s / 24 s |
| Within first-reply SLA | 90 / 90 |

The benchmark runs the full dry-run pipeline, including PDF render, calendar
hold, Sheet row, sales email and first-reply draft, so most of the time is
WeasyPrint PDF generation. Rules-only scoring is the same in live mode; paid
LLM extraction is disabled here. Numbers vary by machine; regenerate with the
command above.

## Docker

```bash
cp .env.example .env  # fill credentials, or start with DRY_RUN=1
docker compose up --build
```

The image runs `tools/init_db.py` on start and serves `uvicorn service.main:app` on `:8080`.

## CI

[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)

Replace `OWNER/REPO` with your GitHub repository.

## Known limitations

- Meta requires a public HTTPS webhook. Instagram DM and WhatsApp production
  access usually require app review/business verification; local testing works
  only for app-role users and the test number until approved.
- Google Forms has no webhook and is polled every `FORM_POLL_SECONDS`.
- Testing-mode Google OAuth refresh tokens expire after 7 days; publish the app
  to production or verify scopes for a durable token.
- SLA tracking depends on sales updating the Sheet status. First replies default
  to approval mode; `FIRST_REPLY_MODE=auto` is opt-in and high-impact.
- No paid API is used. Hard caps `MAX_COST_PER_RUN`, `MAX_COST_PER_DAY` and
  `MAX_COST_PER_MONTH` are enforced before any paid call.
