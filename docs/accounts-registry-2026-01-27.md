# Accounts registry (`accounts.json`) — 2026-01-27

Цель: поддержать multi-project / агентский сценарий в одном MCP-сервере **без хранения секретов** в `accounts.json`.

## Что это
`accounts.json` — это non-secret реестр “профилей проекта”:

- `account_id` → Direct `Client-Login` (child login)
- `account_id` → (опционально) список default `metrica_counter_ids`

OAuth токен и любые секреты **не** хранятся в реестре (они идут через env).

## Как включить
1) Создайте файл (например, рядом с `.env`, вне репозитория):
- `~/mcp/state/yandex.ad/accounts.json`

2) Укажите путь:
- `MCP_ACCOUNTS_FILE=/path/to/accounts.json`

3) (Опционально) Разрешите запись через MCP tools:
- `MCP_ACCOUNTS_WRITE_ENABLED=true`

## Формат файла
Поддерживаются два варианта, оба валидны. Канонический формат — массив профилей.

### Вариант A (рекомендуется): объект с массивом `accounts`
```json
{
  "accounts": [
    {
      "id": "voicexpert",
      "name": "Voice Expert",
      "direct_client_login": "elama-11111111",
      "metrica_counter_ids": ["12345678"]
    },
    {
      "id": "project-b",
      "direct_client_login": "elama-22222222",
      "metrica_counter_ids": ["111", "222"]
    }
  ]
}
```

### Вариант B: просто массив профилей (короче)
```json
[
  {
    "id": "voicexpert",
    "direct_client_login": "elama-11111111",
    "metrica_counter_ids": ["12345678"]
  }
]
```

## Рекомендации по именованию `account_id`
- Используйте стабильные slug’и: `project-x`, `client-foo`, `voicexpert`.
- Избегайте пробелов и случайных UUID (хуже для UX и подсказок enum).
- `account_id` должен быть “человеческим”, чтобы его было удобно передавать в MCP-клиенте.

## Как используется в tool calls
Большинство tools автоматически принимают `account_id` (с подсказкой enum, если реестр загружен).

### Direct (`direct.*`, `direct.hf.*`, `join.hf.*`)
- Если указан `account_id` и у профиля есть `direct_client_login`, сервер подставит его как `direct_client_login`.
- Если одновременно передать `account_id` и `direct_client_login`, и они конфликтуют — вернётся ошибка (защита от случайных запросов в “не тот” аккаунт).

### Metrica (`metrica.*`, `metrica.hf.*`, `join.hf.*`)
- Если tool ожидает `counter_id`, а вы передали только `account_id`:
  - если в профиле **ровно один** `metrica_counter_ids` — он будет использован как `counter_id`;
  - если их несколько — вернётся ошибка с просьбой указать `counter_id` явно.

## Управление реестром через MCP
Есть отдельные tools:
- `accounts.list`
- `accounts.reload`
- `accounts.upsert` (только при `MCP_ACCOUNTS_WRITE_ENABLED=true`)
- `accounts.delete` (только при `MCP_ACCOUNTS_WRITE_ENABLED=true`)

Важно: эти инструменты управляют **только** `accounts.json` (non-secret поля) и не трогают токены.

## Docker / Docker Compose
Рекомендуемый паттерн: держать `.env` и `accounts.json` в внешней state-папке и монтировать её в контейнер.
Пример см. в `docker-compose.yml` (используется `/Users/georgyagaev/mcp/state/yandex.ad`).
