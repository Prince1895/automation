# Workflow: Google setup (OAuth, Sheet, Drive, Gmail, Calendar)

## Objective

Connect the service to a Google account so it can mirror leads to a Sheet,
archive PDFs in Drive, create Calendar holds with Meet links, send Gmail
notifications, read enquiry email and poll Google Forms.

## Required inputs

- A Google Cloud project and an OAuth **Desktop** client.
- The Google account that owns the Sheet, Drive folder and Calendar.
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` in `.env`.
- Sales recipient addresses, and optionally an existing `SHEET_ID` and
  `DRIVE_FOLDER_ID`.

## Tools used

- `tools/google_auth.py` — OAuth consent flow; writes a refresh token.
- `tools/setup_sheet.py` — creates/configures the Leads, Quarantine and Digest
  tabs, formatting, filters, tier colours and status dropdown.
- `tools/init_db.py` — local database.
- `service/pollers.py` — Gmail/Forms polling and Sheet status sync.

## Steps

1. In Google Cloud, create a project and enable: Gmail API, Google Sheets API,
   Google Calendar API, Google Drive API and Google Forms API.
2. Configure the OAuth consent screen. Add the scopes requested by
   `tools/lib/google.py`: `gmail.send`, `gmail.readonly`, `spreadsheets`,
   `calendar`, `drive`, `forms.responses.readonly`.
3. Create an OAuth client of type **Desktop app** and copy the client ID and
   secret into `.env`. Never commit them.
4. Run `.venv/bin/python tools/google_auth.py` and approve access in the
   browser. The token is written to `GOOGLE_TOKEN_PATH` with owner-only
   permissions.
5. Optional: create the Sheet with
   `.venv/bin/python tools/setup_sheet.py --create --title "InstantLead – Leads"`,
   then put the returned `sheet_id` in `.env` as `SHEET_ID`.
6. Run `.venv/bin/python tools/setup_sheet.py` to create/format the tabs on an
   existing Sheet.
7. Create a Drive folder for briefs and put its ID in `DRIVE_FOLDER_ID`.
8. Set `CALENDAR_ID=primary` (or a shared calendar ID), `SALES_EMAILS` and
   `SENDER_EMAIL`/`SENDER_NAME`.
9. Verify: `.venv/bin/python tools/google_auth.py` (prints the authorized
   scopes) and `.venv/bin/python tools/poll_now.py --source email`.
10. Start the service and submit one fixture through the pipeline. Confirm the
    Sheet row, Drive PDF, Gmail message and Calendar/Meet hold.

## Expected output

- A refresh token at `GOOGLE_TOKEN_PATH` (never committed).
- A formatted Sheet with Leads, Quarantine and Digest tabs.
- Drive folder ready for lead briefs.
- Working internal email notifications and Calendar/Meet holds.

## Edge cases and known issues

- **Testing-mode OAuth apps expire refresh tokens after 7 days.** For a
  personal Gmail, set publishing status to “In production” (unverified app
  warning) or verify the scopes.
- Use the Gmail API, not IMAP app passwords, unless `EMAIL_SOURCE=imap` is a
  deliberate fallback.
- `GOOGLE_REDIRECT_URI` must match the local callback used by the OAuth flow.
- Token refresh requires the client ID/secret that created the token.
- The service account is not used; this is user OAuth so Gmail/Calendar work.
- Never print or commit token contents, client secrets or `.env`.
- Google Forms has no webhook; enable `FORMS_POLL_ENABLED=1` and set
  `GOOGLE_FORM_ID` to poll every `FORM_POLL_SECONDS`.

## Cost estimate

- Google APIs used here are $0 within standard quotas.
- Gmail sending is limited to roughly 500 recipients/day for personal accounts.
- No paid API is used by this setup.

## Human approval required?

- Yes for granting OAuth scopes and for creating a new Sheet in the client's
  Drive.
- Yes before switching the OAuth app to production or verifying scopes.

## Changelog

- 2026-10-23: Initial Google setup workflow.
