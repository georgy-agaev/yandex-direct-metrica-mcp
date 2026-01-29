"""Client wrappers for Yandex Direct and Metrica."""

from dataclasses import dataclass
import logging

from .config import AppConfig

logger = logging.getLogger("yandex-direct-metrica-mcp")

try:
    from tapi_yandex_direct import YandexDirect
    from tapi_yandex_metrika import (
        YandexMetrikaLogsapi,
        YandexMetrikaManagement,
        YandexMetrikaStats,
    )
    from .direct_v501 import YandexDirectV501
except ImportError as exc:  # pragma: no cover - runtime dependency
    YandexDirect = None
    YandexDirectV501 = None
    YandexMetrikaLogsapi = None
    YandexMetrikaManagement = None
    YandexMetrikaStats = None
    logger.debug("Optional dependency missing: %s", exc)


@dataclass
class YandexClients:
    direct: object | None
    metrica_management: object | None
    metrica_stats: object | None
    metrica_logs: object | None


def build_direct_client(
    config: AppConfig,
    access_token: str | None,
    *,
    direct_client_login: str | None = None,
) -> object | None:
    if not access_token or not YandexDirect:
        return None

    direct_class = YandexDirect
    if config.direct_api_version == "v501":
        if YandexDirectV501 is None:
            logger.warning("Direct v501 requested but dependency missing; using v5.")
        else:
            direct_class = YandexDirectV501

    login = (direct_client_login or config.direct_client_login or None)
    return direct_class(
        access_token=access_token,
        login=login,
        is_sandbox=config.use_sandbox,
        retry_if_exceeded_limit=True,
        retries_if_server_error=5,
    )


def build_clients(config: AppConfig, access_token: str | None) -> YandexClients:
    if not access_token:
        return YandexClients(
            direct=None, metrica_management=None, metrica_stats=None, metrica_logs=None
        )

    direct_client = build_direct_client(config, access_token)

    metrica_management = None
    metrica_stats = None
    metrica_logs = None
    if YandexMetrikaManagement and YandexMetrikaStats and YandexMetrikaLogsapi:
        metrica_management = YandexMetrikaManagement(access_token=access_token)
        metrica_stats = YandexMetrikaStats(access_token=access_token)
        metrica_logs = YandexMetrikaLogsapi(access_token=access_token)

    return YandexClients(
        direct=direct_client,
        metrica_management=metrica_management,
        metrica_stats=metrica_stats,
        metrica_logs=metrica_logs,
    )
