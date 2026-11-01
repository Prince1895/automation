"""Google OAuth and API service builders (Gmail, Sheets, Calendar, Drive, Forms)."""

from __future__ import annotations

import json
from typing import Any

from .config import Config, ConfigError
from .logging import log_info

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/forms.responses.readonly",
]

_SERVICE_CACHE: dict[tuple[str, str], Any] = {}


def _require_oauth_config(config: Config) -> None:
    if not config.google_client_id or not config.google_client_secret:
        raise ConfigError(
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, "
            "then run: python3 tools/google_auth.py"
        )


def load_credentials(config: Config):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    _require_oauth_config(config)
    token_path = config.google_token_path
    if not token_path.exists():
        raise ConfigError(
            f"Google token not found at {token_path}. Run: python3 tools/google_auth.py"
        )
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        token_path.chmod(0o600)
        log_info("google", "refreshed OAuth token")
    return creds


def get_service(name: str, version: str, config: Config):
    key = (name, version)
    if key in _SERVICE_CACHE:
        return _SERVICE_CACHE[key]
    from googleapiclient.discovery import build

    service = build(name, version, credentials=load_credentials(config), cache_discovery=False)
    _SERVICE_CACHE[key] = service
    return service


def reset_service_cache() -> None:
    _SERVICE_CACHE.clear()


def oauth_flow(config: Config):
    from google_auth_oauthlib.flow import InstalledAppFlow

    _require_oauth_config(config)
    client_config = {
        "installed": {
            "client_id": config.google_client_id,
            "client_secret": config.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    return InstalledAppFlow.from_client_config(client_config, SCOPES)


def run_oauth(config: Config, *, open_browser: bool = True) -> str:
    flow = oauth_flow(config)

    try:
        credentials = flow.run_local_server(
            host="localhost",
            port=8765,
            open_browser=open_browser,
            authorization_prompt_message="Open this URL to authorize InstantLead: {url}",
            success_message="InstantLead authorized. You can close this window.",
        )
    except OSError as e:
        if "Address already in use" in str(e):
            print("\n[!] Local server port 8765 is occupied. Switching to Console Mode...")
            # Let the flow use its default redirect_uri from the config
            auth_url, _ = flow.authorization_url(prompt='consent')
            print(f"\n1. Go to this URL in your browser:\n\n{auth_url}\n")
            print("2. Complete the authorization. You will be redirected to a URL that doesn't load.")
            print("3. COPY the entire URL from the address bar of that failed page.")
            code_url = input("4. Paste the FULL redirect URL here: ").strip()

            import urllib.parse as urlparse
            parsed = urlparse.urlparse(code_url)
            query = urlparse.parse_qs(parsed.query)
            auth_code = query.get('code', [None])[0]

            if not auth_code:
                raise ValueError("Could not find authorization code in the provided URL.")

            flow.fetch_token(code=auth_code)
            credentials = flow.credentials
        else:
            raise e

    path = config.google_token_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(credentials.to_json(), encoding="utf-8")
    path.chmod(0o600)
    return str(path)


def token_summary(config: Config) -> dict[str, Any]:
    path = config.google_token_path
    if not path.exists():
        return {"authorized": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"authorized": False, "error": "token file is not valid JSON"}
    return {
        "authorized": bool(data.get("refresh_token") or data.get("token")),
        "scopes": data.get("scopes", []),
        "expiry": data.get("expiry"),
    }
