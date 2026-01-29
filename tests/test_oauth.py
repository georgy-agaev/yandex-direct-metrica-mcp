import pytest

from mcp_yandex_ad.oauth import build_authorize_url


def test_build_authorize_url_minimal():
    url = build_authorize_url(client_id="cid", redirect_uri=None, scopes=None)
    assert "client_id=cid" in url
    assert "response_type=code" in url


def test_build_authorize_url_with_scopes_and_redirect():
    url = build_authorize_url(
        client_id="cid",
        redirect_uri="https://oauth.yandex.ru/verification_code",
        scopes=["direct:api", "metrika:read"],
    )
    assert "redirect_uri=" in url
    assert "scope=" in url
    assert "direct%3Aapi" in url
    assert "metrika%3Aread" in url

