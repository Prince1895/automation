"""Upload lead PDFs to Google Drive."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from googleapiclient.http import MediaFileUpload

from .config import Config, ConfigError
from .google import get_service
from .retry import with_retries


def upload_pdf(
    path: Path,
    lead: dict[str, Any],
    config: Config,
    *,
    name: str | None = None,
) -> dict[str, str]:
    if config.dry_run:
        return {"id": f"dry-{lead.get('lead_id', 'lead')}", "webViewLink": path.as_uri()}
    if not config.drive_folder_id:
        raise ConfigError("DRIVE_FOLDER_ID is required to archive PDFs")
    service = get_service("drive", "v3", config)
    filename = name or f"InstantLead_{lead.get('lead_id')}_{path.name}"
    media = MediaFileUpload(str(path), mimetype="application/pdf", resumable=False)

    def _upload():
        return (
            service.files()
            .create(
                body={"name": filename, "parents": [config.drive_folder_id]},
                media_body=media,
                fields="id, webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )

    result = with_retries(_upload, tool="drive", attempts=3)
    return {"id": result.get("id", ""), "webViewLink": result.get("webViewLink", "")}


def upload_file(path: Path, config: Config, *, filename: str, mimetype: str) -> dict[str, str]:
    if config.dry_run:
        return {"id": f"dry-{path.stem}", "webViewLink": path.as_uri()}
    if not config.drive_folder_id:
        raise ConfigError("DRIVE_FOLDER_ID is required to archive files")
    service = get_service("drive", "v3", config)
    media = MediaFileUpload(str(path), mimetype=mimetype, resumable=False)

    def _upload():
        return (
            service.files()
            .create(
                body={"name": filename, "parents": [config.drive_folder_id]},
                media_body=media,
                fields="id, webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )

    result = with_retries(_upload, tool="drive", attempts=3)
    return {"id": result.get("id", ""), "webViewLink": result.get("webViewLink", "")}
