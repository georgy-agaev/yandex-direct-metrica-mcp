# yandex-direct-metrica-mcp

MCP server for **Yandex Direct + Yandex Metrica + Yandex Wordstat + Yandex Audience** (Python).

Website (docs): https://georgy-agaev.github.io/yandex-direct-metrica-mcp/

Russian docs: https://georgy-agaev.github.io/yandex-direct-metrica-mcp/ru/

Images:
- GHCR (public): https://github.com/georgy-agaev/yandex-direct-metrica-mcp/pkgs/container/yandex-direct-metrica-mcp
- GHCR (pro): https://github.com/georgy-agaev/yandex-direct-metrica-mcp/pkgs/container/yandex-direct-metrica-mcp-pro
- Docker Hub (optional mirror, if configured): https://hub.docker.com/r/4georgyagaev/yandex-direct-metrica-mcp

Primary UX goals:
- Pull raw data for analytics (minimal normalization, traceable outputs).
- Generate a practical **BI dashboard (Option 1)** as `HTML + JSON` (including multi-account dashboards).
- Provide **BI Option 2 (PRO, plugin)**: datasets + incremental sync (warehouse/BI pipelines).
- Make it easy to use from **Claude Code** via `claude mcp add`.

## Quick start (Claude Code + Docker)

### Automated setup (recommended)

Run the interactive wizard — it creates `.env`, `accounts.json`, and registers the MCP server for your client (Claude Code, Claude Desktop, Cursor, Codex CLI, OpenCode, Gemini CLI):

```bash
python3 scripts/setup.py
```

Or follow the manual steps below.

### 1) Prepare state folder

Create a local folder for state/config (accounts registry, cache, etc):
- Example: `/path/to/mcp-state/yandex-direct-metrica-mcp`

Create `accounts.json` (multi-account dashboards use this):
```json
{
  "accounts": [
    {
      "id": "account_ID",
      "name": "account_name",
      "direct_client_login": "direc_client_login",
      "metrica_counter_ids": ["9999999"]
    }
  ]
}
```

### 2) Prepare `.env`

Copy `.env.example` to your state folder and fill in:
- Direct/Metrica OAuth credentials
- Audience OAuth credentials (optional)
- Wordstat Yandex Search API credentials (optional)

Important: **do not** commit secrets to git.

### 3) Add MCP server to Claude Code

Public (read-only, safe-by-default):
```bash
claude mcp add yandex-direct-metrica-mcp -- \
  docker run --rm -i \
    --env-file /path/to/your/.env \
    -e MCP_ACCOUNTS_FILE=/data/accounts.json \
    -v /path/to/your/state:/data \
    ghcr.io/georgy-agaev/yandex-direct-metrica-mcp:latest
```

Pinned to a specific version:
```bash
claude mcp add yandex-direct-metrica-mcp -- \
  docker run --rm -i \
    --env-file /path/to/your/.env \
    -e MCP_ACCOUNTS_FILE=/data/accounts.json \
    -v /path/to/your/state:/data \
    ghcr.io/georgy-agaev/yandex-direct-metrica-mcp:v1.0.0
```

Pro (separate artifact; intended for paid subscribers; keep the GHCR package private):
```bash
claude mcp add yandex-direct-metrica-mcp-pro -- \
  docker run --rm -i \
    --env-file /path/to/your/.env \
    -e MCP_ACCOUNTS_FILE=/data/accounts.json \
    -v /path/to/your/state:/data \
    ghcr.io/georgy-agaev/yandex-direct-metrica-mcp-pro:v1.0.0
```

Using a locally-built image (for development):
```bash
docker build -t yandex-direct-metrica-mcp:local .

claude mcp add yandex-direct-metrica-mcp -- \
  docker run --rm -i \
    --env-file /path/to/your/.env \
    -e MCP_ACCOUNTS_FILE=/data/accounts.json \
    -v /path/to/your/state:/data \
    yandex-direct-metrica-mcp:local
```

Notes:
- `docker build ...` produces a **public read-only** image by default.
- If you really need a local PRO image, build with:
  - `docker build --build-arg MCP_EDITION=pro --build-arg MCP_PUBLIC_READONLY=false -t yandex-direct-metrica-mcp:pro .`
  - BI Option 2 is delivered via a private PRO plug-in; install it during build via `--build-arg MCP_PLUGIN_PIP="..."` (see `docs/pro-plugin.md`).

Then:
```bash
claude mcp list
```

