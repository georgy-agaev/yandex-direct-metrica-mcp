from mcp_yandex_ad.server import _dashboard_build_metrica_goals


def test_dashboard_build_metrica_goals_daily_series():
    all_days = ["2026-01-01", "2026-01-02"]
    metrica_by_date = {
        "2026-01-01": {"goal_reaches": {"111": 2.0, "222": 1.0}},
        "2026-01-02": {"goal_reaches": {"111": 0.0, "222": 3.0}},
    }
    out = _dashboard_build_metrica_goals(
        all_days=all_days,
        goal_ids=["111", "222"],
        metrica_by_date=metrica_by_date,
        goal_names={"111": "Отправка формы", "222": "Клик по телефону"},
    )
    assert out["available"] is True
    assert out["goal_ids"] == ["111", "222"]
    assert len(out["goals"]) == 2
    g1 = next(g for g in out["goals"] if g["id"] == "111")
    assert g1["name"] == "Отправка формы"
    assert [x["reaches"] for x in g1["daily"]] == [2.0, 0.0]
