import pytest

from mcp_yandex_ad import server


def test_dictionaries_requires_names():
    with pytest.raises(ValueError, match="dictionary_names is required"):
        server._build_dictionaries_params({})


def test_dictionaries_allows_params_override():
    params = server._build_dictionaries_params({"params": {"DictionaryNames": ["Currencies"]}})
    assert params == {"DictionaryNames": ["Currencies"]}


def test_changes_requires_timestamp():
    with pytest.raises(ValueError, match="timestamp is required"):
        server._build_changes_params({})


def test_changes_allows_params_override():
    params = server._build_changes_params({"params": {"Timestamp": "2024-01-01T00:00:00Z"}})
    assert params == {"Timestamp": "2024-01-01T00:00:00Z"}


def test_metrica_stats_requires_counter_id():
    with pytest.raises(ValueError, match="counter_id is required"):
        server._build_metrica_stats_params({})


def test_metrica_stats_requires_metrics():
    with pytest.raises(ValueError, match="metrics is required"):
        server._build_metrica_stats_params({"counter_id": "123"})


def test_metrica_stats_allows_params_override():
    params = server._build_metrica_stats_params({"params": {"ids": "123", "metrics": "ym:s:visits"}})
    assert params["ids"] == "123"


def test_direct_report_requires_fields():
    with pytest.raises(ValueError, match="field_names is required"):
        server._build_report_params({"report_type": "CUSTOM_REPORT"})


def test_direct_report_requires_type():
    with pytest.raises(ValueError, match="report_type is required"):
        server._build_report_params({"field_names": ["Date"]})


def test_direct_report_allows_params_override():
    params = server._build_report_params({"params": {"ReportType": "CUSTOM_REPORT"}})
    assert params["ReportType"] == "CUSTOM_REPORT"


def test_logs_export_requires_dates_for_create():
    with pytest.raises(ValueError, match="date_from and date_to are required"):
        server._build_logs_params({"action": "create", "counter_id": "1"})


def test_logs_export_requires_dates_for_evaluate():
    with pytest.raises(ValueError, match="date_from and date_to are required"):
        server._build_logs_params({"action": "evaluate", "counter_id": "1"})


def test_logs_export_requires_counter_id():
    with pytest.raises(ValueError, match="counter_id is required"):
        server._build_logs_params({"action": "allinfo"})


def test_logs_export_requires_fields_and_source():
    with pytest.raises(ValueError, match="Missing required logs_export params: fields, source"):
        server._build_logs_params(
            {
                "action": "create",
                "counter_id": "1",
                "date_from": "2024-01-01",
                "date_to": "2024-01-02",
            }
        )


def test_logs_export_requires_date_params_when_overridden():
    with pytest.raises(ValueError, match="Missing required logs_export params: date_from, date_to"):
        server._build_logs_params(
            {
                "action": "evaluate",
                "counter_id": "1",
                "params": {"fields": "ym:s:date", "source": "visits"},
            }
        )


def test_logs_export_allows_params_override():
    action, path_args, params = server._build_logs_params(
        {
            "action": "create",
            "counter_id": "1",
            "params": {
                "date1": "2024-01-01",
                "date2": "2024-01-02",
                "fields": "ym:s:date",
                "source": "visits",
            },
        }
    )
    assert action == "create"
    assert path_args["counterId"] == "1"
    assert params["source"] == "visits"


def test_direct_raw_call_requires_resource():
    with pytest.raises(ValueError, match="resource is required"):
        server._build_raw_direct_args({})


def test_direct_items_requires_items():
    with pytest.raises(ValueError, match="items is required"):
        server._build_items_params({}, key="Campaigns")


def test_direct_items_allows_params_override():
    params = server._build_items_params({"params": {"Campaigns": [{"Name": "Test"}]}}, key="Campaigns")
    assert params["Campaigns"][0]["Name"] == "Test"


def test_ids_selection_params_requires_ids():
    with pytest.raises(ValueError, match="Ids is required"):
        server._build_ids_selection_params({}, default_fields=["Id"])


def test_ids_selection_params_accepts_ids_arg():
    params = server._build_ids_selection_params({"ids": [1, 2]}, default_fields=["Id"])
    assert params["SelectionCriteria"]["Ids"] == [1, 2]


def test_ids_selection_params_accepts_selection_criteria_ids():
    params = server._build_ids_selection_params(
        {"selection_criteria": {"Ids": [10]}}, default_fields=["Id"]
    )
    assert params["SelectionCriteria"]["Ids"] == [10]


def test_normalize_ads_items_for_update_converts_adextensions_ids_to_calloutsetting():
    items = [
        {
            "Id": 1,
            "TextAd": {
                "Title": "x",
                "AdExtensions": {"AdExtensionIds": [111, 222]},
            },
        }
    ]
    normalized = server._normalize_ads_items_for_update(items)
    assert normalized[0]["TextAd"].get("AdExtensions") is None
    assert normalized[0]["TextAd"]["CalloutSetting"]["AdExtensions"] == [
        {"AdExtensionId": 111, "Operation": "SET"},
        {"AdExtensionId": 222, "Operation": "SET"},
    ]


def test_normalize_ads_items_for_update_converts_read_shape_list_to_calloutsetting():
    items = [
        {
            "Id": 1,
            "TextAd": {
                "Title": "x",
                "AdExtensions": [{"AdExtensionId": 111, "Type": "CALLOUT"}],
            },
        }
    ]
    normalized = server._normalize_ads_items_for_update(items)
    assert normalized[0]["TextAd"]["CalloutSetting"]["AdExtensions"] == [
        {"AdExtensionId": 111, "Operation": "SET"}
    ]


def test_normalize_ads_items_for_add_converts_calloutsetting_to_adextensions():
    items = [
        {
            "AdGroupId": 1,
            "TextAd": {
                "Title": "x",
                "CalloutSetting": {
                    "AdExtensions": [
                        {"AdExtensionId": 111, "Operation": "SET"},
                        {"AdExtensionId": 222, "Operation": "ADD"},
                    ]
                },
            },
        }
    ]
    normalized = server._normalize_ads_items_for_add(items)
    assert normalized[0]["TextAd"].get("CalloutSetting") is None
    assert normalized[0]["TextAd"]["AdExtensions"]["AdExtensionIds"] == [111, 222]


def test_normalize_ads_items_for_add_converts_read_shape_list_to_adextensions():
    items = [
        {
            "AdGroupId": 1,
            "TextAd": {
                "Title": "x",
                "AdExtensions": [{"AdExtensionId": 111, "Type": "CALLOUT"}],
            },
        }
    ]
    normalized = server._normalize_ads_items_for_add(items)
    assert normalized[0]["TextAd"]["AdExtensions"]["AdExtensionIds"] == [111]
