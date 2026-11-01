#!/usr/bin/env python3
"""Run the Google OAuth flow and save a refresh token.

Purpose: authorize Gmail, Sheets, Calendar, Drive and Forms scopes.
Inputs: GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET in .env
Outputs: token path and scope summary.
Example: python3 tools/google_auth.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.lib import google
from tools.lib.config import get_config


def main() -> int:
    cfg = get_config()
    path = google.run_oauth(cfg, open_browser=False)
    summary = google.token_summary(cfg)
    print(json.dumps({"ok": True, "token_path": path, **summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
