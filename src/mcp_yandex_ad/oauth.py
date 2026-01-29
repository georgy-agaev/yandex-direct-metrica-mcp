"""OAuth helpers (authorize URL + code exchange)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests

OAUTH_AUTHORIZE_URL = "https://oauth.yandex.ru/authorize"
OAUTH_TOKEN_URL = "https://oauth.yandex.ru/token"


@dataclass(frozen=True)
class OAuthTokens:
    access_token: str
    refresh_token: str | None
    expires_in: int | None
    token_type: str | None
    raw: dict[str, Any]


def build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str | None,
    scopes: list[str] | None,
) -> str:
    params: dict[str, str] = {"response_type": "code", "client_id": client_id}
    if redirect_uri:
        params["redirect_uri"] = redirect_uri
    if scopes:
        params["scope"] = " ".join([s.strip() for s in scopes if s.strip()])
    return f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_tokens(
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str | None,
    timeout_seconds: int = 30,
) -> OAuthTokens:
    data: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if redirect_uri:
        data["redirect_uri"] = redirect_uri

    response = requests.post(OAUTH_TOKEN_URL, data=data, timeout=timeout_seconds)
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    return OAuthTokens(
        access_token=str(payload.get("access_token") or ""),
        refresh_token=payload.get("refresh_token"),
        expires_in=payload.get("expires_in"),
        token_type=payload.get("token_type"),
        raw=payload,
    )

