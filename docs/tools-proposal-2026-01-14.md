# Предложение по списку MCP-инструментов (Python, Direct + Metrica)

База: `pavelmaksimov/tapi-yandex-direct` + `pavelmaksimov/tapi-yandex-metrika`.
Цель: read-only, сырые выгрузки, минимальная нормализация.

## Уровень A (MVP, обязателен)

### Direct (структура + базовая статистика)
1) `direct.list_campaigns`
- Назначение: получить список кампаний.
- Параметры: `campaign_ids?`, `states?`, `types?`, `fields?`, `limit?`, `offset?`
- Возврат: сырой список Campaigns.

2) `direct.list_adgroups`
- Назначение: список групп объявлений.
- Параметры: `campaign_ids?`, `adgroup_ids?`, `fields?`, `limit?`, `offset?`
- Возврат: сырой список AdGroups.

3) `direct.list_ads`
- Назначение: список объявлений.
- Параметры: `campaign_ids?`, `adgroup_ids?`, `ad_ids?`, `fields?`, `limit?`, `offset?`
- Возврат: сырой список Ads.

4) `direct.list_keywords`
- Назначение: список ключевых слов.
- Параметры: `campaign_ids?`, `adgroup_ids?`, `keyword_ids?`, `fields?`, `limit?`, `offset?`
- Возврат: сырой список Keywords.

5) `direct.report`
- Назначение: отчеты Direct (показы/клики/CTR/расход, по периодам).
- Параметры: `date_from`, `date_to`, `granularity` (day/week/month), `fields`, `filters?`, `attribution?`, `limit?`
- Возврат: сырой отчет (без агрегации в MCP).

### Metrica (поведенческие метрики)
6) `metrica.list_counters`
- Назначение: список доступных счетчиков.
- Параметры: нет / `limit?`, `offset?`

7) `metrica.report`
- Назначение: сырые отчеты Метрики (визиты/время на сайте/landing pages и пр.).
- Параметры: `counter_id`, `date_from`, `date_to`, `metrics`, `dimensions`, `filters?`, `accuracy?`, `limit?`, `offset?`, `sort?`
- Возврат: сырой отчет.

## Уровень B (полезно для роста / удобства)

### Direct
8) `direct.list_clients`
- Для агентских аккаунтов.

9) `direct.list_dictionaries`
- Справочники Direct (временные зоны, валюты, регионы и пр.).

10) `direct.get_changes`
- Инкрементальные изменения (по Timestamp), удобно для синхронизаций.

11) `direct.list_sitelinks`
12) `direct.list_vcards`
13) `direct.list_adextensions`
- Часто нужны для полной структуры объявлений.

14) `direct.list_bids`
15) `direct.list_bidmodifiers`
- Если понадобится read-only по ставкам/модификаторам.

### Metrica
16) `metrica.counter_info`
- Детали счетчика и доступность метрик.

17) `metrica.logs_export` (опционально)
- Если понадобятся большие выгрузки (Logs API), но сложнее и тяжелее.

## Уровень C (общий “escape hatch”)

18) `direct.raw_call`
- Параметры: `resource`, `method`, `body`.
- Полезно для новых эндпоинтов без изменения MCP.

19) `metrica.raw_call`
- Параметры: `resource`, `method`, `params`, `data`.

## Уровень D (write операции, Direct)

20) `direct.create_campaigns`
21) `direct.update_campaigns`
22) `direct.create_adgroups`
23) `direct.update_adgroups`
24) `direct.create_ads`
25) `direct.update_ads`
26) `direct.create_keywords`
27) `direct.update_keywords`
- Параметры: `items` (массив сущностей) или `params` (сырой payload).
- Использовать с осторожностью, по возможности через Sandbox.

## Примечания по метрикам/разрезам
- Посадочные страницы и “время на сайте” берем из Metrica.
- Для привязки к кампаниям рекомендуется использовать UTM (`utm_campaign`, `utm_content`) или `yclid`.
- MCP не делает склейку на старте — только сырые выгрузки. Склейка будет отдельным слоем позже.
