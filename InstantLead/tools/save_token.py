import json
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from tools.lib.config import get_config

def main():
    cfg = get_config()
    # Recreate the flow to use the same client config
    client_config = {
        "installed": {
            "client_id": cfg.google_client_id,
            "client_secret": cfg.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, 
        [
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/forms.responses.readonly",
        ])
    
    # The code provided by the user
    code = "4/0AXlqoi5mE3jXXYhPtwDLW7bC_8gRjLTQrAMY6akMLg2uKqcUsVGzeREfVeUeRt4Fb1C31Q"

    print("Exchanging code for token...")
    # For Desktop apps, the redirect_uri MUST be passed to fetch_token to match the auth request
    flow.fetch_token(code=code, redirect_uri="http://localhost")
    credentials = flow.credentials
    
    path = cfg.google_token_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(credentials.to_json(), encoding="utf-8")
    path.chmod(0o600)
    print(f"Success! Token saved to {path}")

if __name__ == "__main__":
    main()
