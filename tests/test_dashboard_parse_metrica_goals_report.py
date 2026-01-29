from mcp_yandex_ad.server import _dashboard_parse_metrica_goals_report


def test_parse_metrica_goals_report_date_goal():
    report = {
        "data": [
            {
                "dimensions": [{"name": "2026-01-01"}, {"id": "111", "name": "Отправка формы"}],
                "metrics": [3],
            },
            {
                "dimensions": [{"name": "2026-01-01"}, {"id": "222", "name": "Клик по телефону"}],
                "metrics": [1],
            },
            # same day, same goal multiple rows should sum
            {
                "dimensions": [{"name": "2026-01-01"}, {"id": "111", "name": "Отправка формы"}],
                "metrics": [2],
            },
        ]
    }
    names, by_date = _dashboard_parse_metrica_goals_report(report)
    assert names["111"] == "Отправка формы"
    assert names["222"] == "Клик по телефону"
    assert by_date["2026-01-01"]["111"] == 5.0
    assert by_date["2026-01-01"]["222"] == 1.0
