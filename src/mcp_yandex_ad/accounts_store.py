"""Accounts registry read/write helpers.

This module manages a non-secret JSON file (usually mounted from host) that maps
`account_id` to per-project defaults (Direct Client-Login, Metrica counters).
"""

from __future__ import annotations

from dataclasses import asdict
import errno
import json
from pathlib import Path
from typing import Any

from .accounts import AccountProfile, load_accounts_registry


def _profile_to_json(profile: AccountProfile) -> dict[str, Any]:
    data = asdict(profile)
    # Keep file clean: drop nulls.
    return {k: v for k, v in data.items() if v not in (None, [], {})}


def _to_payload(accounts: dict[str, AccountProfile]) -> dict[str, Any]:
    ordered = [accounts[k] for k in sorted(accounts.keys())]
    return {"accounts": [_profile_to_json(p) for p in ordered]}


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    if not path.parent.exists():
        raise FileNotFoundError(f"Accounts registry directory does not exist: {path.parent}")
    tmp_path = path.with_name(f"{path.name}.tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        tmp_path.write_text(data, encoding="utf-8")
        tmp_path.replace(path)
    except OSError as exc:
        # When the registry file is mounted as a writable file inside a read-only directory
        # (common for Docker setups), we can't create temp files. Fall back to in-place write.
        if exc.errno in {errno.EROFS, errno.EACCES}:
            path.write_text(data, encoding="utf-8")
            return
        raise


def read_accounts_file(path: str | None) -> dict[str, Any]:
    accounts = load_accounts_registry(path)
    return {
        "path": path,
        "count": len(accounts),
        "accounts": [_profile_to_json(p) for p in [accounts[k] for k in sorted(accounts.keys())]],
    }


def upsert_account(
    path: str | None,
    *,
    account_id: str,
    patch: dict[str, Any],
    replace: bool = False,
) -> dict[str, Any]:
    if not path:
        raise ValueError("MCP_ACCOUNTS_FILE is not configured.")

    normalized_id = (account_id or "").strip()
    if not normalized_id:
        raise ValueError("account_id is required.")

    accounts = load_accounts_registry(path)
    existing = accounts.get(normalized_id)

    if replace or existing is None:
        base = AccountProfile(id=normalized_id)
    else:
        base = existing

    name = base.name
    direct_login = base.direct_client_login
    counters = list(base.metrica_counter_ids or []) if base.metrica_counter_ids else None

    if "name" in patch:
        name = patch.get("name")
    if "direct_client_login" in patch:
        direct_login = patch.get("direct_client_login")
    if "metrica_counter_ids" in patch:
        value = patch.get("metrica_counter_ids")
        if value is None:
            counters = None
        elif isinstance(value, list):
            counters = [str(x).strip() for x in value if str(x).strip()]
        else:
            counters = [str(value).strip()] if str(value).strip() else None

    profile = AccountProfile(
        id=normalized_id,
        name=name,
        direct_client_login=direct_login,
        metrica_counter_ids=counters,
    ).normalized()

    created = existing is None
    accounts[profile.id] = profile

    _write_atomic(Path(path), _to_payload(accounts))
    return {
        "created": created,
        "account": _profile_to_json(profile),
        "count": len(accounts),
    }


def delete_account(path: str | None, *, account_id: str) -> dict[str, Any]:
    if not path:
        raise ValueError("MCP_ACCOUNTS_FILE is not configured.")

    normalized_id = (account_id or "").strip()
    if not normalized_id:
        raise ValueError("account_id is required.")

    accounts = load_accounts_registry(path)
    removed = accounts.pop(normalized_id, None)
    if removed is None:
        return {"deleted": False, "count": len(accounts)}

    _write_atomic(Path(path), _to_payload(accounts))
    return {"deleted": True, "account_id": normalized_id, "count": len(accounts)}
