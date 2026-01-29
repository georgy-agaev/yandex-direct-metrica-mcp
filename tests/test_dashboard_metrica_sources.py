from mcp_yandex_ad.server import _dashboard_build_metrica_sources


def test_dashboard_build_metrica_sources_compact_series():
    all_days = ["2026-01-01", "2026-01-02"]
    report = {
        "data": [
            {
                "dimensions": [
                    {"name": "2026-01-01"},
                    {"id": "organic", "name": "Переходы из поисковых систем"},
                    {"id": "yandex", "name": "Яндекс"},
                ],
                "metrics": [10],
            },
            {
                "dimensions": [
                    {"name": "2026-01-01"},
                    {"id": "ad", "name": "Рекламные системы"},
                    {"id": "yandex_direct", "name": "Яндекс.Директ"},
                ],
                "metrics": [5],
            },
            {
                "dimensions": [
                    {"name": "2026-01-01"},
                    {"id": "social", "name": "Социальные сети"},
                    {"id": "vk", "name": "ВКонтакте"},
                ],
                "metrics": [3],
            },
            {
                "dimensions": [
                    {"name": "2026-01-01"},
                    {"id": "messenger", "name": "Мессенджеры"},
                    {"id": "tg", "name": "Telegram"},
                ],
                "metrics": [2],
            },
            {
                "dimensions": [
                    {"name": "2026-01-02"},
                    {"id": "direct", "name": "Прямые заходы"},
                    {"id": "direct", "name": "—"},
                ],
                "metrics": [4],
            },
        ]
    }

    out = _dashboard_build_metrica_sources(all_days=all_days, report=report, max_series=8)
    assert out["available"] is True
    assert out["attribution"] == "lastsign"
    assert isinstance(out["series"], list)

    keys = [s.get("key") for s in out["series"]]
    assert "organic" in keys
    assert "direct" in keys
    assert "other" in keys
    assert any(isinstance(k, str) and k.startswith("engine:") for k in keys)

    # Check that remainder is non-negative and does not exceed total.
    by_key = {s["key"]: s for s in out["series"] if isinstance(s, dict) and "key" in s}
    other_daily = by_key["other"]["daily"]
    assert all(float(r["visits"]) >= 0 for r in other_daily)
