# Research: altrr2/yandex-tools-mcp (2026-01-17)

Repo: `https://github.com/altrr2/yandex-tools-mcp`

## What it is
- A Bun/Node monorepo shipping multiple MCP servers as separate packages:
  - Yandex Wordstat (keyword research)
  - Yandex Search (SERP)
  - Yandex Webmaster (SEO/Indexing)
  - Yandex Metrica (analytics)
- It **does not** implement Yandex Direct, but is useful as a reference for MCP UX patterns and operational concerns.

## Potentially useful ideas for our `yandex.ad` MCP

### 1) Dual output: `content` + `structuredContent`
- Many tools return:
  - `content`: short, human-readable summary (bulleted list, totals)
  - `structuredContent`: raw API response for models/clients
- This reduces token usage in the visible output while preserving full fidelity data for downstream reasoning.

**Adopted in our project:** yes (see “What we adopted”).

### 2) Simple session-level caching
- Example: Wordstat caches regions tree because it rarely changes.
- Example: Webmaster caches `user_id`.
- Cache scope is the process/session, no persistence, no DB.

**Potential use for us:**
- Cache Direct dictionaries (rarely change) when we start relying on them.
- Cache Metrica “counters list” once access is granted.

### 3) Basic rate limiting / quota-friendly behaviour
- Wordstat has a simple `RATE_LIMIT` window (10 req/s) + explicit 429/503 handling.

**Potential use for us:**
- Add an optional per-process throttle for bursty HF operations (bulk bids, bulk keyword updates).
- Keep it off by default to avoid unexpected delays; enable via env.

### 4) Auth helper CLI
- Each server exposes a `auth` CLI command to guide users through OAuth and print env config.

**Potential use for us:**
- We already have `scripts/exchange_code.py` and refresh-token support; we can consider a small interactive wrapper later.

### 5) Response ergonomics and consistent schemas
- Inputs are validated with a schema (Zod in JS).
- Outputs are predictable (summary + structured).

**Potential use for us:**
- Keep our tool schemas stable; extend behaviour without adding new tools unless approved.

## What we adopted (in `yandex.ad`)
- Added `structuredContent` to tool responses while keeping the existing JSON text in `content`:
  - For successful calls, tools now return both a text block and the raw payload as `structuredContent`.
  - This matches a proven pattern from `yandex-tools-mcp` without changing our tool list.

## Not adopted (yet)
- Session caching and rate limiting: noted as future improvements; we’ll add only if we see real 429/quota pain.
- Auth CLI: nice-to-have; we already have working scripts and docs for `code -> tokens` and refresh.

