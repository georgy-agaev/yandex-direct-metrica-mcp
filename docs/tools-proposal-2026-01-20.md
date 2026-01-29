# Предложение по списку MCP-инструментов — дополнение (Accounts registry)

Этот документ дополняет `docs/tools-proposal-2026-01-14.md` для сценария агентства/мульти‑проекта:
нужно управлять несколькими “проектами” (child accounts) из одного MCP, не храня секреты в образе.

## Новый уровень E (администрирование аккаунтов/проектов)

1) `accounts.list`
- Назначение: показать текущие профили проектов из `MCP_ACCOUNTS_FILE`.
- Параметры: нет.
- Возврат: `{path, count, accounts[]}`.

2) `accounts.reload`
- Назначение: перечитать `MCP_ACCOUNTS_FILE` с диска (обновить кеш на сервере).
- Параметры: нет.
- Возврат: `{path, count, account_ids[]}`.

3) `accounts.upsert`
- Назначение: создать/обновить профиль проекта (`account_id -> direct_client_login + metrica_counter_ids`).
- Параметры: `account_id`, `name?`, `direct_client_login?`, `metrica_counter_ids?`, `replace?`.
- Примечание: write‑операция, по умолчанию запрещена; включается `MCP_ACCOUNTS_WRITE_ENABLED=true`.

4) `accounts.delete`
- Назначение: удалить профиль проекта по `account_id`.
- Параметры: `account_id`.
- Примечание: write‑операция, по умолчанию запрещена; включается `MCP_ACCOUNTS_WRITE_ENABLED=true`.

## Примечания
- `accounts.*` не работают с OAuth токенами и не хранят секреты; меняется только `accounts.json` (non‑secret).
- Схемы `account_id` у `direct.*`/`metrica.*` допускают любую строку, но показывают enum‑подсказку из реестра.

## Новый уровень F (утилиты)

1) `dashboard.generate_option1`
- Назначение: сгенерировать BI-дашборд (Option 1) как HTML+JSON из реальных данных Direct+Metrica.
- Параметры: `account_id?`, `direct_client_login?`, `counter_id?`, `date_from`, `date_to`, `output_dir?`, `dashboard_slug?`.
- Примечания:
  - Если передан `output_dir`, сервер пишет файлы на диск и возвращает пути.
  - Если `output_dir` не задан, можно вернуть HTML в ответе (`include_html=true`).
