"""Google Sheets mirror: headers, formatting, idempotent upserts, status sync."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from typing import Any

from .config import Config, ConfigError
from .google import get_service
from .leads import get_lead, update_lead
from .logging import log_warning
from .util import fmt_local, format_budget, iso_utc

HEADERS = [
    "Lead ID",
    "Created (Local)",
    "Tier",
    "Score",
    "Name",
    "Phone",
    "Email",
    "Property Type",
    "Location",
    "Budget",
    "Timeline",
    "Source",
    "Status",
    "Owner",
    "Message",
    "Score Reasons",
    "Calendar Start (Local)",
    "Meet Link",
    "PDF Link",
    "Gmail Message ID",
    "Last Updated",
    "Consent",
    "SLA Flag",
    "Touch Count",
    "First Contact (Local)",
]
DIGEST_HEADERS = [
    "Date",
    "Total",
    "Hot",
    "Warm",
    "Cold",
    "Meetings",
    "Uncontacted Hot",
    "Avg Score",
    "Sources",
    "PDF Link",
]
STATUSES = ["New", "Contacted", "Qualified", "Meeting Set", "Won", "Lost", "Spam"]
LAST_COLUMN = "Y"


def _col(index: int) -> str:
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _hex(color: str) -> dict[str, float]:
    color = (color or "#000000").lstrip("#")
    if len(color) == 3:
        color = "".join(ch * 2 for ch in color)
    return {
        "red": int(color[0:2], 16) / 255,
        "green": int(color[2:4], 16) / 255,
        "blue": int(color[4:6], 16) / 255,
    }


def _service(config: Config):
    if not config.sheet_id:
        raise ConfigError("SHEET_ID is missing. Run: python3 tools/setup_sheet.py --create")
    return get_service("sheets", "v4", config)


def _tab_titles(service, config: Config) -> dict[str, int]:
    data = service.spreadsheets().get(spreadsheetId=config.sheet_id, fields="sheets.properties").execute()
    return {
        sheet["properties"]["title"]: int(sheet["properties"]["sheetId"])
        for sheet in data.get("sheets", [])
    }


def ensure_tabs(service, config: Config) -> dict[str, int]:
    titles = _tab_titles(service, config)
    wanted = [config.sheet_tab, config.quarantine_tab, config.digest_tab]
    missing = [name for name in wanted if name not in titles]
    if missing:
        service.spreadsheets().batchUpdate(
            spreadsheetId=config.sheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": name}}} for name in missing]},
        ).execute()
        titles = _tab_titles(service, config)
    return titles


def _ensure_headers(service, config: Config, tab: str, headers: list[str]) -> bool:
    end = _col(len(headers))
    current = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=config.sheet_id, range=f"'{tab}'!A1:{end}1")
        .execute()
        .get("values", [])
    )
    if current and current[0] and str(current[0][0]).strip():
        return False
    service.spreadsheets().values().update(
        spreadsheetId=config.sheet_id,
        range=f"'{tab}'!A1:{end}1",
        valueInputOption="USER_ENTERED",
        body={"values": [headers]},
    ).execute()
    return True


def _format_tab(service, config: Config, tab: str, sheet_id: int, headers: list[str]) -> None:
    colors = config.brand.get("colors", {})
    end = _col(len(headers))
    requests: list[dict[str, Any]] = [
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": _hex(colors.get("primary", "#0F3D5C")),
                        "textFormat": {"foregroundColor": _hex("#FFFFFF"), "bold": True, "fontSize": 10},
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment)",
            }
        },
        {
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        },
        {
            "setBasicFilter": {
                "filter": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": len(headers)}}
            }
        },
    ]

    if headers is HEADERS or tab == config.sheet_tab:
        for tier, key in (("HOT", "hot"), ("WARM", "warm"), ("COLD", "cold")):
            requests.append(
                {
                    "addConditionalFormatRule": {
                        "rule": {
                            "ranges": [{"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": 2, "endColumnIndex": 3}],
                            "booleanRule": {
                                "condition": {"type": "TEXT_CONTAINS", "values": [{"userEnteredValue": tier}]},
                                "format": {
                                    "backgroundColor": _hex(colors.get(f"{key}_soft", "#FFFFFF")),
                                    "textFormat": {"foregroundColor": _hex(colors.get(key, "#000000")), "bold": True},
                                },
                            },
                        },
                        "index": 0,
                    }
                }
            )
        requests.append(
            {
                "setDataValidation": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": 12, "endColumnIndex": 13},
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [{"userEnteredValue": status} for status in STATUSES],
                        },
                        "showCustomUi": True,
                        "strict": False,
                    },
                }
            }
        )

    widths = [120, 145, 72, 60, 150, 145, 190, 120, 120, 120, 120, 110, 105, 130, 300, 320, 150, 220, 240, 170, 145, 70, 110, 70, 150]
    for index, width in enumerate(widths[: len(headers)]):
        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": index, "endIndex": index + 1},
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            }
        )

    service.spreadsheets().batchUpdate(
        spreadsheetId=config.sheet_id, body={"requests": requests}
    ).execute()


def prepare_sheet(config: Config) -> dict[str, Any]:
    service = _service(config)
    titles = ensure_tabs(service, config)
    created = False
    for tab, headers in (
        (config.sheet_tab, HEADERS),
        (config.quarantine_tab, HEADERS),
        (config.digest_tab, DIGEST_HEADERS),
    ):
        if _ensure_headers(service, config, tab, headers):
            created = True
            _format_tab(service, config, tab, titles[tab], headers)
    return {"sheet_id": config.sheet_id, "tabs": list(titles), "formatted": created}


def _lead_row(lead: dict[str, Any], config: Config) -> list[Any]:
    reasons = lead.get("score_reasons") or []
    return [
        lead.get("lead_id"),
        fmt_local(lead.get("created_at"), config.business_tz, "%d %b %Y, %I:%M %p"),
        lead.get("tier"),
        lead.get("score"),
        lead.get("name") or "",
        lead.get("phone") or lead.get("phone_e164") or "",
        lead.get("email") or "",
        lead.get("property_type") or "",
        lead.get("location") or "",
        format_budget(
            lead.get("budget_min"),
            lead.get("budget_max"),
            lead.get("budget_currency") or config.currency,
        ),
        lead.get("timeline") or "Not provided",
        lead.get("source_label") or lead.get("source") or "",
        lead.get("status") or "New",
        lead.get("owner") or "",
        lead.get("message") or "",
        " | ".join(reasons),
        fmt_local(lead.get("calendar_start"), config.business_tz, "%d %b %Y, %I:%M %p") if lead.get("calendar_start") else "",
        lead.get("meet_link") or "",
        lead.get("pdf_drive_link") or "",
        lead.get("gmail_message_id") or "",
        fmt_local(lead.get("updated_at"), config.business_tz, "%d %b %Y, %I:%M %p"),
        "Yes" if lead.get("consent") else "No",
        lead.get("sla_flag") or "",
        lead.get("touch_count") or 1,
        fmt_local(lead.get("first_contact_at"), config.business_tz, "%d %b %Y, %I:%M %p") if lead.get("first_contact_at") else "",
    ]


def _tab_for(lead: dict[str, Any], config: Config) -> str:
    if (lead.get("status") or "").lower() == "spam":
        return config.quarantine_tab
    return config.sheet_tab


def upsert_lead(service, lead: dict[str, Any], config: Config) -> int:
    tab = _tab_for(lead, config)
    rows = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=config.sheet_id, range=f"'{tab}'!A2:A")
        .execute()
        .get("values", [])
    )
    row_index = None
    for offset, row in enumerate(rows, start=2):
        if row and str(row[0]) == str(lead.get("lead_id")):
            row_index = offset
            break

    values = [_lead_row(lead, config)]
    end = _col(len(HEADERS))
    if row_index:
        service.spreadsheets().values().update(
            spreadsheetId=config.sheet_id,
            range=f"'{tab}'!A{row_index}:{end}{row_index}",
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()
        return row_index

    result = (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=config.sheet_id,
            range=f"'{tab}'!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        )
        .execute()
    )
    updated_range = result.get("updates", {}).get("updatedRange", "")
    match = re.search(r"![A-Z]+(\d+)", updated_range)
    return int(match.group(1)) if match else 0


def sync_statuses(conn: sqlite3.Connection, config: Config) -> dict[str, int]:
    if config.dry_run:
        return {"updated": 0}
    service = _service(config)
    ensure_tabs(service, config)
    rows = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=config.sheet_id, range=f"'{config.sheet_tab}'!A2:{LAST_COLUMN}")
        .execute()
        .get("values", [])
    )
    updated = 0
    for offset, row in enumerate(rows, start=2):
        if not row:
            continue
        lead_id = str(row[0]) if len(row) > 0 else ""
        lead = get_lead(conn, lead_id)
        if not lead:
            continue
        status = str(row[12]) if len(row) > 12 and row[12] else lead.get("status")
        owner = str(row[13]) if len(row) > 13 and row[13] else lead.get("owner")
        sheet_contact = str(row[24]) if len(row) > 24 and row[24] else ""
        fields: dict[str, Any] = {}
        if status and status != lead.get("status"):
            fields["status"] = status
            fields["sla_flag"] = None
        if owner != (lead.get("owner") or ""):
            fields["owner"] = owner
        if sheet_contact:
            fields["first_contact_at"] = lead.get("first_contact_at") or iso_utc()
        elif status and status not in {"New", "Spam"} and not lead.get("first_contact_at"):
            fields["first_contact_at"] = iso_utc()
            service.spreadsheets().values().update(
                spreadsheetId=config.sheet_id,
                range=f"'{config.sheet_tab}'!Y{offset}",
                valueInputOption="USER_ENTERED",
                body={"values": [[fmt_local(datetime.now(config.tz), config.business_tz, "%d %b %Y, %I:%M %p")]]},
            ).execute()
        if fields:
            update_lead(conn, lead_id, **fields)
            updated += 1
    return {"updated": updated}


def update_digest_tab(service, config: Config, digest_date: str, stats: dict[str, Any], pdf_link: str) -> None:
    ensure_tabs(service, config)
    rows = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=config.sheet_id, range=f"'{config.digest_tab}'!A2:A")
        .execute()
        .get("values", [])
    )
    row_index = None
    for offset, row in enumerate(rows, start=2):
        if row and str(row[0]) == digest_date:
            row_index = offset
            break
    values = [[
        digest_date,
        stats.get("total", 0),
        stats.get("hot", 0),
        stats.get("warm", 0),
        stats.get("cold", 0),
        stats.get("meetings", 0),
        stats.get("uncontacted_hot", 0),
        stats.get("avg_score", 0),
        stats.get("sources", ""),
        pdf_link or "",
    ]]
    if row_index:
        service.spreadsheets().values().update(
            spreadsheetId=config.sheet_id,
            range=f"'{config.digest_tab}'!A{row_index}:J{row_index}",
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()
    else:
        service.spreadsheets().values().append(
            spreadsheetId=config.sheet_id,
            range=f"'{config.digest_tab}'!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()


def create_spreadsheet(config: Config, title: str = "InstantLead – Leads") -> dict[str, str]:
    if config.dry_run:
        return {"sheet_id": "dry-run-sheet", "url": "https://docs.google.com/spreadsheets/d/dry-run-sheet/edit"}
    service = get_service("sheets", "v4", config)
    spreadsheet = (
        service.spreadsheets()
        .create(body={"properties": {"title": title, "timeZone": config.business_tz}})
        .execute()
    )
    sheet_id = spreadsheet["spreadsheetId"]
    return {
        "sheet_id": sheet_id,
        "url": f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
    }
