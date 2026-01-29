from mcp_yandex_ad.auth import TokenManager
from mcp_yandex_ad.config import AppConfig


def _base_config(**overrides):
    data = dict(
        access_token=None,
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


def test_get_access_token_uses_existing():
    config = _base_config(access_token="token")
    manager = TokenManager(config)
    assert manager.get_access_token() == "token"


def test_refresh_skips_without_credentials():
    config = _base_config(refresh_token="refresh")
    manager = TokenManager(config)
    assert manager.get_access_token() is None


def test_refresh_success(monkeypatch):
    config = _base_config(
        refresh_token="refresh",
        client_id="client",
        client_secret="secret",
    )

    class DummyResponse:
        def __init__(self):
            self._data = {"access_token": "new-token", "expires_in": 3600}

        def raise_for_status(self):
            return None

        def json(self):
            return self._data

    def fake_post(*args, **kwargs):
        return DummyResponse()

    monkeypatch.setattr("mcp_yandex_ad.auth.requests.post", fake_post)

    manager = TokenManager(config)
    assert manager.get_access_token() == "new-token"
