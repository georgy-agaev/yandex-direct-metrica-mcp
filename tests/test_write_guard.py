import pytest

from mcp_yandex_ad.config import AppConfig
from mcp_yandex_ad.server import _enforce_write_guard


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


def test_write_guard_blocks_when_disabled():
    config = _config(write_enabled=False, use_sandbox=True)
    with pytest.raises(Exception, match="Write operations are disabled"):
        _enforce_write_guard(config, "direct.create_campaigns")


def test_write_guard_blocks_when_not_sandbox():
    config = _config(write_enabled=True, write_sandbox_only=True, use_sandbox=False)
    with pytest.raises(Exception, match="allowed only in sandbox"):
        _enforce_write_guard(config, "direct.update_ads")


def test_write_guard_allows_when_enabled_and_sandbox():
    config = _config(write_enabled=True, write_sandbox_only=True, use_sandbox=True)
    _enforce_write_guard(config, "direct.create_keywords")


def test_write_guard_ignores_read_tool():
    config = _config(write_enabled=False, use_sandbox=False)
    _enforce_write_guard(config, "direct.list_campaigns")


def test_write_guard_treats_raw_call_non_get_as_write():
    config = _config(write_enabled=False, use_sandbox=True)
    with pytest.raises(Exception, match="Write operations are disabled"):
        _enforce_write_guard(config, "direct.raw_call", {"resource": "sitelinks", "method": "add"})


def test_write_guard_allows_raw_call_get():
    config = _config(write_enabled=False, use_sandbox=False)
    _enforce_write_guard(config, "direct.raw_call", {"resource": "campaigns", "method": "get"})
