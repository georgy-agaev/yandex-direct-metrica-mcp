# yandex-direct-metrica-mcp

MCP server for **Yandex Direct** + **Yandex Metrica** (Python).

Primary UX goals:
- Pull raw reporting data (lightweight MVP, minimal normalization).
- Generate a practical **BI dashboard (Option 1)** as `HTML + JSON` (including multi-account dashboards).
- Make it easy to use from **Claude Code** via `claude mcp add`.

## Quick start (Claude Code + Docker)

### 1) Prepare state folder

Create a local folder for state/config (accounts registry, cache, etc):
- Example: `~/mcp-state/yandex-direct-metrica-mcp`

Create `accounts.json` (multi-account dashboards use this):
```json
{
  "accounts": [
    {
      "id": "elama-16161182_vx",
      "name": "Headset VX",
      "direct_client_login": "elama-16161182",
      "metrica_counter_ids": ["91450749"]
    }
  ]
}
```

### 2) Prepare `.env`

Copy `.env.example` to your state folder and fill in:
- Yandex OAuth tokens
- Default Direct client login
- Allowed Metrica counters

Important: **do not** commit secrets to git.

### 3) Add MCP server to Claude Code

Using a locally-built image:
```bash
docker build -t yandex-direct-metrica-mcp:local .
```

```bash
claude mcp add yandex-direct-metrica-mcp -- \
  docker run --rm -i \
    --env-file /path/to/your/.env \
    -e MCP_ACCOUNTS_FILE=/data/accounts.json \
    -v /path/to/your/state:/data \
    yandex-direct-metrica-mcp:local
```

Then:
```bash
claude mcp list
```

### 4) Generate dashboard (Option 1)

Tip: Direct/Metrica data for “today” is often incomplete. For daily use, set `date_to` to **yesterday**.

Ask Claude Code:
- “Generate `dashboard.generate_option1` for all accounts for last 30 days (to yesterday), save to `/path/to/dashboards`, `all_accounts=true`, `return_data=false`, and give me the HTML path.”

## What can it do? (tools / layers)

This MCP exposes two layers:

### 1) Raw data access (low-level tools)

The goal is to give the LLM **full access to raw reporting data** with minimal normalization:
- `direct.*` — Yandex Direct API calls (reports, entities, dictionaries)
- `metrica.*` — Yandex Metrica API calls (exports, reports)

Output format is controlled by:
- `MCP_CONTENT_MODE=json` (recommended for raw analysis)

### 2) Human-friendly layer (high-level tools)

These tools focus on practical analytics workflows:
- `direct.hf.*` — “human-friendly” helpers over Direct (find/report presets, convenience queries)
- `join.hf.*` — best-effort joins between Direct + Metrica (UTM / yclid)
- `dashboard.generate_option1` — generates a self-contained BI dashboard (`HTML + JSON`)

To see the full list of tools in your environment:
- In Claude Code: ask “List available tools for this MCP server” (it calls `tools/list`).
- In this repo: see `docs/tool-coverage-2026-01-27.md`.

## CLI commands

The container/entrypoint runs the MCP server (stdio by default). Local/venv entrypoints:
- `yandex-direct-metrica-mcp` (preferred)
- `mcp-yandex-ad` (legacy alias)

The CLI also provides:
- `auth` — interactive OAuth helper (opens auth URL and exchanges code)

## Public vs Pro

This repo supports a “public read-only” mode:
- `MCP_PUBLIC_READONLY=true` hides/disables write tools (Direct create/update and raw_call).
- `MCP_PUBLIC_READONLY=false` keeps full toolset (intended for a Pro image/release).

## Docs (developer notes / project history)

- Setup notes: `docs/README-setup-2026-01-14.md`
- Claude Code setup (local/dev): `docs/claude-code-setup-2026-01-27.md`
- Publishing (Docker + registries): `docs/publishing-docker-2026-01-29.md`
- Quickstart: `docs/quickstart.md`
- Dashboard: `docs/dashboard-option1.md`
- Public vs Pro: `docs/public-vs-pro.md`
- Claude Code prompt examples: `examples/claude-code-prompts.md`

## Development

Run locally (without Docker):
- `python -m venv .venv && .venv/bin/pip install -e .`
- `.venv/bin/yandex-direct-metrica-mcp --env-file /path/to/.env` (preferred)
- `.venv/bin/mcp-yandex-ad --env-file /path/to/.env` (legacy alias)

CI and publishing:
- CI: `.github/workflows/ci.yml`
- Docker publish: `.github/workflows/docker-publish.yml`

## Disclaimer (affiliation / trademarks)

- This project is not affiliated with, endorsed by, or sponsored by Yandex.
- Yandex, Yandex.Direct, Yandex.Metrica are trademarks of their respective owners.

## Compliance / Terms

- You are responsible for complying with Yandex Direct API and Yandex Metrica terms, policies, and applicable laws.
- Direct and Metrica API calls are performed **on your behalf** using your OAuth credentials; you must have proper access and accept/comply with the relevant API terms.
- External service docs/terms (reference):
  - Direct API docs: `https://yandex.com/dev/direct/`
  - Metrica API docs: `https://yandex.com/dev/metrika/`
