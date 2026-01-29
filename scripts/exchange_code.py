"""Exchange OAuth authorization code for access + refresh tokens."""

from __future__ import annotations

import argparse
import os
import sys

import requests

TOKEN_URL = "https://oauth.yandex.ru/token"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Exchange code for tokens")
    parser.add_argument("--code", help="Authorization code")
    parser.add_argument("--client-id", help="OAuth client id")
    parser.add_argument("--client-secret", help="OAuth client secret")
    parser.add_argument("--redirect-uri", help="Redirect URI (if required)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    code = args.code or os.getenv("YANDEX_AUTH_CODE")
    client_id = args.client_id or os.getenv("YANDEX_CLIENT_ID")
    client_secret = args.client_secret or os.getenv("YANDEX_CLIENT_SECRET")
    redirect_uri = args.redirect_uri or os.getenv("YANDEX_REDIRECT_URI")

    missing = []
    if not code:
        missing.append("code")
    if not client_id:
        missing.append("client_id")
    if not client_secret:
        missing.append("client_secret")
    if missing:
        print(f"Missing required fields: {', '.join(missing)}")
        return 1

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if redirect_uri:
        data["redirect_uri"] = redirect_uri

    try:
        response = requests.post(TOKEN_URL, data=data, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"Token exchange failed: {exc}")
        return 1

    print(response.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
