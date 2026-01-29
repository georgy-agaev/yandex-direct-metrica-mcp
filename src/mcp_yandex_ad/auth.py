"""Token handling for Yandex OAuth (access + refresh)."""

from dataclasses import dataclass
import logging
from typing import Any

import requests

from .config import AppConfig

logger = logging.getLogger("yandex-direct-metrica-mcp")

TOKEN_URL = "https://oauth.yandex.ru/token"


@dataclass
class AccessToken:
    value: str
    expires_in: int | None = None
    token_type: str | None = None


class TokenManager:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._access_token: str | None = config.access_token

    def get_access_token(self) -> str | None:
        if self._access_token:
            return self._access_token
        if not self._config.refresh_token:
            return None
        refreshed = self._refresh_access_token()
        if refreshed:
            self._access_token = refreshed.value
            return refreshed.value
        return None

    def _refresh_access_token(self) -> AccessToken | None:
        if not all(
            [self._config.client_id, self._config.client_secret, self._config.refresh_token]
        ):
            logger.warning("Missing OAuth client credentials for token refresh")
            return None

        data = {
            "grant_type": "refresh_token",
            "refresh_token": self._config.refresh_token,
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
        }

        try:
            response = requests.post(TOKEN_URL, data=data, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Failed to refresh token: %s", exc)
            return None

        payload: dict[str, Any] = response.json()
        return AccessToken(
            value=payload.get("access_token", ""),
            expires_in=payload.get("expires_in"),
            token_type=payload.get("token_type"),
        )
