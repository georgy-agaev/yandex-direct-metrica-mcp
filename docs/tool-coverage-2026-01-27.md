# Tool coverage (MCP Yandex Direct + Metrica) — 2026-01-27

Цель: зафиксировать текущее покрытие MCP-инструментов в проекте `yandex-direct-metrica-mcp` (legacy alias: `mcp-yandex-ad`):
что есть, какие зависимости/гейты у каждого tool, и в каком режиме он безопасен.

## Легенда
- **Read**: только чтение.
- **Write**: потенциально изменяет данные (Direct) или пишет в `accounts.json`.
- **HF**: human-friendly слой. Для Direct HF записи выполняются только при `apply=true`.
- **Guards**:
  - `MCP_WRITE_ENABLED=true` — разрешает Direct write.
  - `MCP_WRITE_SANDBOX_ONLY=true` + `YANDEX_DIRECT_SANDBOX=true` — разрешает Direct write только в Sandbox (по умолчанию включено).
  - `HF_ENABLED=true` — включает каталог HF tools.
  - `HF_WRITE_ENABLED=true` — включает HF write инструменты (дополнительно к `MCP_WRITE_ENABLED`).
  - `HF_DESTRUCTIVE_ENABLED=true` — включает HF delete инструменты (дополнительно к `HF_WRITE_ENABLED`).
  - `MCP_ACCOUNTS_WRITE_ENABLED=true` — разрешает `accounts.upsert/delete`.

## Глобальные зависимости
- Auth:
  - `YANDEX_ACCESS_TOKEN` **или** `YANDEX_REFRESH_TOKEN` (+ `YANDEX_CLIENT_ID`, `YANDEX_CLIENT_SECRET`).
- Direct:
  - Требуется корректный `Client-Login` для агентских аккаунтов:
    - по умолчанию: `YANDEX_DIRECT_CLIENT_LOGIN`
    - либо per-call: `direct_client_login`
    - либо через профили: `account_id` + `MCP_ACCOUNTS_FILE`
- Metrica:
  - Для `metrica.*` нужен доступ токена к счётчику (`counter_id`), иногда Logs API.

## Accounts registry (уровень E)
| Tool | Type | Requires | Guards | Notes |
| --- | --- | --- | --- | --- |
| `accounts.list` | Read | `MCP_ACCOUNTS_FILE` (опционально) | — | Показывает текущий реестр профилей. |
| `accounts.reload` | Read | `MCP_ACCOUNTS_FILE` (опционально) | — | Перечитывает реестр с диска (обновляет кеш). |
| `accounts.upsert` | Write | `MCP_ACCOUNTS_FILE` | `MCP_ACCOUNTS_WRITE_ENABLED` | Пишет только non-secret данные (логин/счётчики). |
| `accounts.delete` | Write | `MCP_ACCOUNTS_FILE` | `MCP_ACCOUNTS_WRITE_ENABLED` | Удаляет профиль по `account_id`. |

## Direct (уровни A–D)
| Tool | Type | Requires | Guards | Notes |
| --- | --- | --- | --- | --- |
| `direct.list_campaigns` | Read | Direct client | — | Поддерживает `direct_client_login` / `account_id`. |
| `direct.list_adgroups` | Read | Direct client | — | — |
| `direct.list_ads` | Read | Direct client | — | — |
| `direct.list_keywords` | Read | Direct client | — | — |
| `direct.report` | Read | Direct client | — | Возвращает raw TSV/columns (без нормализации). |
| `direct.list_clients` | Read | Direct client | — | Полезно для агентских аккаунтов. |
| `direct.list_dictionaries` | Read | Direct client | — | Кешируется при `MCP_CACHE_ENABLED=true`. |
| `direct.get_changes` | Read | Direct client | — | Инкрементальные изменения. |
| `direct.list_sitelinks` | Read | Direct client | — | Для `v501` требует Ids. |
| `direct.list_vcards` | Read | Direct client | — | Для `v501` требует Ids. |
| `direct.list_adextensions` | Read | Direct client | — | — |
| `direct.list_bids` | Read | Direct client | — | — |
| `direct.list_bidmodifiers` | Read | Direct client | — | — |
| `direct.raw_call` | Read/Write | Direct client | non-GET: `MCP_WRITE_ENABLED` (+ sandbox guard) | Escape hatch; non-GET запрещён без write guards. |
| `direct.create_campaigns` | Write | Direct client | `MCP_WRITE_ENABLED` (+ sandbox guard) | Direct Sandbox по умолчанию. |
| `direct.update_campaigns` | Write | Direct client | `MCP_WRITE_ENABLED` (+ sandbox guard) | — |
| `direct.create_adgroups` | Write | Direct client | `MCP_WRITE_ENABLED` (+ sandbox guard) | — |
| `direct.update_adgroups` | Write | Direct client | `MCP_WRITE_ENABLED` (+ sandbox guard) | — |
| `direct.create_ads` | Write | Direct client | `MCP_WRITE_ENABLED` (+ sandbox guard) | Нормализует callouts shape для `ads.add`. |
| `direct.update_ads` | Write | Direct client | `MCP_WRITE_ENABLED` (+ sandbox guard) | — |
| `direct.create_keywords` | Write | Direct client | `MCP_WRITE_ENABLED` (+ sandbox guard) | — |
| `direct.update_keywords` | Write | Direct client | `MCP_WRITE_ENABLED` (+ sandbox guard) | — |

