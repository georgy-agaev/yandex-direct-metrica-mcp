from mcp_yandex_ad.config import load_config


def test_load_config_write_flags(monkeypatch):
    monkeypatch.setenv("MCP_WRITE_ENABLED", "true")
    monkeypatch.setenv("MCP_WRITE_SANDBOX_ONLY", "false")
    config = load_config()
    assert config.write_enabled is True
    assert config.write_sandbox_only is False


def test_load_config_direct_api_version(monkeypatch):
    config = load_config()
    assert config.direct_api_version == "v5"
    monkeypatch.setenv("YANDEX_DIRECT_API_VERSION", "v501")
    config = load_config()
    assert config.direct_api_version == "v501"
