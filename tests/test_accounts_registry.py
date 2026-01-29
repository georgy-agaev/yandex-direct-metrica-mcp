import json

from mcp_yandex_ad.config import load_config
from mcp_yandex_ad.tools import tool_definitions


def test_load_config_accounts_registry(monkeypatch, tmp_path):
    registry_path = tmp_path / "accounts.json"
    registry_path.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "id": "proj1",
                        "name": "Project 1",
                        "direct_client_login": "elama-123",
                        "metrica_counter_ids": ["1"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("MCP_ACCOUNTS_FILE", str(registry_path))
    config = load_config()
    assert "proj1" in config.accounts
    assert config.accounts["proj1"].direct_client_login == "elama-123"
    assert config.accounts["proj1"].metrica_counter_ids == ["1"]


def test_tool_schemas_include_account_id(monkeypatch, tmp_path):
    registry_path = tmp_path / "accounts.json"
    registry_path.write_text(
        json.dumps(
            {
                "accounts": [
                    {"id": "proj1", "direct_client_login": "elama-123"},
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("MCP_ACCOUNTS_FILE", str(registry_path))
    monkeypatch.setenv("YANDEX_DIRECT_CLIENT_LOGINS", "elama-123")
    config = load_config()
    tools = {tool.name: tool for tool in tool_definitions(config)}

    direct_schema = tools["direct.list_campaigns"].inputSchema
    direct_account_id = direct_schema["properties"]["account_id"]
    assert "anyOf" in direct_account_id
    assert direct_account_id["anyOf"][0]["enum"] == ["proj1"]
    assert "direct_client_login" in direct_schema["properties"]

    metrica_schema = tools["metrica.list_counters"].inputSchema
    metrica_account_id = metrica_schema["properties"]["account_id"]
    assert "anyOf" in metrica_account_id
    assert metrica_account_id["anyOf"][0]["enum"] == ["proj1"]
    assert "direct_client_login" not in metrica_schema["properties"]

    dashboard_schema = tools["dashboard.generate_option1"].inputSchema
    dashboard_account_id = dashboard_schema["properties"]["account_id"]
    assert "anyOf" in dashboard_account_id
    assert dashboard_account_id["anyOf"][0]["enum"] == ["proj1"]
    assert "direct_client_login" in dashboard_schema["properties"]
    assert "return_data" in dashboard_schema["properties"]
