"""Send compact HTML emails with the branded PDF attached via the Gmail API."""

from __future__ import annotations

import base64
import mimetypes
import re
import uuid
from email import encoders
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Any

from .config import Config, ConfigError
from .google import get_service
from .logging import log_info
from .retry import with_retries
from .util import slugify


def _from_header(config: Config) -> str | None:
    if not config.sender_email:
        return None
    name = config.sender_name or config.brand.get("company", {}).get("name", "InstantLead")
    return f"{name} <{config.sender_email}>"


def _attach_file(root: MIMEMultipart, attachment: Path) -> None:
    mime, _ = mimetypes.guess_type(str(attachment))
    maintype, subtype = (mime or "application/octet-stream").split("/", 1)
    part = MIMEBase(maintype, subtype)
    part.set_payload(attachment.read_bytes())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=attachment.name)
    root.attach(part)


def _build_message(
    *,
    subject: str,
    html: str,
    text: str,
    recipients: list[str],
    config: Config,
    attachments: list[Path] | None = None,
    logo_path: str = "",
) -> MIMEMultipart:
    if not recipients:
        if not config.dry_run:
            raise ConfigError("SALES_EMAILS is empty; set at least one recipient")
        recipients = ["dry-run@example.invalid"]

    root = MIMEMultipart("mixed")
    root["Subject"] = re.sub(r"[\r\n]+", " ", subject)
    from_header = _from_header(config)
    if from_header:
        root["From"] = from_header
    root["To"] = ", ".join(recipients)
    root["Date"] = formatdate(localtime=True)
    root["Message-ID"] = make_msgid(domain="instantlead.local")

    related = MIMEMultipart("related")
    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(text, "plain", "utf-8"))
    alternative.attach(MIMEText(html, "html", "utf-8"))
    related.attach(alternative)

    logo = Path(logo_path) if logo_path else None
    if logo and not logo.is_absolute():
        logo = config.base_dir / logo
    if logo and logo.exists():
        mime, _ = mimetypes.guess_type(str(logo))
        subtype = (mime or "image/png").split("/", 1)[1]
        image = MIMEImage(logo.read_bytes(), _subtype=subtype)
        image.add_header("Content-ID", "<companylogo>")
        image.add_header("Content-Disposition", "inline", filename=logo.name)
        related.attach(image)

    root.attach(related)
    for attachment in attachments or []:
        _attach_file(root, attachment)
    return root


def _send_raw(raw: bytes, config: Config) -> str:
    service = get_service("gmail", "v1", config)
    encoded = base64.urlsafe_b64encode(raw).decode("ascii")

    def _send():
        return service.users().messages().send(userId="me", body={"raw": encoded}).execute()

    result = with_retries(_send, tool="gmail", attempts=3)
    return str(result.get("id", ""))


def _write_eml(message: MIMEMultipart, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(message.as_bytes())
    path.chmod(0o600)


def send_lead_email(
    *,
    subject: str,
    html: str,
    text: str,
    pdf_path: Path,
    facts: dict[str, Any],
    config: Config,
) -> str:
    message = _build_message(
        subject=subject,
        html=html,
        text=text,
        recipients=config.sales_emails,
        config=config,
        attachments=[pdf_path],
        logo_path=facts.get("company", {}).get("logo", ""),
    )
    if config.dry_run:
        path = config.outbox_dir / f"lead_{facts['lead_id']}_{slugify(facts['name'])}.eml"
        _write_eml(message, path)
        log_info("gmail", "wrote dry-run lead email", lead_id=facts.get("lead_id"), file=path.name)
        return f"dry-{uuid.uuid4().hex[:10]}"
    message_id = _send_raw(message.as_bytes(), config)
    log_info("gmail", "sent lead email", lead_id=facts.get("lead_id"), message_id=message_id)
    return message_id


def send_digest_email(
    *,
    subject: str,
    html: str,
    text: str,
    pdf_path: Path,
    facts: dict[str, Any],
    config: Config,
) -> str:
    message = _build_message(
        subject=subject,
        html=html,
        text=text,
        recipients=config.sales_emails,
        config=config,
        attachments=[pdf_path],
        logo_path=facts.get("company", {}).get("logo", ""),
    )
    if config.dry_run:
        path = config.outbox_dir / f"digest_{facts['digest_date']}.eml"
        _write_eml(message, path)
        log_info("gmail", "wrote dry-run digest email", file=path.name)
        return f"dry-{uuid.uuid4().hex[:10]}"
    message_id = _send_raw(message.as_bytes(), config)
    log_info("gmail", "sent digest email", message_id=message_id)
    return message_id


def send_customer_email(
    *,
    to_address: str,
    subject: str,
    html: str,
    text: str,
    lead_id: str,
    config: Config,
) -> str:
    """Send an approved first reply to the lead (never a sales notification)."""
    message = _build_message(
        subject=subject,
        html=html,
        text=text,
        recipients=[to_address],
        config=config,
        logo_path=config.brand.get("company", {}).get("logo", ""),
    )
    if config.dry_run:
        path = config.outbox_dir / f"reply_{slugify(lead_id)}.eml"
        _write_eml(message, path)
        log_info("gmail", "wrote dry-run first reply", lead_id=lead_id, file=path.name)
        return f"dry-{uuid.uuid4().hex[:10]}"
    message_id = _send_raw(message.as_bytes(), config)
    log_info("gmail", "sent first reply", lead_id=lead_id, message_id=message_id)
    return message_id


def send_alert(
    subject: str,
    html: str,
    text: str,
    config: Config,
    *,
    recipients: list[str] | None = None,
) -> str:
    message = _build_message(
        subject=subject,
        html=html,
        text=text,
        recipients=recipients if recipients is not None else config.sales_emails,
        config=config,
        logo_path=config.brand.get("company", {}).get("logo", ""),
    )
    if config.dry_run:
        path = config.outbox_dir / f"alert_{uuid.uuid4().hex[:8]}.eml"
        _write_eml(message, path)
        return f"dry-{uuid.uuid4().hex[:10]}"
    return _send_raw(message.as_bytes(), config)
