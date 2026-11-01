# Workflow: Daily digest and SLA alerts

## Objective

Send the sales team a daily PDF + compact email at the configured local digest
time (default 19:30 IST) with the day's KPIs and every lead, alert them when a
HOT or WARM lead has not been contacted within its SLA, and keep an eye on
backups, `/healthz` and the dead-letter queue.

## Required inputs

- Leads recorded in SQLite for the target date in `BUSINESS_TZ`.
- `SALES_EMAILS`, `DRIVE_FOLDER_ID`, `SHEET_ID` in `.env` for a live run, or
  `DRY_RUN=1` for local artifacts.
- SLA settings: `SLA_ENABLED`, `HOT_SLA_MINUTES`, `WARM_SLA_MINUTES`.
- Operations settings: `BACKUP_*`, `ALERT_*`, `HEALTHZ_URL`, `DEAD_LETTER_ALERT_THRESHOLD`.

## Tools used

- `service/scheduler.py` — fires the digest once per day and runs SLA checks.
- `service/digest.py` — builds stats, PDF, Drive archive, email and Digest tab.
- `tools/send_digest.py` — send/resend the digest for a date from the CLI.
- `tools/sla_check.py` — run the SLA check from the CLI.
- `tools/generate_pdf.py --digest-date YYYY-MM-DD` — render only the PDF.
- `service/pollers.py::check_sla` — detects uncontacted leads and sends alerts.
- `tools/backup_db.py` — verified online SQLite backup.
- `tools/monitor.py` — `/healthz` and dead-letter checks with cooldown.

## Steps

1. The scheduler checks every 15 seconds. After `DIGEST_TIME` in `BUSINESS_TZ`
   (or `locale.digest_time` in the brand config), it sends the digest once per
   `digest_date`; `digests` prevents duplicates.
2. `send_daily_digest` loads that day's leads, computes totals by tier,
   meetings booked, uncontacted HOT leads, average score and source mix.
3. It renders the branded A4 PDF, uploads it to Drive (if configured), emails a
   compact HTML + plain-text version with the PDF attached, and appends a row
   to the `Digest` tab.
4. The result is recorded in the `digests` table for auditability.
5. Every `SLA_CHECK_SECONDS`, SLA checks look for leads whose status is still
   `New` with no first-contact timestamp. HOT leads alert after
   `HOT_SLA_MINUTES`; WARM after `WARM_SLA_MINUTES`.
6. Each alerted lead is marked `alerted:<timestamp>` so the alert is not
   repeated. Updating the Sheet status (or First Contact) stops future alerts.
7. The scheduler also runs `BACKUP_INTERVAL_HOURS` SQLite backups (retained
   `BACKUP_RETENTION` copies) and periodic `/healthz` + dead-letter checks.
   `ALERT_COOLDOWN_MINUTES` suppresses repeat alerts.
8. Manual runs:
   `python3 tools/send_digest.py --date YYYY-MM-DD --force`
   `python3 tools/sla_check.py`
   `python3 tools/backup_db.py`
   `python3 tools/monitor.py --no-send`

## Expected output

- Branded daily digest PDF in `ARCHIVE_DIR` and (live) the Drive folder.
- Compact digest email to `SALES_EMAILS`; the hot list is inline, full detail is
  in the PDF.
- A `Digest` tab row: date, total, HOT/WARM/COLD, meetings, uncontacted HOT,
  average score, sources, PDF link.
- SLA alert email listing each breached lead and its contact details.
- Backups under `BACKUP_DIR` with `0600` permissions and integrity checks.
- Alert state in the `alert_state` table so repeat failures do not spam.
- Dry run writes `.eml` files and a PDF under `.tmp/` and does not call Google.

## Edge cases and known issues

- A digest is sent only once per date unless `--force` is used.
- A day with zero leads still produces a digest showing zeroes.
- The SLA clock uses lead creation time. Status changes are synced from the
  Sheet every `STATUS_SYNC_SECONDS`; until sync, the Sheet is the source of
  truth for sales activity.
- If Drive upload fails, the email still sends and the PDF link is omitted.
- If Gmail fails, the run is marked failed in `jobs` and retried on the next
  scheduler tick.
- Do not bulk-resend digests; each resend sends a real email.

## Cost estimate

- Google APIs: $0 within quota; personal Gmail limits are about 500 sends/day.
- Typical volume: 1 digest/day + a handful of SLA alerts.
- Hard caps: $1.00/run, $10.00/day, $100.00/month (no paid calls in v1).

## Human approval required?

- No for the scheduled internal digest and SLA alerts.
- Yes before sending to external recipients, changing the schedule, or
  re-sending to the whole team after a failed verification.

## Changelog

- 2026-10-23: Initial digest and SLA workflow.
- 2026-10-23: Config-driven digest time, backups and operational alerts.
