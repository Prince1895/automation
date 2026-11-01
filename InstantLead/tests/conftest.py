from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "instantlead.db"))
    monkeypatch.setenv("ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("LLM_ENABLED", "0")
    monkeypatch.setenv("SALES_EMAILS", "sales@example.invalid")
    monkeypatch.setenv("SHEET_ID", "")
    monkeypatch.setenv("DRIVE_FOLDER_ID", "")
    monkeypatch.setenv("FORM_WEBHOOK_SECRET", "test-form-secret")
    monkeypatch.setenv("META_APP_SECRET", "test-meta-secret")
    monkeypatch.setenv("META_VERIFY_TOKEN", "test-verify-token")
    monkeypatch.setenv("WORKER_ENABLED", "0")
    monkeypatch.setenv("SCHEDULER_ENABLED", "0")
    monkeypatch.setenv("MAX_COST_PER_RUN", "1.00")
    monkeypatch.setenv("MAX_COST_PER_DAY", "10.00")
    monkeypatch.setenv("MAX_COST_PER_MONTH", "100.00")

    from tools.lib.config import get_config, reset_config_cache
    from tools.lib.db import init_db

    reset_config_cache()
    cfg = get_config()
    init_db(cfg.db_path)
    yield cfg
    reset_config_cache()
