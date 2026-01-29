"""Human-friendly (HF) tools for Yandex Metrica."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .hf_common import HFError, ensure_hf_enabled, hf_payload


def _require_counter_id(args: dict[str, Any]) -> str:
    cid = args.get("counter_id")
    if not cid:
        raise HFError("counter_id is required")
    return str(cid)


def _metric_default(metric: str | None) -> str:
    return metric or "ym:s:visits"


def _aggregate_by_period(rows: list[dict[str, Any]], *, granularity: str) -> list[dict[str, Any]]:
    # Input rows are expected to include `dimensions[0].name` as a date string like 'YYYY-MM-DD'.
    # We group by:
    # - week: ISO week (YYYY-Www)
    # - month: YYYY-MM
    # - quarter: YYYY-Qn
    # - year: YYYY
    if granularity == "day":
        return rows

    def key_for(date_str: str) -> str:
        year, month, day = date_str.split("-")
        if granularity == "week":
            import datetime as dt

            y, m, d = int(year), int(month), int(day)
            iso = dt.date(y, m, d).isocalendar()
            return f"{iso.year}-W{iso.week:02d}"
        if granularity == "month":
            return f"{year}-{month}"
        if granularity == "quarter":
            q = (int(month) - 1) // 3 + 1
            return f"{year}-Q{q}"
        if granularity == "year":
            return year
        return date_str

    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        dims = row.get("dimensions") or []
        mets = row.get("metrics") or []
        if not dims:
            continue
        name = dims[0].get("name") if isinstance(dims[0], dict) else None
        if not isinstance(name, str) or len(name) < "YYYY-MM-DD".__len__():
            continue
        k = key_for(name[:10])
        if k not in buckets:
            buckets[k] = {"period": k, "metrics": [0.0 for _ in mets]}
        # Sum metrics by index.
        for i, v in enumerate(mets):
            try:
                buckets[k]["metrics"][i] += float(v)
            except Exception:
                continue

    out = list(buckets.values())
    out.sort(key=lambda x: x["period"])
    return out


def handle(tool: str, ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    ensure_hf_enabled(ctx.config)

    if tool == "metrica.hf.list_accessible_counters":
        data = ctx._metrica_get_management("counters", args.get("params") or {})  # type: ignore[attr-defined]
        counters = data.get("counters", data.get("counters", []))  # api returns {"counters":[...]}
        if isinstance(data.get("counters"), list):
            counters = data["counters"]
        return hf_payload(tool=tool, status="ok", result={"counters": counters})

    if tool == "metrica.hf.counter_summary":
        counter_id = _require_counter_id(args)
        info = ctx._metrica_get_counter(counter_id, {})  # type: ignore[attr-defined]
        # goals list best-effort
        goals = None
        try:
            goals = ctx._metrica_management_call(  # type: ignore[attr-defined]
                resource="goals",
                method="get",
                params=None,
                data=None,
                path_args={"counterId": counter_id},
            )
        except Exception:
            goals = None
        return hf_payload(tool=tool, status="ok", result={"counter": info.get("counter", info), "goals": goals})

    if tool == "metrica.hf.report_time_series":
        counter_id = _require_counter_id(args)
        date_from = args.get("date_from")
        date_to = args.get("date_to")
        if not date_from or not date_to:
            raise HFError("date_from and date_to are required")
        metric = _metric_default(args.get("metric"))
        granularity = (args.get("granularity") or "day").lower()
        raw = ctx._metrica_get_stats(  # type: ignore[attr-defined]
            {
                "ids": counter_id,
                "metrics": metric,
                "dimensions": "ym:s:date",
                "date1": date_from,
                "date2": date_to,
                "sort": "ym:s:date",
                "limit": 100000,
            }
        )
        rows = raw.get("data", [])
        if not isinstance(rows, list):
            rows = []
        agg = _aggregate_by_period(rows, granularity=granularity)
        return hf_payload(tool=tool, status="ok", result={"counter_id": counter_id, "metric": metric, "granularity": granularity, "data": agg, "raw": raw})

    if tool == "metrica.hf.report_landing_pages":
        counter_id = _require_counter_id(args)
        date_from = args.get("date_from")
        date_to = args.get("date_to")
        if not date_from or not date_to:
            raise HFError("date_from and date_to are required")
        limit = int(args.get("limit") or 50)
        raw = ctx._metrica_get_stats(  # type: ignore[attr-defined]
            {
                "ids": counter_id,
                "metrics": "ym:s:visits,ym:s:avgVisitDurationSeconds",
                "dimensions": "ym:s:startURL",
                "date1": date_from,
                "date2": date_to,
                "sort": "-ym:s:visits",
                "limit": limit,
            }
        )
        return hf_payload(tool=tool, status="ok", result={"counter_id": counter_id, "raw": raw})

    if tool == "metrica.hf.report_utm_campaigns":
        counter_id = _require_counter_id(args)
        date_from = args.get("date_from")
        date_to = args.get("date_to")
        if not date_from or not date_to:
            raise HFError("date_from and date_to are required")
        limit = int(args.get("limit") or 50)
        raw = ctx._metrica_get_stats(  # type: ignore[attr-defined]
            {
                "ids": counter_id,
                "metrics": "ym:s:visits,ym:s:avgVisitDurationSeconds",
                "dimensions": "ym:s:UTMCampaign,ym:s:UTMContent",
                "date1": date_from,
                "date2": date_to,
                "sort": "-ym:s:visits",
                "limit": limit,
            }
        )
        return hf_payload(tool=tool, status="ok", result={"counter_id": counter_id, "raw": raw})

    if tool == "metrica.hf.report_geo":
        counter_id = _require_counter_id(args)
        date_from = args.get("date_from")
        date_to = args.get("date_to")
        if not date_from or not date_to:
            raise HFError("date_from and date_to are required")
        level = (args.get("level") or "country").lower()
        dim = "ym:s:geoCountry" if level == "country" else "ym:s:geoCity"
        limit = int(args.get("limit") or 50)
        raw = ctx._metrica_get_stats(  # type: ignore[attr-defined]
            {
                "ids": counter_id,
                "metrics": "ym:s:visits,ym:s:avgVisitDurationSeconds",
                "dimensions": dim,
                "date1": date_from,
                "date2": date_to,
                "sort": "-ym:s:visits",
                "limit": limit,
            }
        )
        return hf_payload(tool=tool, status="ok", result={"counter_id": counter_id, "raw": raw})

    if tool == "metrica.hf.report_devices":
        counter_id = _require_counter_id(args)
        date_from = args.get("date_from")
        date_to = args.get("date_to")
        if not date_from or not date_to:
            raise HFError("date_from and date_to are required")
        limit = int(args.get("limit") or 50)
        raw = ctx._metrica_get_stats(  # type: ignore[attr-defined]
            {
                "ids": counter_id,
                "metrics": "ym:s:visits,ym:s:avgVisitDurationSeconds",
                "dimensions": "ym:s:deviceCategory",
                "date1": date_from,
                "date2": date_to,
                "sort": "-ym:s:visits",
                "limit": limit,
            }
        )
        return hf_payload(tool=tool, status="ok", result={"counter_id": counter_id, "raw": raw})

    if tool == "metrica.hf.logs_export_preset":
        counter_id = _require_counter_id(args)
        date_from = args.get("date_from")
        date_to = args.get("date_to")
        if not date_from or not date_to:
            raise HFError("date_from and date_to are required")
        # Minimal preset: create + evaluate.
        preview = {
            "create": {
                "action": "create",
                "counter_id": counter_id,
                "date_from": date_from,
                "date_to": date_to,
                "source": "visits",
                "fields": "ym:s:dateTime,ym:s:clientID,ym:s:startURL,ym:s:UTMCampaign,ym:s:UTMContent,ym:s:yclid",
            },
            "evaluate": {
                "action": "evaluate",
                "counter_id": counter_id,
                "date_from": date_from,
                "date_to": date_to,
                "source": "visits",
                "fields": "ym:s:dateTime,ym:s:clientID,ym:s:startURL,ym:s:UTMCampaign,ym:s:UTMContent,ym:s:yclid",
            },
        }
        return hf_payload(tool=tool, status="ok", preview=preview)

    raise HFError(f"Unknown HF Metrica tool: {tool}")

