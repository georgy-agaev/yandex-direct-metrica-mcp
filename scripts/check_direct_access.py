"""Check access to Yandex Direct.

Reads config from `.env` / environment via `load_config()` and verifies access by
calling Direct API (a minimal `campaigns.get` request).

This script avoids printing any secrets. On failure it prints a normalized error
payload with endpoint/request_id when available.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_yandex_ad.auth import TokenManager  # noqa: E402
from mcp_yandex_ad.clients import build_clients  # noqa: E402
from mcp_yandex_ad.config import load_config  # noqa: E402
from mcp_yandex_ad.errors import normalize_error  # noqa: E402


def main() -> int:
    load_dotenv()
    config = load_config()

    tokens = TokenManager(config)
    access_token = tokens.get_access_token()
    if not access_token:
        print("Missing access token. Set YANDEX_ACCESS_TOKEN or refresh credentials.")
        return 1

    clients = build_clients(config, access_token)
    if clients.direct is None:
        print("Direct client not configured (missing dependencies or token).")
        return 1

    try:
        campaigns = clients.direct.campaigns().post(
            data={
                "method": "get",
                "params": {
                    "SelectionCriteria": {},
                    "FieldNames": ["Id", "Name"],
                },
            }
        )
        count = len(campaigns.data.get("result", {}).get("Campaigns", []))
        print(
            f"Direct OK: campaigns.get returned {count} campaigns "
            f"(sandbox={config.use_sandbox}, api_version={config.direct_api_version})"
        )
        return 0
    except Exception as exc:  # pragma: no cover - runtime safety
        print(json.dumps(normalize_error("direct.check_access", exc), ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
