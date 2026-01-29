# Dashboard generator (Option 1)

Tool: `dashboard.generate_option1`

Output:
- `*.html` (self-contained dashboard)
- `*.json` (same data, удобен для diff/проверок)

## Common usage patterns

### Single account

Arguments (example):
- `account_id`: profile id from `accounts.json`
- `date_from`: `YYYY-MM-DD`
- `date_to`: `YYYY-MM-DD` (recommend: **yesterday**)
- `output_dir`: where to write files
- `dashboard_slug`: optional, for nicer filenames
- `return_data=false`: avoid token-limit issues in Claude Code

### Multi-account

Use:
- `all_accounts=true`
or
- `account_ids=[...]`

The generated HTML contains an account selector and switches content client-side.

## Notes

- “Today” data can be incomplete in Direct/Metrica; for daily use set `date_to` to yesterday.
- Campaign-level CPL/leads can be “best-effort” and may be gated if Metrica attribution filters fail (to avoid misleading numbers).

