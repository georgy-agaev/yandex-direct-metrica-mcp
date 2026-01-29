"""Project accounts registry (multi-project support).

This module provides a lightweight way to map a human-friendly `account_id` to:
- Direct `Client-Login`
- default Metrica counter IDs

It intentionally does NOT store OAuth tokens or other secrets.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("yandex-direct-metrica-mcp")


@dataclass(frozen=True)
class AccountProfile:
    id: str
    name: str | None = None
    direct_client_login: str | None = None
    metrica_counter_ids: list[str] | None = None

    def normalized(self) -> "AccountProfile":
        account_id = (self.id or "").strip()
        if not account_id:
            raise ValueError("AccountProfile.id is required")
        name = (self.name or "").strip() or None
        direct_login = (self.direct_client_login or "").strip() or None
        counters = [str(x).strip() for x in (self.metrica_counter_ids or []) if str(x).strip()]
        return AccountProfile(
            id=account_id,
            name=name,
            direct_client_login=direct_login,
            metrica_counter_ids=counters or None,
        )


def _parse_registry_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("accounts"), list):
            return [x for x in payload["accounts"] if isinstance(x, dict)]
        if isinstance(payload.get("profiles"), list):
            return [x for x in payload["profiles"] if isinstance(x, dict)]
    raise ValueError("Accounts registry must be a list or an object with 'accounts' array")


def load_accounts_registry(path: str | None) -> dict[str, AccountProfile]:
    if not path:
        return {}

    file_path = Path(path)
    try:
        raw = file_path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("Failed to read accounts registry file: %s (%s)", path, exc.__class__.__name__)
        return {}

    accounts: dict[str, AccountProfile] = {}
    try:
        items = _parse_registry_payload(payload)
        for item in items:
            profile = AccountProfile(
                id=str(item.get("id") or ""),
                name=item.get("name"),
                direct_client_login=item.get("direct_client_login") or item.get("directClientLogin"),
                metrica_counter_ids=item.get("metrica_counter_ids")
                or item.get("metricaCounterIds")
                or item.get("metrica_counters"),
            ).normalized()
            accounts[profile.id] = profile
    except Exception as exc:
        logger.warning("Failed to parse accounts registry file: %s (%s)", path, exc.__class__.__name__)
        return {}

    return accounts
