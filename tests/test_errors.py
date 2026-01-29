from requests import Response

from mcp_yandex_ad.errors import MissingClientError, WriteGuardError, normalize_error
from tapi_yandex_direct import exceptions as direct_exceptions
from tapi_yandex_metrika import exceptions as metrica_exceptions


def _response(url: str = "https://api.direct.yandex.com/json/v5/campaigns") -> Response:
    response = Response()
    response.status_code = 400
    response.reason = "Bad Request"
    response.url = url
    response.headers["X-Request-Id"] = "req-123"
    return response


def test_normalize_direct_token_error():
    message = {
        "error": {
            "error_code": 53,
            "request_id": "req-123",
            "error_string": "Invalid",
            "error_detail": "OAuth token is missing",
        }
    }
    exc = direct_exceptions.YandexDirectTokenError(_response(), message, client=object())
    payload = normalize_error("direct.list_campaigns", exc)["error"]
    assert payload["provider"] == "direct"
    assert payload["error_code"] == 53
    assert payload["request_id"] == "req-123"
    assert payload["hint"] == "Check access/refresh token and API permissions."


def test_normalize_metrica_limit_error():
    exc = metrica_exceptions.YandexMetrikaLimitError(
        _response("https://api-metrika.yandex.net/stat/v1/data"),
        message="Rate limit",
        code=429,
        errors=[{"error_type": "quota"}],
    )
    payload = normalize_error("metrica.report", exc)["error"]
    assert payload["provider"] == "metrica"
    assert payload["error_code"] == 429
    assert payload["hint"] == "Rate limit exceeded; retry with backoff."


def test_normalize_missing_client():
    exc = MissingClientError("direct", "Direct client not configured.")
    payload = normalize_error("direct.list_campaigns", exc)["error"]
    assert payload["provider"] == "direct"
    assert payload["hint"] == "Check access/refresh token and API permissions."


def test_normalize_write_guard():
    exc = WriteGuardError("direct", "Write operations are disabled.", "Enable write mode")
    payload = normalize_error("direct.create_campaigns", exc)["error"]
    assert payload["provider"] == "direct"
    assert payload["hint"] == "Enable write mode"
