from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp_yandex_ad.hf_join import handle


@dataclass(frozen=True)
class _Cfg:
    hf_enabled: bool = True


class _CtxUTM:
    config = _Cfg()

    def __init__(self, direct_report: dict[str, Any], metrica_report: dict[str, Any]) -> None:
        self._direct_report_payload = direct_report
        self._metrica_report_payload = metrica_report
        self.metrica_calls: list[dict[str, Any]] = []

    def _direct_report(self, params: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002
        return self._direct_report_payload

    def _metrica_get_stats(self, params: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002
        self.metrica_calls.append(params)
        return self._metrica_report_payload

    def _direct_get(self, resource: str, params: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002
        raise AssertionError("_direct_get should not be called in this test")


class _CtxYclid:
    config = _Cfg()

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []

    def _metrica_logs_call(self, action: str, path_args: dict[str, Any], params: dict[str, Any] | None) -> dict[str, Any]:
        self.calls.append((action, path_args, params))
        if action == "create":
            return {"request_id": "r1"}
        if action == "info":
            return {"status": "processed", "parts": [{"part_number": 0}]}
        if action == "download":
            return {
                "raw": (
                    "ym:s:dateTime\tym:s:yclid\tym:s:startURL\n"
                    "2026-01-01T00:00:00\tY1\thttp://example.test/\n"
                    "2026-01-01T00:01:00\t\thttp://example.test/\n"
                )
            }
        if action == "clean":
            return {"status": "ok"}
        raise AssertionError(f"Unexpected logs action: {action}")

    def _direct_report(self, params: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002
        return {
            "raw": (
                "Date\tCampaignId\tClickId\n"
                "2026-01-01\t123\tY1\n"
            ),
            "columns": ["Date", "CampaignId", "ClickId"],
        }

    def _direct_get(self, resource: str, params: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002
        raise AssertionError("_direct_get should not be called in click-id join tests")


def test_join_by_utm_produces_joined_series() -> None:
    ctx = _CtxUTM(
        direct_report={
            "raw": (
                "Date\tCampaignId\tImpressions\tClicks\tCost\n"
                "2026-01-01\t123\t10\t1\t100\n"
                "2026-01-02\t123\t20\t2\t200\n"
            ),
            "columns": ["Date", "CampaignId", "Impressions", "Clicks", "Cost"],
        },
        metrica_report={
            "data": [
                {"dimensions": [{"name": "2026-01-01"}], "metrics": [5]},
                {"dimensions": [{"name": "2026-01-02"}], "metrics": [7]},
            ]
        },
    )

    out = handle(
        "join.hf.direct_vs_metrica_by_utm",
        ctx,
        {
            "campaign_id": 123,
            "utm_campaign": "campaign-123",
            "counter_id": "42",
            "date_from": "2026-01-01",
            "date_to": "2026-01-02",
        },
    )

    assert out["status"] == "ok"
    result = out["result"]
    assert result["utm_campaign"] == "campaign-123"
    assert result["totals"]["visits"] == 12.0
    assert len(result["joined_by_date"]) == 2
    assert result["joined_by_date"][0]["date"] == "2026-01-01"
    assert result["joined_by_date"][0]["visits"] == 5.0


def test_join_by_utm_quotes_filters_when_value_contains_quote() -> None:
    ctx = _CtxUTM(
        direct_report={
            "raw": "Date\tCampaignId\tImpressions\tClicks\tCost\n2026-01-01\t123\t1\t1\t1\n",
            "columns": ["Date", "CampaignId", "Impressions", "Clicks", "Cost"],
        },
        metrica_report={"data": [{"dimensions": [{"name": "2026-01-01"}], "metrics": [1]}]},
    )

    out = handle(
        "join.hf.direct_vs_metrica_by_utm",
        ctx,
        {
            "campaign_id": 123,
            "utm_campaign": "Bob's campaign",
            "counter_id": "42",
            "date_from": "2026-01-01",
            "date_to": "2026-01-01",
        },
    )

    assert out["status"] == "ok"
    assert ctx.metrica_calls, "Expected metrica stats call"
    assert "ym:s:UTMCampaign==\"Bob's campaign\"" in (ctx.metrica_calls[0].get("filters") or "")


def test_join_by_yclid_joins_logs_with_direct_click_ids() -> None:
    ctx = _CtxYclid()

    out = handle(
        "join.hf.direct_vs_metrica_by_yclid",
        ctx,
        {
            "counter_id": "42",
            "date_from": "2026-01-01",
            "date_to": "2026-01-01",
            "max_wait_seconds": 1,
            "poll_interval_seconds": 0.01,
            "max_rows": 1000,
        },
    )

    assert out["status"] == "ok"
    result = out["result"]
    assert result["request_id"] == "r1"
    assert result["join"]["matched_visits"] == 1
    assert result["join"]["unmatched_visits"] == 0
    assert result["join"]["by_campaign"][0]["campaign_id"] == "123"
    assert result["join"]["by_campaign"][0]["visits"] == 1


def test_join_by_yclid_falls_back_to_parsing_start_url() -> None:
    class _Ctx(_CtxYclid):
        def _metrica_logs_call(self, action: str, path_args: dict[str, Any], params: dict[str, Any] | None) -> dict[str, Any]:
            self.calls.append((action, path_args, params))
            if action == "create":
                return {"request_id": "r1"}
            if action == "info":
                return {"status": "processed", "parts": [{"part_number": 0}]}
            if action == "download":
                return {
                    "raw": (
                        "ym:s:dateTime\tym:s:startURL\n"
                        "2026-01-01T00:00:00\thttp://example.test/?yclid=Y1\n"
                    )
                }
            if action == "clean":
                return {"status": "ok"}
            raise AssertionError(f"Unexpected logs action: {action}")

    ctx = _Ctx()

    out = handle(
        "join.hf.direct_vs_metrica_by_yclid",
        ctx,
        {
            "counter_id": "42",
            "date_from": "2026-01-01",
            "date_to": "2026-01-01",
            "max_wait_seconds": 1,
            "poll_interval_seconds": 0.01,
            "max_rows": 1000,
        },
    )

    assert out["status"] == "ok"
    result = out["result"]
    assert result["join"]["matched_visits"] == 1


def test_logs_extract_request_id_supports_log_request_shape() -> None:
    class _Ctx(_CtxYclid):
        def _metrica_logs_call(self, action: str, path_args: dict[str, Any], params: dict[str, Any] | None) -> dict[str, Any]:
            if action == "create":
                return {"log_request": {"request_id": 123}}
            if action == "info":
                return {"status": "processed", "parts": [{"part_number": 0}]}
            if action == "download":
                return {"raw": "ym:s:dateTime\tym:s:yclid\tym:s:startURL\n2026-01-01T00:00:00\tY1\thttp://example.test/\n"}
            if action == "clean":
                return {"status": "ok"}
            raise AssertionError(f"Unexpected logs action: {action}")

    ctx = _Ctx()
    out = handle(
        "join.hf.direct_vs_metrica_by_yclid",
        ctx,
        {"counter_id": "42", "date_from": "2026-01-01", "date_to": "2026-01-01", "max_wait_seconds": 1, "poll_interval_seconds": 0.01},
    )
    assert out["status"] == "ok"


def test_logs_info_shape_with_log_request_status_and_parts() -> None:
    class _Ctx(_CtxYclid):
        def _metrica_logs_call(self, action: str, path_args: dict[str, Any], params: dict[str, Any] | None) -> dict[str, Any]:
            if action == "create":
                return {"log_request": {"request_id": 123}}
            if action == "info":
                return {"log_request": {"status": "processed", "parts": [{"part_number": 0}]}}
            if action == "download":
                return {"raw": "ym:s:dateTime\tym:s:yclid\tym:s:startURL\n2026-01-01T00:00:00\tY1\thttp://example.test/\n"}
            if action == "clean":
                return {"status": "ok"}
            raise AssertionError(f"Unexpected logs action: {action}")

    ctx = _Ctx()
    out = handle(
        "join.hf.direct_vs_metrica_by_yclid",
        ctx,
        {"counter_id": "42", "date_from": "2026-01-01", "date_to": "2026-01-01", "max_wait_seconds": 1, "poll_interval_seconds": 0.01},
    )
    assert out["status"] == "ok"


def test_join_by_banner_id_fallback_maps_to_campaigns() -> None:
    class _Ctx:
        config = _Cfg()

        def _metrica_logs_call(self, action: str, path_args: dict[str, Any], params: dict[str, Any] | None) -> dict[str, Any]:  # noqa: ARG002
            if action == "create":
                return {"log_request": {"request_id": 1}}
            if action == "info":
                return {"log_request": {"status": "processed", "parts": [{"part_number": 0}]}}
            if action == "download":
                return {
                    "raw": (
                        "ym:s:dateTime\tym:s:startURL\tym:s:lastDirectClickBanner\n"
                        "2026-01-01T00:00:00\thttp://example.test/?yclid=X\t100\n"
                        "2026-01-01T00:01:00\thttp://example.test/\t100\n"
                        "2026-01-01T00:02:00\thttp://example.test/\t200\n"
                    )
                }
            if action == "clean":
                return {"status": "ok"}
            raise AssertionError(f"Unexpected logs action: {action}")

        def _direct_report(self, params: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002
            # Simulate Direct report field failure by raising.
            raise RuntimeError("Invalid request: invalid enumeration value")

        def _direct_get(self, resource: str, params: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002
            assert resource == "ads"
            return {
                "result": {
                    "Ads": [
                        {"Id": 100, "CampaignId": 10},
                        {"Id": 200, "CampaignId": 20},
                    ]
                }
            }

    ctx = _Ctx()
    out = handle(
        "join.hf.direct_vs_metrica_by_yclid",
        ctx,
        {"counter_id": "42", "date_from": "2026-01-01", "date_to": "2026-01-01", "max_wait_seconds": 1, "poll_interval_seconds": 0.01},
    )
    assert out["status"] == "ok"
    result = out["result"]
    assert result["join_mode"] == "banner_id"
    by_campaign = {x["campaign_id"]: x["visits"] for x in result["join"]["by_campaign"]}
    assert by_campaign == {"10": 2, "20": 1}
