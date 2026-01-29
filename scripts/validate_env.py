"""Validate required environment variables without making API calls."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_yandex_ad.config import load_config


def main() -> int:
    load_dotenv()
    config = load_config()
    errors: list[str] = []
    warnings: list[str] = []

    if not config.access_token and not config.refresh_token:
        errors.append("Missing YANDEX_ACCESS_TOKEN or YANDEX_REFRESH_TOKEN")

    if config.refresh_token and (not config.client_id or not config.client_secret):
        errors.append("Missing YANDEX_CLIENT_ID or YANDEX_CLIENT_SECRET for refresh flow")

    if not config.metrica_counter_ids:
        warnings.append("YANDEX_METRICA_COUNTER_IDS is empty")
    elif len(config.metrica_counter_ids) > 1:
        warnings.append(
            "Multiple Metrica counters provided; ensure you pass counter_id per request"
        )
    if not config.direct_client_login and not config.direct_client_logins:
        warnings.append("YANDEX_DIRECT_CLIENT_LOGIN is empty (required for agency accounts)")
    if config.direct_client_login and "," in config.direct_client_login:
        warnings.append(
            "YANDEX_DIRECT_CLIENT_LOGIN must be a single login; use YANDEX_DIRECT_CLIENT_LOGINS for multiple"
        )
    if config.write_enabled and config.write_sandbox_only and not config.use_sandbox:
        warnings.append("Write enabled but sandbox is disabled; set YANDEX_DIRECT_SANDBOX=true")
    raw_version = os.getenv("YANDEX_DIRECT_API_VERSION")
    if raw_version and raw_version.strip().lower() not in {"v5", "5", "v501", "501"}:
        warnings.append("YANDEX_DIRECT_API_VERSION should be v5 or v501")

    if errors:
        print("Errors:")
        for item in errors:
            print(f"- {item}")

    if warnings:
        print("Warnings:")
        for item in warnings:
            print(f"- {item}")

    if errors:
        return 1

    print("OK: environment looks valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
