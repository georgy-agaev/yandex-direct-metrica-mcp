# Claude Code setup — MCP Yandex Ad (2026-01-27)

Goal: подключить `yandex-direct-metrica-mcp` (legacy alias: `mcp-yandex-ad`) в Claude Code как MCP server и быстро проверить UX (tools + dashboard).

## Option A (recommended): use `.mcp.json` in `~/crew_a`

1) Add a new server entry to `~/crew_a/.mcp.json`:

```json
{
  "mcpServers": {
    "yandexad": {
      "command": "/Users/georgyagaev/mcp/yandex.ad/.venv/bin/yandex-direct-metrica-mcp",
      "args": ["--env-file", "/Users/georgyagaev/mcp/yandex.ad/.env"]
    }
  }
}
```

Notes:
- Default transport is `stdio`, which is what Claude Code expects for local MCP servers.
- Prefer pointing to an env file; do not inline secrets into JSON.

2) Enable the server in `~/crew_a/.claude/settings.local.json`:
- add `"yandexad"` to `enabledMcpjsonServers`.

3) Allow tool calls in `~/crew_a/.claude/settings.local.json`:
- add the minimal set first (and extend as needed):
  - `mcp__yandexad__direct.list_campaigns`
  - `mcp__yandexad__direct.report`
  - `mcp__yandexad__metrica.report`
  - `mcp__yandexad__join.hf.direct_vs_metrica_by_utm`
  - `mcp__yandexad__join.hf.direct_vs_metrica_by_yclid`
  - `mcp__yandexad__dashboard.generate_option1`

If Claude Code shows a “tool not allowed” name, copy that exact name into the allow-list.

4) Restart Claude Code.

## Option B: `claude mcp add ...`

If you prefer CLI-managed config:
```bash
claude mcp add yandex-direct-metrica-mcp -s user -- /Users/georgyagaev/mcp/yandex.ad/.venv/bin/yandex-direct-metrica-mcp --env-file /Users/georgyagaev/mcp/yandex.ad/.env
claude mcp list
```
Then update `~/crew_a/.claude/settings.local.json` allow-list similarly.

## Quick prompts to test UX

### 1) Discover tools
- “List available tools in yandexad and show me the main ones for reporting + joins.”

### 2) UTM join (works well)
- “Сделай join Direct vs Metrica по UTM за последние 30 дней для кампании `<campaign_id>` и счётчика `<counter_id>`. Используй direct_client_login=`<direct_client_login>` и utm_campaign=`<utm_campaign>`.”

### 3) yclid join (best effort)
- “Попробуй join по yclid за вчера для счётчика `<counter_id>` (direct_client_login=`<direct_client_login>`). Объясни join_mode и почему может быть много unmatched.”

## Dashboard generator (Option 1)

Generate HTML+JSON locally:
- Option A (local script): this is **not** an MCP tool; it calls MCP over SSE (`http://localhost:8000/sse` by default), so start the server with SSE transport first (e.g. via `docker-compose.yml`).
```bash
/Users/georgyagaev/mcp/yandex.ad/.venv/bin/python /Users/georgyagaev/mcp/yandex.ad/scripts/generate_dashboard_option1.py \
  --account-id voicexpert \
  --date-from 2026-01-01 \
  --date-to 2026-01-31 \
  --output-dir /Users/georgyagaev/crew_a/voicexpert/dashboard
```

Then open the HTML:
```bash
open /Users/georgyagaev/crew_a/voicexpert/dashboard/yandexad_dashboard__voicexpert__2026-01-01_2026-01-31.html
```

Option B (MCP tool): call `dashboard.generate_option1` (no SSE needed; uses the same server runtime).
- Tip: when using `output_dir`, set `return_data=false` to avoid token-limit issues in Claude Code while still getting `files.html_path` / `files.json_path`.
