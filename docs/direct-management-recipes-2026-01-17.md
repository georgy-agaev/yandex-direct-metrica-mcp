# Direct API management recipes (via MCP)

This doc shows how to manage advanced Direct settings and parameters using the existing MCP tools.

Principle:
- Use first-class tools where available (`direct.update_campaigns`, `direct.update_ads`, etc).
- Use `direct.raw_call` for everything else.

## Prerequisites
- MCP server running with SSE (`docker compose up -d --build`)
- Write enabled:
  - `MCP_WRITE_ENABLED=true`
  - For live (non-sandbox) changes: `MCP_WRITE_SANDBOX_ONLY=false` and `YANDEX_DIRECT_SANDBOX=false`

## Recipes

Safety: scripts that modify bids/budgets/modifiers default to `dry-run`. Add `--apply` to execute.

### 1) Set keyword bids (bulk)

Script:
```bash
./.venv/bin/python scripts/mcp_set_keyword_bids.py --campaign-id 706377468 --bid-rub 30 --apply
```

Raw MCP call equivalent (conceptual):
```json
{
  "tool": "direct.raw_call",
  "arguments": {
    "resource": "bids",
    "method": "set",
    "params": {
      "Bids": [
        { "KeywordId": 123, "Bid": 30000000 }
      ]
    }
  }
}
```

Notes:
- `Bid` is in micros (1 RUB = 1_000_000).

### 1a) Set autotargeting bid (Unified campaigns)

Script:
```bash
./.venv/bin/python scripts/mcp_set_autotargeting_bid.py --campaign-id 706377468 --bid-rub 15 --apply
```

### 2) Update campaign negative keywords

Script:
```bash
./.venv/bin/python scripts/mcp_update_campaign_negatives.py --campaign-id 706377468 --negatives "бесплатно,скачать,вакансия" --apply
```

MCP tool call:
```json
{
  "tool": "direct.update_campaigns",
  "arguments": {
    "items": [
      {
        "Id": 706377468,
        "NegativeKeywords": { "Items": ["бесплатно", "скачать", "вакансия"] }
      }
    ]
  }
}
```

### 3) Suspend/resume/archive/unarchive (template)

Direct resources often support additional lifecycle methods (depends on the entity):
```json
{
  "tool": "direct.raw_call",
  "arguments": {
    "resource": "campaigns",
    "method": "suspend",
    "params": { "SelectionCriteria": { "Ids": [706377468] } }
  }
}
```

If the API rejects a method, keep it as `direct.raw_call` and follow the error detail / expected values.

### 4) Create/Update sitelinks and callouts

Create sitelinks set:
```json
{
  "tool": "direct.raw_call",
  "arguments": {
    "resource": "sitelinks",
    "method": "add",
    "params": {
      "SitelinksSets": [
        {
          "Sitelinks": [
            { "Title": "Каталог", "Href": "https://test-energy.ru/", "Description": "Товары и решения" }
          ]
        }
      ]
    }
  }
}
```

Create callouts:
```json
{
  "tool": "direct.raw_call",
  "arguments": {
    "resource": "adextensions",
    "method": "add",
    "params": {
      "AdExtensions": [
        { "Callout": { "CalloutText": "Доставка по РФ" } }
      ]
    }
  }
}
```

Attach sitelinks + callouts to ads:
```json
{
  "tool": "direct.update_ads",
  "arguments": {
    "items": [
      {
        "Id": 17541577412,
        "TextAd": {
          "SitelinkSetId": 1454958643,
          "AdExtensions": { "AdExtensionIds": [41450823, 41451160] }
        }
      }
    ]
  }
}
```

### 5) Bid modifiers (device/geo/audience adjustments)

Bid modifiers are managed via `direct.raw_call` because their schema evolves.

List existing bid modifiers:
```bash
./.venv/bin/python scripts/mcp_set_bid_modifiers.py --method get --payload '{"SelectionCriteria":{"CampaignIds":[706377468]},"FieldNames":["Id","CampaignId","Type"]}'
```

Apply modifiers (example payload file path):
```bash
./.venv/bin/python scripts/mcp_set_bid_modifiers.py --method set --payload ./my_bidmodifiers_payload.json --apply
```

### 6) Budget / strategy (campaign patch)

Campaign strategy and budget fields depend on campaign type (Text/Unified/etc) and API version.

Recommended workflow:
1) Dump current campaign object via `direct.raw_call` (`campaigns.get`) with the field names you need.
2) Build a minimal patch JSON containing only fields you want to change.
3) Apply it using:

```bash
./.venv/bin/python scripts/mcp_update_campaign_budget_strategy.py --campaign-id 706377468 --patch ./campaign_patch.json --apply
```

### 7) UTM templates (apply to ad URLs)

This applies UTM parameters to `TextAd.Href` for all text ads in a campaign.

```bash
./.venv/bin/python scripts/mcp_apply_utm_templates_to_ads.py \\\n  --campaign-id 706377468 \\\n  --utm 'utm_source=yandex&utm_medium=cpc&utm_campaign={campaign_id}&utm_content={ad_id}'
```

Add `--overwrite` to replace existing UTM keys.

## Notes on v501
- When `YANDEX_DIRECT_API_VERSION=v501`, all Direct endpoints are called as `/json/v501/*`.
- Some resources require `Ids` even for `get` (we enforce this for `direct.list_sitelinks` and `direct.list_vcards`).

## Templates folder
- Ready-to-edit payload templates live in `docs/templates/` (see `docs/templates/README-2026-01-17.md`).
