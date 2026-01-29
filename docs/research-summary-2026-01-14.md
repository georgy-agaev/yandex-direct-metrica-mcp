# Yandex Direct repos with create/update support (verified locally)

## biplane/yandex-direct (PHP)
- Campaigns add/update: yandex.ad/repos/yandex-direct/src/Api/V5/Campaigns.php
- AdGroups add/update: yandex.ad/repos/yandex-direct/src/Api/V5/AdGroups.php
- Ads add/update: yandex.ad/repos/yandex-direct/src/Api/V5/Ads.php
- Keywords add/update: yandex.ad/repos/yandex-direct/src/Api/V5/Keywords.php

## sitkoru/yandex-direct-api (PHP)
- CampaignsService add/update: yandex.ad/repos/yandex-direct-api/src/services/campaigns/CampaignsService.php
- AdGroupsService add/update: yandex.ad/repos/yandex-direct-api/src/services/adgroups/AdGroupsService.php
- AdsService add/update: yandex.ad/repos/yandex-direct-api/src/services/ads/AdsService.php
- KeywordsService add/update: yandex.ad/repos/yandex-direct-api/src/services/keywords/KeywordsService.php

## gladyshev/yandex-direct-client (PHP)
- Campaigns add/update: yandex.ad/repos/yandex-direct-client/src/Service/Campaigns.php
- AdGroups add/update: yandex.ad/repos/yandex-direct-client/src/Service/AdGroups.php
- Ads add/update: yandex.ad/repos/yandex-direct-client/src/Service/Ads.php
- Keywords add/update: yandex.ad/repos/yandex-direct-client/src/Service/Keywords.php

## perf2k2/direct (PHP)
- README явно перечисляет add/update для Campaigns/AdGroups/Ads/Keywords: yandex.ad/repos/direct/README.md
- Примеры в тестах: yandex.ad/repos/direct/tests/integration/KeywordsTest.php, yandex.ad/repos/direct/tests/integration/AdsTest.php

## pavelmaksimov/tapi-yandex-direct (Python)
- Универсальная поддержка методов add/update через mapping: yandex.ad/repos/tapi-yandex-direct/tapi_yandex_direct/tapi_yandex_direct.py
  - RESULT_DICTIONARY_KEYS_OF_API_METHODS включает add/update и др.
  - Ресурсы campaigns/adgroups/ads/keywords описаны в: yandex.ad/repos/tapi-yandex-direct/tapi_yandex_direct/resource_mapping.py

## Неочевидные/старые варианты (осторожно)
- yapi-net/YandexDirect (C#): есть CreateOrUpdateCampaign и CreateOrUpdateBanners, но похоже на старый API: yandex.ad/repos/YandexDirect/Yandex.Direct/YandexDirectService.cs
- ArtemBuskunov/API_YD (C#): проект с MVC и частичной логикой UpdateCampaign (не чистая библиотека), сложнее для переиспользования: yandex.ad/repos/API_YD/API_Yandex_Direct/UpDate
