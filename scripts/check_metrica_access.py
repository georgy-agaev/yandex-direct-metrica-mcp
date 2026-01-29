"""Check access to configured Yandex Metrica counters.

Reads `YANDEX_METRICA_COUNTER_IDS` from environment via `load_config()` and
verifies access by calling:
- Management API: `counter.get` (metadata access)
- Stats API: a small report (data access)

This script prints only counter IDs and minimal metadata (name) and avoids
printing any secrets.
"""

from __future__ import annotations

import datetime as dt
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


def _today_range(days: int = 7) -> tuple[str, str]:
    date_to = dt.date.today()
    date_from = date_to - dt.timedelta(days=days)
    return str(date_from), str(date_to)


def main() -> int:
    load_dotenv()
    config = load_config()
    if not config.metrica_counter_ids:
        print("No counters configured. Set YANDEX_METRICA_COUNTER_IDS=...")
        return 1

    tokens = TokenManager(config)
    access_token = tokens.get_access_token()
    if not access_token:
        print("Missing access token. Set YANDEX_ACCESS_TOKEN or refresh credentials.")
        return 1

    clients = build_clients(config, access_token)
    if clients.metrica_management is None and clients.metrica_stats is None:
        print("Metrica clients are not configured (missing token scopes or dependencies).")
        return 1

    date_from, date_to = _today_range(7)
    ok = True

    accessible_ids: set[str] = set()
    if clients.metrica_management is not None:
        try:
            counters = clients.metrica_management.counters().get().data.get("counters", [])
            for c in counters:
                if isinstance(c, dict) and "id" in c:
                    accessible_ids.add(str(c["id"]))
            print(f"Accessible counters via API: {len(accessible_ids)}")
        except Exception as exc:  # pragma: no cover - runtime safety
            ok = False
            print(f"Failed to list counters: {exc.__class__.__name__}: {exc}")

    for counter_id in config.metrica_counter_ids:
        print(f"counter_id={counter_id}")
        if accessible_ids:
            print(f"  in list_counters: {'YES' if counter_id in accessible_ids else 'NO'}")

        if clients.metrica_management is not None:
            try:
                info = clients.metrica_management.counter(counterId=counter_id).get()
                counter = info.data.get("counter", {})
                name = counter.get("name")
                print(f"  management: OK (name={name!r})")
            except Exception as exc:  # pragma: no cover - runtime safety
                ok = False
                print(f"  management: FAILED ({exc.__class__.__name__}: {exc})")
        else:
            print("  management: SKIPPED (client not configured)")

        if clients.metrica_stats is not None:
            try:
                report = clients.metrica_stats.stats().get(
                    params={
                        "ids": counter_id,
                        "metrics": "ym:s:visits",
                        "dimensions": "ym:s:date",
                        "date1": date_from,
                        "date2": date_to,
                        "sort": "ym:s:date",
                        "limit": 1,
                    }
                )
                rows = len(report.data.get("data", []))
                print(f"  stats: OK (rows={rows})")
            except Exception as exc:  # pragma: no cover - runtime safety
                ok = False
                print(f"  stats: FAILED ({exc.__class__.__name__}: {exc})")
        else:
            print("  stats: SKIPPED (client not configured)")

    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
