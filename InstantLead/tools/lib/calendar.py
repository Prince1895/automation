"""Find a free business slot and create a Calendar event with Google Meet."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .config import Config
from .google import get_service
from .retry import with_retries
from .util import fmt_local, format_budget


class NoSlotError(RuntimeError):
    pass


def _events(service, config: Config, start: datetime, end: datetime) -> list[dict[str, Any]]:
    result = (
        service.events()
        .list(
            calendarId=config.calendar_id,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=250,
        )
        .execute()
    )
    return result.get("items", [])


def _busy(events: list[dict[str, Any]], tz: ZoneInfo, default_minutes: int) -> list[tuple[datetime, datetime]]:
    busy: list[tuple[datetime, datetime]] = []
    for event in events:
        if event.get("status") == "cancelled":
            continue
        start_raw = (event.get("start") or {}).get("dateTime")
        end_raw = (event.get("end") or {}).get("dateTime")
        if not start_raw:
            continue
        try:
            start = datetime.fromisoformat(start_raw).astimezone(tz)
            end = (
                datetime.fromisoformat(end_raw).astimezone(tz)
                if end_raw
                else start + timedelta(minutes=default_minutes)
            )
        except (TypeError, ValueError):
            continue
        busy.append((start, end))
    return busy


def find_slot(
    config: Config,
    service=None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    tz = ZoneInfo(config.business_tz)
    now = (now or datetime.now(tz)).astimezone(tz)
    horizon = now + timedelta(hours=config.booking_horizon_hours)
    busy = _busy(_events(service, config, now, horizon + timedelta(days=1)), tz, config.meeting_minutes) if service else []
    buffer = timedelta(minutes=config.slot_buffer_minutes)
    duration = timedelta(minutes=config.meeting_minutes)
    earliest = now + timedelta(minutes=config.slot_buffer_minutes)

    for day_offset in range(0, max(1, config.booking_horizon_hours // 24 + 2)):
        day = (now + timedelta(days=day_offset)).date()
        if day.weekday() not in config.business_days:
            continue
        day_start = datetime.combine(day, datetime.min.time(), tzinfo=tz).replace(
            hour=config.business_start[0], minute=config.business_start[1]
        )
        day_end = datetime.combine(day, datetime.min.time(), tzinfo=tz).replace(
            hour=config.business_end[0], minute=config.business_end[1]
        )
        candidate = max(day_start, earliest)
        # Align to a 15-minute grid anchored at business start.
        minutes_from_start = int((candidate - day_start).total_seconds() // 60)
        remainder = minutes_from_start % 15
        if remainder:
            candidate += timedelta(minutes=15 - remainder)
        while candidate + duration <= day_end and candidate <= horizon:
            candidate_end = candidate + duration
            conflict = False
            for busy_start, busy_end in busy:
                if candidate < busy_end + buffer and candidate_end + buffer > busy_start:
                    conflict = True
                    break
            if not conflict:
                return candidate, candidate_end
            candidate += timedelta(minutes=15)
    raise NoSlotError(
        f"No free {config.meeting_minutes}-minute slot in the next {config.booking_horizon_hours}h"
    )


def _description(lead: dict[str, Any], facts: dict[str, Any]) -> str:
    reasons = " | ".join(facts.get("reasons", [])[:4])
    lines = [
        f"Lead ID: {lead.get('lead_id')}",
        f"Tier: {lead.get('tier')} ({lead.get('score')}/100)",
        f"Name: {facts.get('name')}",
        f"Phone: {facts.get('phone')}",
        f"Email: {facts.get('email')}",
        f"Requirement: {facts.get('property_type')} · {facts.get('location')}",
        f"Budget: {facts.get('budget')}",
        f"Timeline: {facts.get('timeline')}",
        f"Source: {facts.get('source')}",
        f"Why: {reasons}",
    ]
    if facts.get("links", {}).get("pdf"):
        lines.append(f"Lead brief: {facts['links']['pdf']}")
    if facts.get("links", {}).get("sheet"):
        lines.append(f"Sheet row: {facts['links']['sheet']}")
    lines.append("Internal hold created by InstantLead. Confirm with the lead before sharing the Meet link.")
    return "\n".join(lines)


def create_event(
    lead: dict[str, Any],
    facts: dict[str, Any],
    config: Config,
    *,
    service=None,
) -> dict[str, Any]:
    start, end = find_slot(config, service)
    if config.dry_run:
        return {
            "event_id": f"dry-{lead.get('lead_id')}",
            "start": start.isoformat(),
            "meet_link": f"https://meet.google.com/dry-{str(lead.get('lead_id', 'lead')).lower()}",
        }

    service = service or get_service("calendar", "v3", config)
    body = {
        "summary": (
            f"[{lead.get('tier')}] {facts.get('name')} "
            f"{'— ' + facts.get('property_type') if facts.get('property_type') and facts.get('property_type') != 'Not provided' else ''} "
            f"{' ' + facts.get('location') if facts.get('location') and facts.get('location') != 'Not provided' else ''}"
        ).strip(),
        "description": _description(lead, facts),
        "start": {"dateTime": start.isoformat(), "timeZone": config.business_tz},
        "end": {"dateTime": end.isoformat(), "timeZone": config.business_tz},
        "attendees": [{"email": email} for email in config.sales_emails],
        "conferenceData": {
            "createRequest": {
                "requestId": f"instantlead-{lead.get('lead_id')}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 10},
                {"method": "email", "minutes": 30},
            ],
        },
        "extendedProperties": {"private": {"instantlead_id": str(lead.get("lead_id"))}},
    }

    def _insert():
        return (
            service.events()
            .insert(
                calendarId=config.calendar_id,
                body=body,
                conferenceDataVersion=1,
                sendUpdates="all",
            )
            .execute()
        )

    event = with_retries(_insert, tool="calendar", attempts=3)
    meet_link = ""
    for point in (event.get("conferenceData") or {}).get("entryPoints", []):
        if point.get("entryPointType") == "video":
            meet_link = point.get("uri", "")
            break
    return {
        "event_id": event.get("id", ""),
        "start": (event.get("start") or {}).get("dateTime", start.isoformat()),
        "meet_link": meet_link or event.get("hangoutLink", ""),
    }


def event_summary(lead: dict[str, Any], config: Config) -> str:
    currency = lead.get("budget_currency") or config.currency
    return (
        f"{lead.get('tier')} · "
        f"{fmt_local(lead.get('calendar_start'), config.business_tz)} · "
        f"{format_budget(lead.get('budget_min'), lead.get('budget_max'), currency)}"
    )
