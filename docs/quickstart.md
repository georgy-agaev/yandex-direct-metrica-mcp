# Quickstart (Docker + Claude Code)

This guide assumes you want the **Docker** runtime (recommended) and you will connect via **Claude Code**.

## Prerequisites

- Docker Desktop
- Claude Code CLI (`claude`)
- Yandex OAuth token(s) with access to:
  - Direct API (for the relevant client logins)
  - Metrica API (for the relevant counter IDs)

## 1) Create a state folder

Pick a folder that will store configuration/state on your machine:
- Example: `~/mcp-state/yandex-direct-metrica-mcp`

Inside it, create `accounts.json`:
```json
{
  "accounts": [
    {
      "id": "example_project",
      "name": "Example project",
      "direct_client_login": "example-client-login",
      "metrica_counter_ids": ["12345678"]
    }
  ]
}
```

Notes:
- `id` must be **unique**. If one Direct client login maps to multiple sites/counters, create multiple profiles with different `id`.
- `metrica_counter_ids` is an allow-list for that profile (used by dashboard + joins).

## 2) Create an `.env`

Copy `.env.example` and fill it:
- OAuth token(s)
- Direct defaults (`YANDEX_DIRECT_CLIENT_LOGIN`, optional `YANDEX_DIRECT_CLIENT_LOGINS`)
- Metrica allow-list (`YANDEX_METRICA_COUNTER_IDS`)

Recommended defaults for public/read-only usage:
- `MCP_WRITE_ENABLED=false`
- `HF_WRITE_ENABLED=false`
- `MCP_PUBLIC_READONLY=true`

## 3) Add MCP to Claude Code

Build locally:
```bash
docker build -t yandex-direct-metrica-mcp:local .
```

Add to Claude Code:
```bash
claude mcp add yandex-direct-metrica-mcp -- \
  docker run --rm -i \
    --env-file /path/to/your/.env \
    -e MCP_ACCOUNTS_FILE=/data/accounts.json \
    -v /path/to/your/state:/data \
    yandex-direct-metrica-mcp:local
```

Verify:
```bash
claude mcp list
```

## 4) First checks

In Claude Code, try:
- “List accounts from the server.”
- “Generate `dashboard.generate_option1` for all accounts for the last 30 days **to yesterday**, save into `/path/to/dashboards`, `all_accounts=true`, `return_data=false`, and give me the HTML path.”
