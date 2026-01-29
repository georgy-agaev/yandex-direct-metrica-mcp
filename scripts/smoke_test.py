"""Smoke test for Yandex Direct + Metrica using real credentials."""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp_yandex_ad.auth import TokenManager
from mcp_yandex_ad.clients import build_clients
from mcp_yandex_ad.config import load_config
from mcp_yandex_ad.errors import normalize_error


def main() -> int:
    load_dotenv()
    config = load_config()
    tokens = TokenManager(config)
    access_token = tokens.get_access_token()

    if not access_token:
        print("Missing access token. Set YANDEX_ACCESS_TOKEN or refresh credentials.")
        return 1

    clients = build_clients(config, access_token)

    if clients.direct is not None:
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
            print(f"Direct campaigns OK: {count}")
        except Exception as exc:  # pragma: no cover - runtime safety
            print(json.dumps(normalize_error("direct.campaigns.get", exc), ensure_ascii=False))
    else:
        print("Direct client not configured.")

    if clients.metrica_management is not None:
        try:
            counters = clients.metrica_management.counters().get()
            count = len(counters.data.get("counters", []))
            print(f"Metrica counters OK: {count}")
        except Exception as exc:  # pragma: no cover - runtime safety
            print(json.dumps(normalize_error("metrica.counters.get", exc), ensure_ascii=False))
    else:
        print("Metrica management client not configured.")

    counter_id = config.metrica_counter_ids[0] if config.metrica_counter_ids else None
    if clients.metrica_stats is not None and counter_id:
        try:
            date_to = dt.date.today()
            date_from = date_to - dt.timedelta(days=7)
            report = clients.metrica_stats.stats().get(
                params={
                    "ids": counter_id,
                    "metrics": "ym:s:visits",
                    "dimensions": "ym:s:date",
                    "date1": str(date_from),
                    "date2": str(date_to),
                    "sort": "ym:s:date",
                }
            )
            rows = len(report.data.get("data", []))
            print(f"Metrica report OK: {rows} rows")
        except Exception as exc:  # pragma: no cover - runtime safety
            print(json.dumps(normalize_error("metrica.stats.get", exc), ensure_ascii=False))
    else:
        print("Metrica stats client not configured or counter ID missing.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
