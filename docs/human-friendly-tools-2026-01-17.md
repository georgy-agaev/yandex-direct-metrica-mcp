# Human-friendly tools layer (design) — 2026-01-17

Goal: add a convenience layer on top of the existing “raw” MCP tools so that an LLM (or a human) can request common actions using small, safe inputs (names, rubles, presets), while the server performs:
- ID lookups and disambiguation
- schema-safe payload building for Direct API
- dry-run previews (default) and explicit apply
- consistent error messages (request_id, endpoint, hint)

Non-goals (for now):
- heavy normalization of returned data
- hiding Direct API concepts completely (we still allow passing raw params/patches)

## Options (3)

### Option A — Add wrapper MCP tools (recommended)
Add new MCP tools like `direct.hf.pause_campaign`, `direct.hf.apply_utm_to_ads`, etc.
Internally they call existing handlers (`direct.list_*`, `direct.update_*`, `direct.raw_call`).

Pros:
- best UX in Claude/Cursor: tool names are self-describing
- centralizes safety (dry-run/apply) and validation
- still keeps raw tools for edge cases

Cons:
- tool catalog grows (need to curate carefully)

### Option B — Keep raw MCP tools, ship only scripts/templates
No new MCP tools, but provide scripts and templates for common operations.

Pros:
- minimal MCP surface area
- very stable

Cons:
- worse UX for interactive MCP clients (harder to “discover”)

### Option C — Separate “hf” as Pro-only plugin/package
Keep read-only wrappers in OSS; move write wrappers to Pro package or Pro image.

Pros:
- clean monetization boundary for create/update
- OSS remains safe by construction

Cons:
- more packaging/release complexity

## Cross-cutting safety rules (hf layer)
- `dry_run` defaults to `true` for all write tools.
- `apply=true` is required to execute write calls.
- All write calls also require existing write guard (`MCP_WRITE_ENABLED` etc.).
- If selector-by-name matches multiple entities, return a disambiguation payload instead of guessing.
- All “money” fields accept user-friendly units (rubles, percent) but are converted to Direct API units.

Execution policy:
- Write executes only when `apply=true`. (No strict `dry_run=false` requirement.)

## Proposed tool naming
Prefix: `direct.hf.*` and `metrica.hf.*`

## Proposed Direct HF tools (phase 1)

### 1) `direct.hf.find_campaign`
Input: `name_contains`, `status?`, `state?`, `limit?`
Output: list of `{id,name,type,status,state}`

### 2) `direct.hf.pause_campaign` / `direct.hf.resume_campaign` / `direct.hf.archive_campaign` / `direct.hf.unarchive_campaign`
Input: `campaign_id?`, `campaign_name?`, `dry_run=true`, `apply=false`
Behavior: resolve campaign → build `campaigns.suspend|resume|archive|unarchive` via `direct.raw_call`
Output: payload preview or API result

### 3) `direct.hf.set_campaign_strategy`
Input: `campaign_id? | campaign_name?`, `preset`, `dry_run=true`, `apply=false`
Preset examples:
- `search_only_highest_position`
- `search_and_network_highest_position`
Behavior: apply a minimal patch via `direct.update_campaigns` (campaign type aware; fallback to “patch only” and let API validate)

### 4) `direct.hf.set_campaign_budget`
Input: `campaign_id? | campaign_name?`, `daily_budget_rub`, `mode` (STANDARD/DISTRIBUTED), `dry_run=true`, `apply=false`
Behavior: map to the correct campaign budget field based on campaign type; if unknown, require `patch` mode.

### 5) `direct.hf.set_bid_modifier`
Input: `campaign_id? | campaign_name?`, `modifier_type`, `value_percent`, `dry_run=true`, `apply=false`
Example types: `mobile`, `desktop`, `demographics`
Behavior: build `bidmodifiers.set` payload via `direct.raw_call`

### 6) `direct.hf.set_autotargeting_bid`
Input: `campaign_id? | campaign_name?`, `bid_rub`, `dry_run=true`, `apply=false`
Behavior: find `---autotargeting` keyword IDs → call `bids.set`

### 7) `direct.hf.apply_utm_to_ads`
Input: `campaign_id? | campaign_name?`, `utm_template`, `overwrite=false`, `dry_run=true`, `apply=false`
Behavior: list ads → build new hrefs → `direct.update_ads`

UTM mode (approved):
- `utm_mode=auto`: attempt TrackingParams/template first; fallback to `Href` rewrite.

## Proposed Metrica HF tools (phase 2, after access is fixed)
- `metrica.hf.list_counters` (plus “is_accessible”)
- `metrica.hf.report_time_series` (day/week/month presets)
- `metrica.hf.report_landing_pages` (startURL dimension + time-on-site metric)
- `metrica.hf.report_utm_campaigns` (utm dimensions)

## Implementation notes (Python)
- Keep wrappers in a separate module (e.g., `src/mcp_yandex_ad/hf.py`).
- Keep schemas small; do lightweight validation without adding heavy deps.
- Reuse existing helpers: paging builder, error normalizer, write guard.
