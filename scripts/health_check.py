"""Basic health check for MCP Yandex Ad (no API calls)."""

from __future__ import annotations

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

    if config.write_enabled and config.write_sandbox_only and not config.use_sandbox:
        warnings.append("Write enabled but sandbox is disabled; set YANDEX_DIRECT_SANDBOX=true")

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

    print("OK: health check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
