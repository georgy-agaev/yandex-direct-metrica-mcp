"""Error normalization for Yandex Direct + Metrica."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from tapi_yandex_direct import exceptions as direct_exceptions
from tapi_yandex_metrika import exceptions as metrica_exceptions

HINT_RATE_LIMIT = "Rate limit exceeded; retry with backoff."
HINT_TOKEN = "Check access/refresh token and API permissions."
HINT_UNITS = "Not enough units; retry later or reduce scope."
HINT_REPORT = "Report not ready; retry later."
HINT_PARAMS = "Check required parameters."


class MissingClientError(RuntimeError):
    def __init__(self, provider: str, message: str) -> None:
        super().__init__(message)
        self.provider = provider


class WriteGuardError(RuntimeError):
    def __init__(self, provider: str, message: str, hint: str) -> None:
        super().__init__(message)
        self.provider = provider
        self.hint = hint


def _safe_message(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=True)
    return str(value)


def _sanitize_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _extract_http_info(exc: Exception) -> dict[str, Any]:
    response = getattr(exc, "response", None)
    if response is None:
        return {}

    info: dict[str, Any] = {}
    status_code = getattr(response, "status_code", None)
    reason = getattr(response, "reason", None)
    endpoint = _sanitize_url(getattr(response, "url", None))

    if status_code is not None:
        info["http_status"] = status_code
    if reason:
        info["http_reason"] = reason
    if endpoint:
        info["endpoint"] = endpoint

    headers = getattr(response, "headers", None)
    if headers:
        request_id = headers.get("X-Request-Id") or headers.get("X-Request-ID")
        if request_id:
            info["request_id"] = request_id

    return info


def normalize_error(tool: str, exc: Exception) -> dict[str, Any]:
    payload: dict[str, Any] = {"tool": tool, "type": exc.__class__.__name__}
    payload.update(_extract_http_info(exc))

    if isinstance(exc, MissingClientError):
        payload["provider"] = exc.provider
        payload["message"] = str(exc)
        payload["hint"] = HINT_TOKEN
    elif isinstance(exc, WriteGuardError):
        payload["provider"] = exc.provider
        payload["message"] = str(exc)
        payload["hint"] = exc.hint
    elif isinstance(exc, direct_exceptions.YandexDirectClientError):
        payload["provider"] = "direct"
        payload["error_code"] = exc.error_code
        payload["request_id"] = exc.request_id
        payload["message"] = exc.error_string
        payload["detail"] = exc.error_detail
        if isinstance(exc, direct_exceptions.YandexDirectTokenError):
            payload["hint"] = HINT_TOKEN
        elif isinstance(exc, direct_exceptions.YandexDirectRequestsLimitError):
            payload["hint"] = HINT_RATE_LIMIT
        elif isinstance(exc, direct_exceptions.YandexDirectNotEnoughUnitsError):
            payload["hint"] = HINT_UNITS
    elif isinstance(exc, direct_exceptions.YandexDirectApiError):
        payload["provider"] = "direct"
        payload["message"] = _safe_message(getattr(exc, "data", None)) or "Direct API error"
    elif isinstance(exc, metrica_exceptions.YandexMetrikaClientError):
        payload["provider"] = "metrica"
        payload["error_code"] = exc.code
        payload["message"] = exc.message or "Metrica API error"
        if exc.errors:
            payload["details"] = exc.errors
        if isinstance(exc, metrica_exceptions.YandexMetrikaTokenError):
            payload["hint"] = HINT_TOKEN
        elif isinstance(exc, metrica_exceptions.YandexMetrikaLimitError):
            payload["hint"] = HINT_RATE_LIMIT
        elif isinstance(exc, metrica_exceptions.YandexMetrikaDownloadReportError):
            payload["hint"] = HINT_REPORT
    elif isinstance(exc, metrica_exceptions.YandexMetrikaApiError):
        payload["provider"] = "metrica"
        payload["message"] = exc.message or "Metrica API error"
    elif isinstance(exc, ValueError):
        payload["message"] = str(exc)
        payload["hint"] = HINT_PARAMS
    else:
        payload["message"] = str(exc)

    return {"error": payload}