### 4) Generate dashboard (Option 1)

Tip: Direct/Metrica data for “today” is often incomplete. For daily use, set `date_to` to **yesterday**.

Ask Claude Code:
- “Generate `dashboard.generate_option1` for all accounts for last 30 days (to yesterday), save to `/path/to/dashboards`, `all_accounts=true`, `return_data=false`, and give me the HTML path.”

## What “read-only” means (Public 1.0.0 contract)

Read-only means:
- no changes to managed entities in **Direct/Metrica/Audience** (no create/update/delete of campaigns, segments, goals, etc.).

Allowed side effects (still treated as read-only for the public contract):
- **Wordstat** report-like requests (provider-side compute).
- **Metrica Logs API** export jobs used for analysis/joins (`metrica.logs_export`) — no counter configuration changes.

Public mode spec:
- `docs/public-mode.md`

## What can it do? (tools / layers)

This MCP exposes two layers:

### 1) Raw data access (low-level tools)

The goal is to give the LLM **full access to raw reporting data** with minimal normalization:
- `direct.*` — Yandex Direct API calls (reports, entities, dictionaries)
- `metrica.*` — Yandex Metrica API calls (exports, reports)
- `wordstat.*` — Yandex Wordstat API calls (keyword statistics)
- `search_serp` — Yandex Search API Web Search SERP normalization (ads + organic)
- `audience.*` — Yandex Audience API calls (segments, overlaps, catalogs)

Output format is controlled by:
- `MCP_CONTENT_MODE=json` (recommended for raw analysis)

### 2) Human-friendly layer (high-level tools)

These tools focus on practical analytics workflows:
- `direct.hf.*` — “human-friendly” helpers over Direct (find/report presets, convenience queries)
- `join.hf.*` — best-effort joins between Direct + Metrica (UTM / yclid)
- `wordstat.hf.*` — keyword suggestions helpers over Wordstat
- `audience.hf.*` — audience catalog + best-effort segment performance proxy
- `dashboard.generate_option1` — generates a self-contained BI dashboard (`HTML + JSON`)

### 3) BI Option 2 (PRO plugin): datasets + incremental sync

BI Option 2 is provided by an optional **private PRO plugin** (not part of the public OSS build):
- `dashboard.schema`
- `dashboard.dataset.*`
- `dashboard.sync.start` / `dashboard.sync.next` (NDJSON-friendly)

See:
- `docs/bi-option2-proposal-2026-02-03.md`
- `docs/llm-usage-guide-pro-2026-02-03.md`

To see the full list of tools in your environment:
- In Claude Code: ask “List available tools for this MCP server” (it calls `tools/list`).
- In this repo: see `docs/tool-coverage-2026-01-27.md`.

## Environment variables (high level)

Direct/Metrica OAuth (usually shared app/token):
- `YANDEX_ACCESS_TOKEN` or `YANDEX_REFRESH_TOKEN`
- if using refresh: `YANDEX_CLIENT_ID`, `YANDEX_CLIENT_SECRET`

Audience OAuth (may be shared with Direct/Metrica, but can be separate):
- `YANDEX_AUDIENCE_ACCESS_TOKEN` or `YANDEX_AUDIENCE_REFRESH_TOKEN`
- if using refresh: `YANDEX_AUDIENCE_CLIENT_ID`, `YANDEX_AUDIENCE_CLIENT_SECRET`

Wordstat and Web Search via Yandex Search API:
- `YANDEX_SEARCH_API_FOLDER_ID`
- `YANDEX_SEARCH_API_API_KEY` or `YANDEX_SEARCH_API_IAM_TOKEN`
- optional Web Search defaults: `MCP_SEARCH_API_ENABLED`, `YANDEX_SEARCH_API_DEFAULT_REGION`

Search API tools do **not** use Direct OAuth. Configure them separately:
- the service account belongs to the target folder;
- the service account has `search-api.webSearch.user`;
- the API key is created for that service account;
- if API key scopes are configured, include `yc.search-api.execute`;
- `YANDEX_SEARCH_API_FOLDER_ID` matches that folder.

If `wordstat.user_info` or any `wordstat.*` call returns 401/403, check the role/scope/folder above. For `wordstat.dynamics`, monthly `to_date` must be `YYYY-MM` or the last day of the month; weekly boundaries are provider-specific, so use raw `params` only with a confirmed provider-valid `toDate`.

