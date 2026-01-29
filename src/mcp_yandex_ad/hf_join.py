"""Human-friendly (HF) join tools combining Direct and Metrica."""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlsplit
from typing import Any

from .hf_common import HFError, ensure_hf_enabled, hf_payload


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _first_key(payload: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _normalize_key(value: Any) -> str:
    return _as_str(value).strip()


def _guess_delimiter(text: str) -> str:
    if "\t" in text:
        return "\t"
    if ";" in text:
        return ";"
    return ","


def _parse_delimited(
    raw: str,
    *,
    delimiter: str | None = None,
    columns: list[str] | None = None,
    max_rows: int | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    raw = raw or ""
    delimiter = delimiter or _guess_delimiter(raw)
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        return [], columns or []

    resolved_columns = columns[:] if columns else []

    # If columns are not provided, treat the first non-empty line as a header when it looks like one.
    if not resolved_columns:
        header = [c.strip() for c in lines[0].split(delimiter)]
        if len(header) >= 2 and all(h and not h.replace(".", "").replace("_", "").isdigit() for h in header):
            resolved_columns = header
            lines = lines[1:]

    rows: list[dict[str, str]] = []
    for line in lines:
        if line.lower().startswith(("total", "итого", "всего")):
            continue
        parts = [p for p in line.split(delimiter)]
        if resolved_columns and len(parts) != len(resolved_columns):
            continue
        if not resolved_columns:
            resolved_columns = [f"col_{i}" for i in range(len(parts))]
        rows.append({resolved_columns[i]: parts[i] for i in range(len(parts))})
        if max_rows is not None and len(rows) >= max_rows:
            break
    return rows, resolved_columns


def _extract_metrica_time_series(payload: dict[str, Any]) -> dict[str, float]:
    data = payload.get("data")
    if not isinstance(data, list):
        return {}

    series: dict[str, float] = {}
    for row in data:
        if not isinstance(row, dict):
            continue
        dims = row.get("dimensions")
        mets = row.get("metrics")
        if not isinstance(dims, list) or not isinstance(mets, list) or not dims or not mets:
            continue
        dim0 = dims[0]
        if isinstance(dim0, dict):
            date = _as_str(dim0.get("name")).strip()
        else:
            date = _as_str(dim0).strip()
        if not date:
            continue
        try:
            value = float(mets[0])
        except Exception:
            continue
        series[date] = series.get(date, 0.0) + value
    return series


def _metrica_filter_quote(value: str) -> str:
    """Quote a value for Metrica `filters` expression.

    Metrica filter examples commonly use single quotes. If the value contains a
    single quote, we fall back to double quotes and escape them.
    """
    value = value or ""
    if "'" not in value:
        return "'" + value.replace("\\", "\\\\") + "'"
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _direct_campaign_performance_params(*, campaign_id: int, date_from: str, date_to: str) -> dict[str, Any]:
    return {
        "SelectionCriteria": {
            "DateFrom": date_from,
            "DateTo": date_to,
            "Filter": [{"Field": "CampaignId", "Operator": "IN", "Values": [str(int(campaign_id))]}],
        },
        "FieldNames": ["Date", "CampaignId", "Impressions", "Clicks", "Cost"],
        "ReportName": f"HF_join_direct_{campaign_id}",
        "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
        "DateRangeType": "CUSTOM_DATE",
        "Format": "TSV",
        "IncludeVAT": "YES",
        "IncludeDiscount": "NO",
    }


def _direct_clickid_report_params(
    *,
    date_from: str,
    date_to: str,
    report_type: str,
    field_names: list[str],
    report_name: str,
) -> dict[str, Any]:
    return {
        "SelectionCriteria": {"DateFrom": date_from, "DateTo": date_to},
        "FieldNames": field_names,
        "ReportName": report_name[:255],
        "ReportType": report_type,
        "DateRangeType": "CUSTOM_DATE",
        "Format": "TSV",
        "IncludeVAT": "YES",
        "IncludeDiscount": "NO",
    }


def _extract_raw_and_columns(report_payload: dict[str, Any]) -> tuple[str, list[str] | None]:
    if "raw" in report_payload and isinstance(report_payload.get("raw"), str):
        columns = report_payload.get("columns") if isinstance(report_payload.get("columns"), list) else None
        return report_payload["raw"], columns
    result = report_payload.get("result")
    if isinstance(result, dict) and isinstance(result.get("raw"), str):
        columns = result.get("columns") if isinstance(result.get("columns"), list) else None
        return result["raw"], columns
    return "", None


def _build_clickid_index(
    direct_report_payload: dict[str, Any],
    *,
    click_id_field: str,
    campaign_id_field: str,
    max_rows: int,
) -> tuple[dict[str, str], dict[str, Any]]:
    raw, columns = _extract_raw_and_columns(direct_report_payload)
    rows, resolved_columns = _parse_delimited(raw, delimiter="\t", columns=columns, max_rows=max_rows)
    if not rows:
        return {}, {"rows": 0, "columns": resolved_columns}

    if click_id_field not in resolved_columns or campaign_id_field not in resolved_columns:
        raise HFError(
            f"Direct report does not contain required columns. "
            f"Need {click_id_field!r} and {campaign_id_field!r}. Got: {resolved_columns}"
        )

    index: dict[str, str] = {}
    skipped = 0
    for row in rows:
        click_id = _normalize_key(row.get(click_id_field))
        campaign_id = _normalize_key(row.get(campaign_id_field))
        if not click_id or not campaign_id:
            skipped += 1
            continue
        index.setdefault(click_id, campaign_id)

    return index, {
        "rows": len(rows),
        "columns": resolved_columns,
        "unique_click_ids": len(index),
        "skipped": skipped,
    }


def _logs_extract_request_id(create_payload: dict[str, Any]) -> str:
    # Common response shape from Metrica Logs API:
    # {"log_request": {"request_id": 123, ...}}
    log_request = create_payload.get("log_request")
    if isinstance(log_request, dict):
        nested = _first_key(log_request, ["request_id", "requestId", "requestID", "id"])
        nested = _as_str(nested).strip()
        if nested:
            return nested

    request_id = _first_key(create_payload, ["request_id", "requestId", "requestID", "id"])
    request_id = _as_str(request_id).strip()
    if not request_id:
        raise HFError(f"Could not extract request_id from logs create response: {create_payload}")
    return request_id


def _logs_find_request_info(allinfo_payload: dict[str, Any], request_id: str) -> dict[str, Any] | None:
    candidates: list[Any] = []
    for key in ("requests", "data", "result"):
        value = allinfo_payload.get(key)
        if isinstance(value, list):
            candidates = value
            break
    if not candidates:
        value = allinfo_payload.get("log_requests")
        if isinstance(value, list):
            candidates = value
    for item in candidates:
        if not isinstance(item, dict):
            continue
        rid = _as_str(_first_key(item, ["request_id", "requestId", "id"])).strip()
        if not rid and isinstance(item.get("log_request"), dict):
            rid = _as_str(_first_key(item["log_request"], ["request_id", "requestId", "id"])).strip()
        if rid == request_id:
            return item
    return None


def _logs_get_status(info_payload: dict[str, Any]) -> str:
    src: dict[str, Any] = info_payload
    if isinstance(info_payload.get("log_request"), dict):
        src = info_payload["log_request"]
    status = _first_key(src, ["status", "state"])
    return _as_str(status).strip().lower()


def _logs_get_part_numbers(info_payload: dict[str, Any]) -> list[int]:
    src: dict[str, Any] = info_payload
    if isinstance(info_payload.get("log_request"), dict):
        src = info_payload["log_request"]
    parts = _first_key(src, ["parts", "part", "files"])
    if not isinstance(parts, list):
        return []
    out: list[int] = []
    for part in parts:
        if isinstance(part, dict):
            num = _first_key(part, ["part_number", "partNumber", "number"])
        else:
            num = part
        try:
            out.append(int(num))
        except Exception:
            continue
    return sorted(set(out))


def _logs_download_rows(
    ctx: Any,
    *,
    counter_id: str,
    request_id: str,
    part_numbers: list[int],
    max_rows: int,
    delimiter: str | None = None,
    columns: list[str] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    rows: list[dict[str, str]] = []
    downloaded_parts: list[int] = []
    resolved_columns: list[str] | None = columns[:] if columns else None

    for part_number in part_numbers:
        payload = ctx._metrica_logs_call(  # type: ignore[attr-defined]
            "download",
            {"counterId": counter_id, "requestId": request_id, "partNumber": part_number},
            None,
        )
        raw, cols = _extract_raw_and_columns(payload)
        if cols and not resolved_columns:
            resolved_columns = [str(x) for x in cols]
        part_rows, part_cols = _parse_delimited(
            raw,
            delimiter=delimiter,
            columns=resolved_columns,
            max_rows=max(0, max_rows - len(rows)),
        )
        if not resolved_columns and part_cols:
            resolved_columns = part_cols
        rows.extend(part_rows)
        downloaded_parts.append(part_number)
        if len(rows) >= max_rows:
            break

    return rows, {"rows": len(rows), "downloaded_parts": downloaded_parts, "columns": resolved_columns or []}


def _extract_yclid_from_url(value: Any) -> str | None:
    url = _as_str(value).strip()
    if not url:
        return None
    try:
        parts = urlsplit(url)
        query = parse_qs(parts.query or "")
        yclid = query.get("yclid", [])
        if yclid:
            candidate = _as_str(yclid[0]).strip()
            return candidate or None
        return None
    except Exception:
        return None


def handle(tool: str, ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    ensure_hf_enabled(ctx.config)

    if tool == "join.hf.direct_vs_metrica_by_utm":
        campaign_id = args.get("campaign_id")
        campaign_name = args.get("campaign_name")
        utm_campaign = args.get("utm_campaign")
        counter_id = args.get("counter_id")
        date_from = args.get("date_from")
        date_to = args.get("date_to")
        if (campaign_id is None and not campaign_name) or not counter_id or not date_from or not date_to:
            raise HFError("campaign_id (or campaign_name), counter_id, date_from, date_to are required")

        resolved_campaign_id: int | None = None
        if campaign_id is not None:
            try:
                resolved_campaign_id = int(campaign_id)
            except Exception as exc:
                raise HFError("campaign_id must be an integer") from exc

        if not utm_campaign:
            if campaign_name:
                utm_campaign = str(campaign_name)
            elif resolved_campaign_id is not None:
                campaigns = ctx._direct_get(  # type: ignore[attr-defined]
                    "campaigns",
                    {"SelectionCriteria": {"Ids": [resolved_campaign_id]}, "FieldNames": ["Id", "Name"]},
                )
                items = campaigns.get("result", {}).get("Campaigns") if isinstance(campaigns, dict) else None
                if isinstance(items, list) and items and isinstance(items[0], dict):
                    utm_campaign = _as_str(items[0].get("Name")).strip() or None

        if not utm_campaign:
            raise HFError("Could not resolve utm_campaign; pass utm_campaign explicitly.")
        if resolved_campaign_id is None:
            raise HFError("campaign_id is required for Direct report join.")

        direct = ctx._direct_report(  # type: ignore[attr-defined]
            _direct_campaign_performance_params(
                campaign_id=resolved_campaign_id,
                date_from=str(date_from),
                date_to=str(date_to),
            )
        )
        direct_raw, direct_columns = _extract_raw_and_columns(direct)
        direct_rows, _ = _parse_delimited(direct_raw, delimiter="\t", columns=direct_columns)
        direct_by_date: dict[str, dict[str, float]] = {}
        for row in direct_rows:
            date = _normalize_key(row.get("Date"))
            if not date:
                continue
            try:
                direct_by_date[date] = {
                    "impressions": float(row.get("Impressions") or 0),
                    "clicks": float(row.get("Clicks") or 0),
                    "cost": float(row.get("Cost") or 0),
                }
            except Exception:
                continue

        metrica = ctx._metrica_get_stats(  # type: ignore[attr-defined]
            {
                "ids": str(counter_id),
                "metrics": "ym:s:visits",
                "dimensions": "ym:s:date",
                "date1": date_from,
                "date2": date_to,
                "filters": f"ym:s:UTMCampaign=={_metrica_filter_quote(str(utm_campaign))}",
                "sort": "ym:s:date",
                "limit": 100000,
            }
        )
        visits_by_date = _extract_metrica_time_series(metrica)

        all_dates = sorted(set(direct_by_date.keys()) | set(visits_by_date.keys()))
        joined = []
        totals = {"impressions": 0.0, "clicks": 0.0, "cost": 0.0, "visits": 0.0}
        for date in all_dates:
            d = direct_by_date.get(date) or {"impressions": 0.0, "clicks": 0.0, "cost": 0.0}
            v = float(visits_by_date.get(date) or 0.0)
            joined.append({"date": date, **d, "visits": v})
            totals["impressions"] += float(d["impressions"])
            totals["clicks"] += float(d["clicks"])
            totals["cost"] += float(d["cost"])
            totals["visits"] += v

        return hf_payload(
            tool=tool,
            status="ok",
            result={
                "utm_campaign": utm_campaign,
                "campaign_id": resolved_campaign_id,
                "counter_id": str(counter_id),
                "joined_by_date": joined,
                "totals": totals,
                "raw": {"direct_report": direct, "metrica_report": metrica},
            },
        )

    if tool == "join.hf.direct_vs_metrica_by_yclid":
        counter_id = args.get("counter_id")
        date_from = args.get("date_from")
        date_to = args.get("date_to")
        if not counter_id or not date_from or not date_to:
            raise HFError("counter_id, date_from, date_to are required")

        request_id = _as_str(args.get("request_id")).strip() or None
        max_wait_seconds = float(args.get("max_wait_seconds") or 60)
        poll_interval_seconds = float(args.get("poll_interval_seconds") or 2)
        max_rows = int(args.get("max_rows") or 20000)
        cleanup = bool(args.get("cleanup") if args.get("cleanup") is not None else True)

        logs_source = _as_str(args.get("logs_source")).strip() or "visits"
        # Some counters/sources do not expose `ym:s:yclid` as a Logs API field.
        # Default to `startURL` and a Direct attribution field, and extract yclid from query params as a fallback.
        # For many counters, `ym:s:lastDirectClickBanner` is the most practical join key (maps to Direct Ad Id).
        logs_fields = _as_str(args.get("logs_fields")).strip() or "ym:s:dateTime,ym:s:startURL,ym:s:lastDirectClickBanner"
        logs_delimiter = _as_str(args.get("logs_delimiter")).strip() or None
        yclid_field = _as_str(args.get("yclid_field")).strip() or "ym:s:yclid"
        start_url_field = _as_str(args.get("start_url_field")).strip() or "ym:s:startURL"
        banner_field = _as_str(args.get("banner_field")).strip() or "ym:s:lastDirectClickBanner"

        direct_report_type = _as_str(args.get("direct_report_type")).strip() or "CUSTOM_REPORT"
        direct_field_names = args.get("direct_field_names")
        if not isinstance(direct_field_names, list) or not direct_field_names:
            direct_field_names = ["Date", "CampaignId", "ClickId"]
        direct_click_id_field = _as_str(args.get("direct_click_id_field")).strip() or "ClickId"
        direct_campaign_id_field = _as_str(args.get("direct_campaign_id_field")).strip() or "CampaignId"
        direct_max_rows = int(args.get("direct_max_rows") or 200000)

        if not request_id:
            create_payload = ctx._metrica_logs_call(  # type: ignore[attr-defined]
                "create",
                {"counterId": str(counter_id)},
                {
                    "date1": str(date_from),
                    "date2": str(date_to),
                    "source": logs_source,
                    "fields": logs_fields,
                },
            )
            request_id = _logs_extract_request_id(create_payload)

        started = time.monotonic()
        info_payload: dict[str, Any] | None = None
        status = ""
        while True:
            try:
                info_payload = ctx._metrica_logs_call(  # type: ignore[attr-defined]
                    "info",
                    {"counterId": str(counter_id), "requestId": request_id},
                    None,
                )
            except Exception:
                allinfo_payload = ctx._metrica_logs_call(  # type: ignore[attr-defined]
                    "allinfo",
                    {"counterId": str(counter_id)},
                    None,
                )
                info_payload = _logs_find_request_info(allinfo_payload, request_id) or {}

            status = _logs_get_status(info_payload or {})
            if status in {"processed", "completed", "done", "ready"}:
                break
            if status in {"canceled", "cancelled", "failed", "error"}:
                raise HFError(f"Logs export status={status}. payload={info_payload}")
            if time.monotonic() - started >= max_wait_seconds:
                return hf_payload(
                    tool=tool,
                    status="ok",
                    result={
                        "status": "pending",
                        "note": "Logs export is not ready yet. Retry the same tool call with request_id.",
                        "request_id": request_id,
                        "last_status": status or "unknown",
                        "counter_id": str(counter_id),
                    },
                )
            time.sleep(max(0.2, poll_interval_seconds))

        part_numbers = _logs_get_part_numbers(info_payload or {}) or [0]
        logs_rows: list[dict[str, str]] = []
        logs_meta: dict[str, Any] = {}
        try:
            logs_rows, logs_meta = _logs_download_rows(
                ctx,
                counter_id=str(counter_id),
                request_id=request_id,
                part_numbers=part_numbers,
                max_rows=max_rows,
                delimiter=logs_delimiter,
                columns=None,
            )
        finally:
            if cleanup:
                try:
                    ctx._metrica_logs_call(  # type: ignore[attr-defined]
                        "clean",
                        {"counterId": str(counter_id), "requestId": request_id},
                        None,
                    )
                except Exception:
                    pass

        if not logs_rows:
            return hf_payload(
                tool=tool,
                status="ok",
                result={"status": "ok", "note": "Logs export downloaded but no rows were parsed.", "request_id": request_id, "logs": logs_meta},
            )

        # Try click-id join first (may be unsupported in some accounts/report types).
        direct_report: dict[str, Any] | None = None
        direct_meta: dict[str, Any] | None = None
        click_index: dict[str, str] = {}
        click_index_error: str | None = None
        try:
            direct_report = ctx._direct_report(  # type: ignore[attr-defined]
                _direct_clickid_report_params(
                    date_from=str(date_from),
                    date_to=str(date_to),
                    report_type=direct_report_type,
                    field_names=[str(x) for x in direct_field_names],
                    report_name=f"HF_join_clickid_{date_from}_{date_to}",
                )
            )
            click_index, direct_meta = _build_clickid_index(
                direct_report,
                click_id_field=direct_click_id_field,
                campaign_id_field=direct_campaign_id_field,
                max_rows=direct_max_rows,
            )
        except Exception as exc:
            click_index_error = f"{exc.__class__.__name__}: {exc}"
            click_index = {}
            direct_meta = None

        if click_index:
            matched = 0
            skipped_no_yclid = 0
            unmatched = 0
            by_campaign: dict[str, int] = {}
            sample_matches: list[dict[str, Any]] = []
            for row in logs_rows:
                yclid = _normalize_key(row.get(yclid_field))
                if not yclid:
                    yclid = _extract_yclid_from_url(row.get(start_url_field)) or ""
                if not yclid:
                    skipped_no_yclid += 1
                    continue
                campaign = click_index.get(yclid)
                if not campaign:
                    unmatched += 1
                    continue
                matched += 1
                by_campaign[campaign] = by_campaign.get(campaign, 0) + 1
                if len(sample_matches) < 10:
                    sample_matches.append(
                        {
                            "yclid": yclid,
                            "campaign_id": campaign,
                            "dateTime": row.get("ym:s:dateTime"),
                            "startURL": row.get(start_url_field),
                        }
                    )

            summary = [
                {"campaign_id": cid, "visits": visits}
                for cid, visits in sorted(by_campaign.items(), key=lambda x: (-x[1], x[0]))
            ]

            return hf_payload(
                tool=tool,
                status="ok",
                result={
                    "status": "ok",
                    "join_mode": "click_id",
                    "request_id": request_id,
                    "logs": {"status": status, **logs_meta, "skipped_no_yclid": skipped_no_yclid},
                    "direct": direct_meta,
                    "join": {
                        "matched_visits": matched,
                        "unmatched_visits": unmatched,
                        "by_campaign": summary,
                        "sample_matches": sample_matches,
                    },
                    "raw": {"direct_report": direct_report},
                },
            )

        # Fallback: join by Direct banner id from Metrica (lastDirectClickBanner) → Direct ads.get (Id → CampaignId).
        banner_counts: dict[str, int] = {}
        skipped_no_banner = 0
        for row in logs_rows:
            banner = _normalize_key(row.get(banner_field))
            if not banner:
                skipped_no_banner += 1
                continue
            banner_counts[banner] = banner_counts.get(banner, 0) + 1

        if not banner_counts:
            raise HFError(
                "No join keys found in logs rows. Provide logs_fields with a Direct attribution field "
                "(e.g., ym:s:lastDirectClickBanner) or configure a Direct click id report."
            )

        banner_ids: list[int] = []
        for key in sorted(banner_counts.keys(), key=lambda k: (-banner_counts[k], k))[:1000]:
            try:
                banner_ids.append(int(key))
            except Exception:
                continue

        direct_ads = ctx._direct_get(  # type: ignore[attr-defined]
            "ads",
            {"SelectionCriteria": {"Ids": banner_ids}, "FieldNames": ["Id", "CampaignId"]},
        )
        ads_items = direct_ads.get("result", {}).get("Ads") if isinstance(direct_ads, dict) else None
        banner_to_campaign: dict[str, str] = {}
        if isinstance(ads_items, list):
            for item in ads_items:
                if not isinstance(item, dict):
                    continue
                bid = item.get("Id")
                cid = item.get("CampaignId")
                if bid is None or cid is None:
                    continue
                banner_to_campaign[str(bid)] = str(cid)

        by_campaign: dict[str, int] = {}
        unmatched = 0
        for bid, count in banner_counts.items():
            cid = banner_to_campaign.get(bid)
            if not cid:
                unmatched += int(count)
                continue
            by_campaign[cid] = by_campaign.get(cid, 0) + int(count)

        summary = [
            {"campaign_id": cid, "visits": visits}
            for cid, visits in sorted(by_campaign.items(), key=lambda x: (-x[1], x[0]))
        ]

        return hf_payload(
            tool=tool,
            status="ok",
            result={
                "status": "ok",
                "join_mode": "banner_id",
                "note": "Direct click id report was not available; used Metrica lastDirectClickBanner → Direct ads.get mapping.",
                "request_id": request_id,
                "logs": {"status": status, **logs_meta, "skipped_no_banner": skipped_no_banner},
                "direct": {
                    "ads_fetched": len(banner_ids),
                    "ads_matched": len(banner_to_campaign),
                    "click_index_error": click_index_error,
                },
                "join": {
                    "matched_visits": sum(by_campaign.values()),
                    "unmatched_visits": unmatched,
                    "by_campaign": summary,
                },
                "raw": {"direct_ads": direct_ads},
            },
        )

    raise HFError(f"Unknown HF join tool: {tool}")
