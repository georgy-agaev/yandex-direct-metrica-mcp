# MCP Yandex Ad - Usage examples (updates)

This document captures *new* usage patterns added after the initial MVP docs.

## Direct - enable v501

Set in `.env`:
```bash
YANDEX_DIRECT_API_VERSION=v501
```

Use `v501` when you need Unified campaigns or other v501-only features.

## Direct - multi-project access (per-call Client-Login)

If your OAuth token belongs to an agency/representative login that has access to multiple client accounts,
you can override Direct `Client-Login` per tool call using `direct_client_login`:

Tip: to make UIs show a dropdown of known client logins, set `YANDEX_DIRECT_CLIENT_LOGINS` in `.env`.

```json
{
  "tool": "direct.list_campaigns",
  "arguments": {
    "direct_client_login": "elama-16161182",
    "field_names": ["Id", "Name", "Type", "Status", "State"]
  }
}
```

## Direct - create Unified campaign (v501)

```json
{
  "tool": "direct.create_campaigns",
  "arguments": {
    "items": [
      {
        "Name": "MCP unified test-energy.ru",
        "StartDate": "2026-01-17",
        "UnifiedCampaign": {
          "BiddingStrategy": {
            "Search": { "BiddingStrategyType": "HIGHEST_POSITION" },
            "Network": { "BiddingStrategyType": "SERVING_OFF" }
          }
        }
      }
    ]
  }
}
```

Notes:
- `StartDate` must not be earlier than the current date in the account timezone.

## Direct - attach callouts (AdExtensions) to a TextAd

For updates, the API attaches callouts via `CalloutSetting` (not `TextAd.AdExtensions`).

```json
{
  "tool": "direct.update_ads",
  "arguments": {
    "items": [
      {
        "Id": 17541476443,
        "TextAd": {
          "CalloutSetting": {
            "AdExtensions": [
              { "AdExtensionId": 41450823, "Operation": "SET" },
              { "AdExtensionId": 41450824, "Operation": "SET" },
              { "AdExtensionId": 41450825, "Operation": "SET" }
            ]
          }
        }
      }
    ]
  }
}
```

Compatibility note:
- The MCP server also accepts the older shape `TextAd.AdExtensions: {"AdExtensionIds":[...]}` and converts it to `CalloutSetting` for `direct.update_ads`.

Create note:
- For `direct.create_ads` (`ads.add`), callouts must be provided as `TextAd.AdExtensions: {"AdExtensionIds":[...]}`. If you pass `CalloutSetting` on create, the MCP server converts it to the add-compatible `AdExtensions` shape.

## Direct - seed a minimal draft campaign (script)

With the SSE server running (`docker compose up -d --build`):
```bash
./.venv/bin/python scripts/mcp_seed_test_energy.py
```

## Direct - attach sitelinks + callouts (script)

After seeding ads, attach sitelinks + existing callouts (via `direct.raw_call` + `direct.update_ads`):
```bash
./.venv/bin/python scripts/mcp_attach_assets_test_energy.py
```
Notes:
- The script creates missing callouts with texts from `CALLOUT_TEXTS` and reuses existing ones if present.
- The script reuses the existing `SitelinkSetId` from ads when already attached; otherwise it creates a new sitelinks set.

## Direct - list sitelinks / vcards (Ids required)

Some Direct endpoints require Ids even for `get`:

```json
{
  "tool": "direct.list_sitelinks",
  "arguments": { "ids": [1454958643], "field_names": ["Id", "Sitelinks"] }
}
```

```json
{
  "tool": "direct.list_vcards",
  "arguments": { "ids": [1234567890], "field_names": ["Id"] }
}
```

## Direct - UTM template (apply to ad URLs)

```bash
./.venv/bin/python scripts/mcp_apply_utm_templates_to_ads.py \\\n  --campaign-id 706377468 \\\n  --utm 'utm_source=yandex&utm_medium=cpc&utm_campaign={campaign_id}&utm_content={ad_id}'
```

## Accounts registry - use `account_id`

If you run one MCP server for multiple projects, configure `MCP_ACCOUNTS_FILE` and pass `account_id` in calls.
Docs: `docs/accounts-registry-2026-01-27.md`.

Example: Direct read using a profile (server will resolve `direct_client_login`):
```json
{
  "tool": "direct.list_campaigns",
  "arguments": {
    "account_id": "voicexpert",
    "field_names": ["Id", "Name", "Type", "Status", "State"]
  }
}
```

## Join HF - Direct vs Metrica by UTM (daily series)

This tool joins:
- Direct daily performance for a specific campaign id (Direct report), and
- Metrica daily visits filtered by a stable `ym:s:UTMCampaign` value.

Pass `utm_campaign` explicitly if your UTMCampaign naming is not equal to the Direct campaign name.

```json
{
  "tool": "join.hf.direct_vs_metrica_by_utm",
  "arguments": {
    "account_id": "voicexpert",
    "campaign_id": 706377468,
    "utm_campaign": "706377468",
    "date_from": "2026-01-01",
    "date_to": "2026-01-31"
  }
}
```

Notes:
- If the profile has exactly one `metrica_counter_ids`, you can omit `counter_id` (it will be auto-selected).
- Output includes `joined_by_date[]` + `totals` + `raw` datasets.

## Join HF - by yclid (Logs API) → campaign attribution (best effort)

This tool orchestrates Logs API export/download and joins visits to Direct click identifiers.
It is **bounded** (`max_rows`) and **resumable** (`request_id`).

Start join (no request_id yet):
```json
{
  "tool": "join.hf.direct_vs_metrica_by_yclid",
  "arguments": {
    "account_id": "voicexpert",
    "date_from": "2026-01-01",
    "date_to": "2026-01-07",
    "max_wait_seconds": 60,
    "max_rows": 20000
  }
}
```

If the export is still processing, you will get:
- `status=ok`, `result.status=pending`, and a `request_id`.

Resume later:
```json
{
  "tool": "join.hf.direct_vs_metrica_by_yclid",
  "arguments": {
    "account_id": "voicexpert",
    "request_id": "YOUR_REQUEST_ID",
    "date_from": "2026-01-01",
    "date_to": "2026-01-07",
    "max_wait_seconds": 60,
    "max_rows": 20000
  }
}
```

Direct report compatibility:
- Defaults assume Direct report returns columns `CampaignId` + `ClickId` (report type `CUSTOM_REPORT`).
- If your account/report needs different fields, pass overrides:
  - `direct_report_type`
  - `direct_field_names`
  - `direct_click_id_field` / `direct_campaign_id_field`

Known limitations:
- Logs API export can take longer than `max_wait_seconds`; in that case the tool returns `result.status=pending` and you must retry with `request_id`.
- Click identifier field naming in Direct reports can vary by report type/account configuration; treat yclid join as best-effort and be ready to override report params.
- Some counters/sources do not expose `ym:s:yclid` as a Logs API field; the tool falls back to extracting `yclid` from `ym:s:startURL` query params.
- In practice, the most reliable attribution key is often `ym:s:lastDirectClickBanner` (Direct ad id) from Logs API; the tool can fall back to mapping banner id → campaign via `ads.get`.
