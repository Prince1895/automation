"""Consistent SQLite backups with integrity checks and retention.

Uses SQLite's online backup API so WAL mode is safe and the service can keep
writing while a backup runs. Backups are owner-only files under BACKUP_DIR.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config
from .logging import log_info


def _backup_name(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    return f"instantlead-{stamp}.db"


def prune_backups(config: Config) -> int:
    files = sorted(config.backup_dir.glob("instantlead-*.db"))
    keep = max(1, config.backup_retention)
    stale = files[:-keep] if len(files) > keep else []
    for path in stale:
        try:
            path.unlink()
        except OSError:
            continue
    return len(stale)


def backup_database(
    config: Config,
    destination: Path | None = None,
    *,
    verify: bool = True,
) -> dict[str, Any]:
    source_path = config.db_path
    if not source_path.exists():
        raise FileNotFoundError(f"Database not found: {source_path}")

    config.backup_dir.mkdir(parents=True, exist_ok=True)
    target = destination or (config.backup_dir / _backup_name())
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(f"Backup already exists: {target}")

    source = sqlite3.connect(str(source_path), timeout=30)
    try:
        target_conn = sqlite3.connect(str(target))
        try:
            source.backup(target_conn)
            integrity = "ok"
            if verify:
                row = target_conn.execute("PRAGMA integrity_check").fetchone()
                integrity = str(row[0]) if row else "unknown"
                if integrity != "ok":
                    raise RuntimeError(f"Backup integrity check failed: {integrity}")
        finally:
            target_conn.close()
    except Exception:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    finally:
        source.close()

    target.chmod(0o600)
    pruned = prune_backups(config)
    result = {
        "ok": True,
        "backup": str(target),
        "bytes": target.stat().st_size,
        "integrity": integrity,
        "pruned": pruned,
    }
    log_info(
        "backup",
        "database backup created",
        file=target.name,
        bytes=result["bytes"],
        integrity=integrity,
        pruned=pruned,
    )
    return result


def last_backup(config: Config) -> Path | None:
    if not config.backup_dir.exists():
        return None
    files = sorted(config.backup_dir.glob("instantlead-*.db"))
    return files[-1] if files else None
