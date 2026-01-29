"""Direct API v501 support for tapi-yandex-direct.

The upstream `tapi-yandex-direct` library hardcodes v5 resource paths in its
resource mapping. For v501-only features (for example, Unified campaigns), we
only need to switch endpoints from `/json/v5/*` to `/json/v501/*`.

We intentionally keep this adapter minimal to avoid diverging from the upstream
request/response logic.
"""

from __future__ import annotations

from tapi2 import generate_wrapper_from_adapter
from tapi_yandex_direct.resource_mapping import RESOURCE_MAPPING_V5
from tapi_yandex_direct.tapi_yandex_direct import YandexDirectClientAdapter


def _upgrade_resource_mapping(mapping: dict) -> dict:
    upgraded: dict = {}
    for key, value in mapping.items():
        resource = value.get("resource")
        if isinstance(resource, str) and "json/v5/" in resource:
            resource = resource.replace("json/v5/", "json/v501/")
        upgraded[key] = {**value, "resource": resource}
    return upgraded


RESOURCE_MAPPING_V501 = _upgrade_resource_mapping(RESOURCE_MAPPING_V5)


class YandexDirectClientAdapterV501(YandexDirectClientAdapter):
    resource_mapping = RESOURCE_MAPPING_V501


YandexDirectV501 = generate_wrapper_from_adapter(YandexDirectClientAdapterV501)

