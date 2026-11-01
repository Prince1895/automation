"""Render branded A4 lead briefs and daily digests with WeasyPrint."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import Config
from .util import slugify


def _environment() -> Environment:
    from .config import BASE_DIR

    return Environment(
        loader=FileSystemLoader(str(BASE_DIR / "templates")),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _with_logo(facts: dict[str, Any], config: Config) -> dict[str, Any]:
    facts = dict(facts)
    company = dict(facts.get("company") or {})
    logo = company.get("logo") or ""
    if logo:
        path = Path(logo)
        if not path.is_absolute():
            path = config.base_dir / path
        company["logo"] = str(path) if path.exists() else ""
    facts["company"] = company
    return facts


def render_lead_pdf(facts: dict[str, Any], config: Config, output_path: Path | None = None) -> Path:
    from weasyprint import HTML

    facts = _with_logo(facts, config)
    html = _environment().get_template("lead_brief.html").render(**facts)
    if output_path is None:
        name = f"lead_{facts['generated_day']}_{facts['lead_id']}_{slugify(facts['name'])}.pdf"
        output_path = config.archive_dir / name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html, base_url=str(config.base_dir)).write_pdf(str(output_path))
    output_path.chmod(0o600)
    return output_path


def render_digest_pdf(facts: dict[str, Any], config: Config, output_path: Path | None = None) -> Path:
    from weasyprint import HTML

    facts = _with_logo(facts, config)
    html = _environment().get_template("digest.html").render(**facts)
    if output_path is None:
        output_path = config.archive_dir / f"InstantLead_Digest_{facts['digest_date']}.pdf"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html, base_url=str(config.base_dir)).write_pdf(str(output_path))
    output_path.chmod(0o600)
    return output_path
