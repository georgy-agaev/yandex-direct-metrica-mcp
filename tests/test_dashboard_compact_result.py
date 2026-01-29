from mcp_yandex_ad.server import _dashboard_build_compact_result


def test_dashboard_compact_result_extracts_totals():
    data = {
        "meta": {"date_from": "2026-01-01", "date_to": "2026-01-02"},
        "direct": {
            "current": {"totals": {"impressions": 10, "clicks": 2, "cost_rub": 100.0, "ctr": 20.0, "cpc": 50.0}},
            "prev": {"totals": {"impressions": 8, "clicks": 1, "cost_rub": 60.0, "ctr": 12.5, "cpc": 60.0}},
        },
        "metrica": {
            "current": {
                "totals": {
                    "visits": 5,
                    "users": 4,
                    "bounce_rate": 10.0,
                    "page_depth": 1.5,
                    "avg_visit_duration_seconds": 42.0,
                    "engaged": 4.5,
                    "leads": 1.0,
                }
            },
            "prev": {
                "totals": {
                    "visits": 3,
                    "users": 3,
                    "bounce_rate": 20.0,
                    "page_depth": 1.2,
                    "avg_visit_duration_seconds": 30.0,
                    "engaged": 2.4,
                    "leads": 0.0,
                }
            },
        },
    }

    out = _dashboard_build_compact_result(data, warnings=[], coverage={"ok": True})
    assert out["summary"]["direct"]["current"]["total_impressions"] == 10
    assert out["summary"]["direct"]["current"]["ctr_pct"] == 20.0
    assert out["summary"]["metrica"]["current"]["total_visits"] == 5
    assert out["summary"]["metrica"]["current"]["avg_duration_seconds"] == 42.0
    assert out["meta"]["date_to"] == "2026-01-02"
