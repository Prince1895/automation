import requests
import json
from pathlib import Path
from tools.lib.config import get_config

def main():
    cfg = get_config()
    code = "4/0AXlqoi5mE3jXXYhPtwDLW7bC_8gRjLTQrAMY6akMLg2uKqcUsVGzeREfVeUeRt4Fb1C31Q"
    
    print("Attempting direct token exchange...")
    
    data = {
        "code": code,
        "client_id": cfg.google_client_id,
        "client_secret": cfg.google_client_secret,
        "redirect_uri": "http://localhost",
        "grant_type": "authorization_code",
    }
    
    response = requests.post("https://oauth2.googleapis.com/token", data=data)
    
    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        print(response.text)
        return

    token_data = response.json()
    
    # The library expects the token in a specific format for Credentials.from_authorized_user_file
    # We need to ensure it has the correct keys
    final_token = {
        "token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": cfg.google_client_id,
        "client_secret": cfg.google_client_secret,
        "scopes": [
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/forms.responses.readonly",
        ],
    }
    
    path = cfg.google_token_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(final_token), encoding="utf-8")
    path.chmod(0o600)
    print(f"Success! Token manually saved to {path}")

if __name__ == "__main__":
    main()
