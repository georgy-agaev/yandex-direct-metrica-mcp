# Claude Desktop / Claude CLI: подключение MCP через Docker (SSE) без секретов

Цель: запустить MCP сервер в Docker с env-файлом вне репозитория и подключить его к Claude через SSE, не сохраняя креды в конфиге Claude.

## 1) Где лежат креды

Креденшиалсы хранятся вне репозитория:
- `/Users/georgyagaev/mcp/state/yandex.ad/.env`

Важно: `.env` не должен попадать в Docker image. Он подаётся только как переменные окружения контейнеру.

## 2) Запуск сервера в Docker (docker compose)

В `docker-compose.yml` используется `env_file` с абсолютным путём:
```yaml
services:
  yandex-direct-metrica-mcp:
    build: .
    env_file:
      - /Users/georgyagaev/mcp/state/yandex.ad/.env
    environment:
      - MCP_ACCOUNTS_FILE=/data/accounts.json
      - MCP_ACCOUNTS_WRITE_ENABLED=true
    volumes:
      - /Users/georgyagaev/mcp/state/yandex.ad:/data:ro
      - /Users/georgyagaev/mcp/state/yandex.ad/accounts.json:/data/accounts.json:rw
    command: ["yandex-direct-metrica-mcp", "--transport", "sse", "--port", "8000"]
    ports:
      - "8000:8000"
```

Пересобрать и запустить:
```bash
docker compose up --build -d
```

Проверка SSE:
```bash
curl -I http://localhost:8000/sse
```

## 3) Подключение через Claude CLI (к конкретному проекту)

Подключение выполняется через `mcp-remote`, креды Claude не нужны, т.к. сервер уже запущен локально и берёт env внутри контейнера.

### Вариант A: обычный `claude mcp add`
```bash
claude mcp add yandex-ad -s project -- npx -y mcp-remote http://localhost:8000/sse
```

### Вариант B: `claude mcp add-json`
```bash
claude mcp add-json yandex-ad -s project '{
  "command": "npx",
  "args": ["-y", "mcp-remote", "http://localhost:8000/sse"]
}'
```

Проверка:
```bash
claude mcp list
```

## Заметки
- Если порт занят, поменяйте маппинг в `docker-compose.yml` и URL в командах (например `8080:8000` и `http://localhost:8080/sse`).
- Для multi-project используйте `account_id` (профили хранятся в `accounts.json`). Управлять ими можно прямо из Claude через `accounts.*`:
  - `accounts.list` / `accounts.reload`
  - `accounts.upsert` / `accounts.delete` (требует `MCP_ACCOUNTS_WRITE_ENABLED=true`)
