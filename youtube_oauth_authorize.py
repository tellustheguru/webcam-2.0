#!/usr/bin/env python3
import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


BASE_DIR = Path(__file__).resolve().parent
CLIENT_FILE = BASE_DIR / "youtube-oauth-client.json"
TOKEN_FILE = BASE_DIR / "youtube-oauth-token.json"
SCOPES = ["https://www.googleapis.com/auth/youtube"]


def main():
    if not CLIENT_FILE.exists():
        raise SystemExit(f"OAuth-klienten saknas: {CLIENT_FILE}")

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_FILE, SCOPES)
    credentials = flow.run_local_server(
        host="127.0.0.1",
        port=8765,
        open_browser=False,
        timeout_seconds=600,
        access_type="offline",
        prompt="consent",
        authorization_prompt_message="Öppna denna adress i webbläsaren:\n{url}\n",
        success_message="YouTube är auktoriserat. Du kan stänga fliken.",
    )
    TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
    os.chmod(TOKEN_FILE, 0o600)
    print(f"Token sparad säkert i {TOKEN_FILE}")


if __name__ == "__main__":
    main()
