# MCP Yandex Ad - Local setup

## Requirements
- Python 3.10+
- Docker (optional)

## Environment variables
- `YANDEX_ACCESS_TOKEN` or `YANDEX_REFRESH_TOKEN`
- `YANDEX_CLIENT_ID`, `YANDEX_CLIENT_SECRET` (required if using refresh token)
- `YANDEX_DIRECT_CLIENT_LOGIN` (agency accounts; default client login)
- `YANDEX_DIRECT_CLIENT_LOGINS` (optional; comma-separated list for multi-project UX)
- `YANDEX_METRICA_COUNTER_IDS` (comma-separated; supports multiple counters)
- `YANDEX_DIRECT_SANDBOX` (true/false)
- `YANDEX_DIRECT_API_VERSION` (`v5` or `v501`; use `v501` for Unified campaigns)
- `MCP_WRITE_ENABLED` (true/false; allow create/update in Direct)
- `MCP_WRITE_SANDBOX_ONLY` (true/false; restrict writes to sandbox)
Accounts registry (multi-project, non-secret):
- `MCP_ACCOUNTS_FILE` (path to `accounts.json`)
- `MCP_ACCOUNTS_WRITE_ENABLED` (true/false; allow `accounts.upsert/delete`)
HF (human-friendly) layer:
- `HF_ENABLED` (true/false; enable HF tools catalog)
- `HF_WRITE_ENABLED` (true/false; enable HF write tools; still requires MCP_WRITE_ENABLED)
- `HF_DESTRUCTIVE_ENABLED` (true/false; enable HF delete tools)
Note: set `YANDEX_DIRECT_SANDBOX=true` when testing create/update.

## Run locally (Python)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
yandex-direct-metrica-mcp (preferred; legacy alias: mcp-yandex-ad)
```
Dev/test deps:
```bash
pip install pytest pytest-asyncio
pytest
```
Note: default transport is `stdio`. Use `--transport sse` for HTTP access.
Tip: pass a specific env file with `yandex-direct-metrica-mcp --env-file .env` (legacy: `mcp-yandex-ad ...`).

## Logging
- Use `-v` or `-vv` for more verbose logs when debugging.
- Avoid logging tokens or raw request payloads with credentials.

## Run via Docker
```bash
docker build -t yandex-direct-metrica-mcp .
docker run --rm -e YANDEX_ACCESS_TOKEN=... yandex-direct-metrica-mcp
```
Note: add `--transport sse --port 8000` to enable HTTP access.

## Run via Docker Compose
```bash
docker compose up --build
```

## Running multiple instances (Docker)
```bash
docker run --rm -e YANDEX_ACCESS_TOKEN=... -e YANDEX_DIRECT_CLIENT_LOGIN=login_a -p 8081:8000 yandex-direct-metrica-mcp --transport sse --port 8000
docker run --rm -e YANDEX_ACCESS_TOKEN=... -e YANDEX_DIRECT_CLIENT_LOGIN=login_b -p 8082:8000 yandex-direct-metrica-mcp --transport sse --port 8000
```
Note: each container must expose a unique host port.
Alternative: you can keep a single server instance and pass `direct_client_login` per tool call to override `Client-Login`.

## Validate environment (no API calls)
```bash
python scripts/validate_env.py
```

## Health check (no API calls)
```bash
python scripts/health_check.py
```

## Exchange OAuth code for tokens
```bash
python scripts/exchange_code.py --code <AUTH_CODE>
```

## Interactive OAuth helper (recommended)
```bash
yandex-direct-metrica-mcp auth (legacy: mcp-yandex-ad auth)
```
Optional env for the helper:
- `YANDEX_SCOPES` (space-separated)
- `YANDEX_REDIRECT_URI`

## Runtime controls (optional)
- Response mode: `MCP_CONTENT_MODE` (`json`, `summary`, `summary_json`)
- Cache: `MCP_CACHE_ENABLED`, `MCP_CACHE_TTL_SECONDS`
- Throttling: `MCP_DIRECT_RATE_LIMIT_RPS`, `MCP_METRICA_RATE_LIMIT_RPS`
- Retries: `MCP_RETRY_MAX_ATTEMPTS`, `MCP_RETRY_BASE_DELAY_SECONDS`, `MCP_RETRY_MAX_DELAY_SECONDS`

## Smoke test (requires real credentials)
```bash
python scripts/smoke_test.py
```

## Auth troubleshooting
- If Direct calls fail with token errors, refresh tokens and check `YANDEX_DIRECT_CLIENT_LOGIN`.
- If Metrica calls fail with 403/429, verify counter access and quotas in Metrica.
- For `metrica.logs_export`, ensure Logs API is enabled and the token has access to logs.

## Common errors (quick hints)
| Provider | Symptom | Hint |
| --- | --- | --- |
| Direct | error_code 53 or message "OAuth token is missing" | Refresh tokens, check `YANDEX_DIRECT_CLIENT_LOGIN`. |
| Direct | error_code 56/506/9000 | Rate limit exceeded, retry later with backoff. |
| Direct | error_code 152 | Not enough units, retry later or reduce scope. |
| Metrica | error_code 403 | Token lacks access to the counter or scope. |
| Metrica | error_code 429 | Rate limit exceeded, retry later with backoff. |

## Retry/backoff guidance
- Start with exponential backoff (e.g., 2s, 4s, 8s) and add small jitter.
- Respect rate-limit errors and back off before retrying.
- For large reports, reduce date ranges to avoid timeouts.

## Goals and ecommerce prerequisites
- Conversion metrics require configured goals in Direct/Metrica.
- Revenue/ROI metrics require ecommerce or revenue goals to be enabled.

## UTM mapping strategy (Direct + Metrica)
- Use `ym:s:UTMCampaign` and other UTM dimensions to align Metrica visits with Direct campaigns.
- If UTM tagging is inconsistent, fall back to `yclid` in Metrica logs for joins.

## Multiple Direct client logins
- If you have an agency token, you can target different child accounts by passing:
  - `account_id` (recommended; requires `MCP_ACCOUNTS_FILE`), or
  - `direct_client_login` per tool call (advanced).
- Docs: `docs/accounts-registry-2026-01-27.md`.

## yclid-based joins (Logs API)
- Use `metrica.logs_export` with fields like `ym:s:clientID`, `ym:s:yclid`, `ym:s:startURL` to link visits to ad clicks.
- Keep request windows small (day/week) to avoid large exports.
- Verify the correct Direct field for click identifiers before joining; it can vary by report type.

## Sampling vs accuracy (Metrica reports)
- If you see sampling, try smaller date ranges or increase `accuracy`.
- Higher `accuracy` can increase response times; use only where needed.
