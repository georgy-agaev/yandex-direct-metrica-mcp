import pytest

from mcp_yandex_ad.config import AppConfig
from mcp_yandex_ad.tools import tool_definitions


def _config(**overrides):
    data = dict(
        access_token="token",
        refresh_token=None,
        client_id=None,
        client_secret=None,
        direct_client_login=None,
        direct_client_logins=[],
        direct_api_version="v5",
        metrica_counter_ids=[],
        use_sandbox=False,
        write_enabled=False,
        write_sandbox_only=True,
        hf_enabled=True,
        hf_write_enabled=False,
        hf_destructive_enabled=False,
        cache_enabled=True,
        cache_ttl_seconds=300,
        direct_rate_limit_rps=0,
        metrica_rate_limit_rps=0,
        retry_max_attempts=3,
        retry_base_delay_seconds=0.5,
        retry_max_delay_seconds=8.0,
        content_mode="json",
    )
    data.update(overrides)
    return AppConfig(**data)


def test_hf_tools_hidden_when_disabled():
    tools = tool_definitions(_config(hf_enabled=False))
    assert all(not t.name.startswith("direct.hf.") for t in tools)


def test_hf_destructive_tools_hidden_by_default():
    tools = tool_definitions(_config(hf_enabled=True, hf_destructive_enabled=False))
    names = {t.name for t in tools}
    assert "direct.hf.delete_ads" not in names
    assert "direct.hf.delete_keywords" not in names


def test_hf_destructive_tools_visible_when_enabled():
    tools = tool_definitions(_config(hf_enabled=True, hf_destructive_enabled=True))
    names = {t.name for t in tools}
    assert "direct.hf.delete_ads" in names
    assert "direct.hf.delete_keywords" in names