`search_serp` uses the same Search API credentials and returns normalized `ads`, `ads_count_top`, `ads_count_bottom`, `organic`, and `captcha`. For HTML ads, `ads[].domain` is the normalized advertiser domain, `ads[].click_url` retains the Yandex redirect when present, `ads[].type` is `text`, `product_gallery`, or `native`, and `ads[].block` is `top` or `bottom` when placement can be inferred. Use `format=html` when ads are required; raw HTML is returned only with `include_raw=true`.

Multi-account registry:
- `MCP_ACCOUNTS_FILE=/data/accounts.json`

Public/pro flags:
- Public image forces read-only (safe-by-default), but `MCP_PUBLIC_READONLY=true` remains a compatibility flag.
- Pro writes require explicit enables:
  - `MCP_WRITE_ENABLED=true`
  - `HF_WRITE_ENABLED=true` (HF write tools)
  - `HF_DESTRUCTIVE_ENABLED=true` (delete tools)
  - Optional safety: `MCP_TWO_PHASE_WRITES=true` (write tools return a `confirm_token`; execution requires `write.confirm`)
- Pro-only auth tools (return secrets; no storage): `MCP_AUTH_TOOLS_ENABLED=true`

## CLI commands

The container/entrypoint runs the MCP server (stdio by default). Local/venv entrypoints:
- `yandex-direct-metrica-mcp` (preferred)
- `mcp-yandex-ad` (legacy alias)

The CLI also provides:
- `auth` — interactive OAuth helper (opens auth URL and exchanges code)
  - `--flow hybrid` (default) uses loopback callback when `YANDEX_REDIRECT_URI` is a local URL (example: `http://127.0.0.1:8765/callback`), otherwise falls back to manual code copy/paste.
  - Tip: set `--output-env /path/to/.env` to avoid printing tokens to stdout.

## Public vs Pro

This repo ships **two artifacts**:

- Public: `yandex-direct-metrica-mcp` (safe-by-default read-only).
  - Contract: `tests/snapshots/public_tools_v1.json`
- Pro: `yandex-direct-metrica-mcp-pro` (writes still require explicit env guardrails) + private PRO plug-ins (e.g., BI Option 2).

See:
- `docs/public-vs-pro.md`
- `docs/compatibility-semver.md`

## Docs (developer notes / project history)

- Setup notes: `docs/README-setup-2026-01-14.md`
- Claude Code setup (local/dev): `docs/claude-code-setup-2026-01-27.md`
- Publishing (Docker + registries): `docs/publishing-docker-2026-01-29.md`
- Quickstart: `docs/quickstart.md`
- Dashboard: `docs/dashboard-option1.md`
- Audience: `docs/audience-2026-02-03.md`
- BI Option 2 (proposal, PRO): `docs/bi-option2-proposal-2026-02-03.md`
- LLM usage guide (public read-only): `docs/llm-usage-guide-2026-02-03.md`
- LLM usage guide (PRO): `docs/llm-usage-guide-pro-2026-02-03.md`
- Public vs Pro: `docs/public-vs-pro.md`
- Claude Code prompt examples: `examples/claude-code-prompts.md`

## Development

Run locally (without Docker):
- `python -m venv .venv && .venv/bin/pip install -e .`
- `.venv/bin/yandex-direct-metrica-mcp --env-file /path/to/.env` (preferred)
- `.venv/bin/mcp-yandex-ad --env-file /path/to/.env` (legacy alias)

CI and publishing:
- CI: `.github/workflows/ci.yml`
- Docker publish (public): `.github/workflows/docker-publish-public.yml`
- Docker publish (pro, gated): `.github/workflows/docker-publish-pro.yml`

## Documentation languages

- English docs live in `docs/` (this branch).
- Russian docs live in `docs/ru/` (this branch) and are published under `/ru/` on the docs website.

## Disclaimer (affiliation / trademarks)

- This project is not affiliated with, endorsed by, or sponsored by Yandex.
- Yandex, Yandex.Direct, Yandex.Metrica are trademarks of their respective owners.

## Compliance / Terms

- You are responsible for complying with Yandex Direct API and Yandex Metrica terms, policies, and applicable laws.
- Direct and Metrica API calls are performed **on your behalf** using your OAuth credentials; you must have proper access and accept/comply with the relevant API terms.
- External service docs/terms (reference):
  - Direct API docs: `https://yandex.com/dev/direct/`
  - Metrica API docs: `https://yandex.com/dev/metrika/`