## Metrica (уровни A–C)
| Tool | Type | Requires | Guards | Notes |
| --- | --- | --- | --- | --- |
| `metrica.list_counters` | Read | Metrica management client | — | Список доступных счётчиков. |
| `metrica.counter_info` | Read | Metrica management client | — | Детали по конкретному `counter_id`. |
| `metrica.report` | Read | Metrica stats client | — | Raw JSON отчёт Stats API. |
| `metrica.logs_export` | Read | Metrica logs client | — | Поддерживает create/info/allinfo/download/cancel/clean/evaluate (через `action`). |
| `metrica.raw_call` | Read/Write* | Metrica clients | — | Stats: только GET. Management: поддерживает write (если токен/права позволяют). |

## HF tools (Direct)
Примечание: HF-инструменты Direct **выполняют запись только при `apply=true`**.
При `apply=false` обычно возвращают `preview` (dry-run). Все записи проходят через базовый write guard (`MCP_WRITE_ENABLED`, sandbox-only).

| Tool prefix / tool | Type | Requires | Guards | Notes |
| --- | --- | --- | --- | --- |
| `direct.hf.find_*` | Read | Direct client | `HF_ENABLED` | Поиск сущностей по имени/фильтрам. |
| `direct.hf.get_campaign_summary` | Read | Direct client | `HF_ENABLED` | Сводка с подсчётами. |
| `direct.hf.get_campaign_assets` | Read | Direct client | `HF_ENABLED` | Привязанные assets (sitelinks/callouts/vcards). |
| `direct.hf.report_*` | Read | Direct client | `HF_ENABLED` | Пресеты отчётов. |
| `direct.hf.pause_*` / `resume_*` / `archive_*` / `unarchive_*` | Write (apply=true) | Direct client | `HF_ENABLED` + `HF_WRITE_ENABLED` + base write guards | Безопасные управляющие операции. |
| `direct.hf.moderate_ads` | Write (apply=true) | Direct client | `HF_ENABLED` + `HF_WRITE_ENABLED` + base write guards | Модерация (best effort). |
| `direct.hf.set_campaign_*` / `set_adgroup_*` | Write (apply=true) | Direct client | `HF_ENABLED` + `HF_WRITE_ENABLED` + base write guards | Бюджет/стратегия/гео/расписание/минуса/UTM. |
| `direct.hf.create_*` / `update_*` / `attach_*` / `ensure_assets_*` | Write (apply=true) | Direct client | `HF_ENABLED` + `HF_WRITE_ENABLED` + base write guards | Генерация payload + создание/привязка assets. |
| `direct.hf.set_keyword_bid*` / `set_bid_modifier_*` / `clear_bid_modifiers` | Write (apply=true) | Direct client | `HF_ENABLED` + `HF_WRITE_ENABLED` + base write guards | Денежно-чувствительные действия — используйте Sandbox/preview. |
| `direct.hf.delete_ads` / `direct.hf.delete_keywords` | Write (apply=true) | Direct client | `HF_ENABLED` + `HF_WRITE_ENABLED` + `HF_DESTRUCTIVE_ENABLED` + base write guards | Деструктивные операции, по умолчанию выключены. |

## HF tools (Metrica)
| Tool | Type | Requires | Guards | Notes |
| --- | --- | --- | --- | --- |
| `metrica.hf.*` | Read | Metrica clients | `HF_ENABLED` | Пресеты отчётов и discovery counters. |

## Join tools (HF)
| Tool | Type | Requires | Guards | Notes |
| --- | --- | --- | --- | --- |
| `join.hf.direct_vs_metrica_by_utm` | Read | Direct report + Metrica stats | `HF_ENABLED` | Возвращает объединённый дневной ряд (Direct: impressions/clicks/cost + Metrica: visits) по `ym:s:UTMCampaign`. |
| `join.hf.direct_vs_metrica_by_yclid` | Read | Metrica logs + Direct report | `HF_ENABLED` | Best-effort join: Logs API yclid + Direct click id (resumable `request_id`, bounded `max_rows`, возможны оверрайды Direct report params). |
