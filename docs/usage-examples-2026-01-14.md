# MCP Yandex Ad - Usage examples

All examples below assume the MCP server is running and available to an MCP client.

## Direct - list campaigns
```json
{
  "tool": "direct.list_campaigns",
  "arguments": {
    "field_names": ["Id", "Name"],
    "selection_criteria": {}
  }
}
```
Required: none.

## Direct - report (campaign performance)
```json
{
  "tool": "direct.report",
  "arguments": {
    "report_name": "campaign_performance",
    "report_type": "CAMPAIGN_PERFORMANCE_REPORT",
    "date_range_type": "CUSTOM_DATE",
    "date_from": "2026-01-01",
    "date_to": "2026-01-31",
    "field_names": ["Date", "CampaignId", "Impressions", "Clicks"],
    "order_by": [{"Field": "Date"}],
    "format": "TSV",
    "include_vat": "YES",
    "include_discount": "YES"
  }
}
```
Required: `field_names`, `report_type` (unless `params` override is used).
Note: Direct may respond with a "report not ready" status. Retry with backoff (see retry example below).

## Direct - list ads
```json
{
  "tool": "direct.list_ads",
  "arguments": {
    "selection_criteria": {"CampaignIds": [123456]},
    "field_names": ["Id", "AdGroupId", "State", "Status"]
  }
}
```
Required: none.

## Direct - pagination example
```json
{
  "tool": "direct.list_campaigns",
  "arguments": {
    "selection_criteria": {},
    "field_names": ["Id", "Name"],
    "page": {"limit": 50, "offset": 0}
  }
}
```
Note: when `LimitedBy` is returned, set `page.offset` to that value for the next request.

## Direct - list ad groups
```json
{
  "tool": "direct.list_adgroups",
  "arguments": {
    "selection_criteria": {"CampaignIds": [123456]},
    "field_names": ["Id", "Name", "CampaignId"]
  }
}
```
Required: none.

## Direct - list keywords
```json
{
  "tool": "direct.list_keywords",
  "arguments": {
    "selection_criteria": {"CampaignIds": [123456]},
    "field_names": ["Id", "Keyword", "AdGroupId"]
  }
}
```
Required: none.

## Direct - create campaigns
```json
{
  "tool": "direct.create_campaigns",
  "arguments": {
    "items": [
      {
        "Name": "Brand campaign",
        "Type": "TEXT_CAMPAIGN"
      }
    ]
  }
}
```
Required: `items` (fields depend on campaign type).
Note: set `MCP_WRITE_ENABLED=true` and use Sandbox or a test account for create/update validation.

## Direct - update campaigns
```json
{
  "tool": "direct.update_campaigns",
  "arguments": {
    "items": [
      {
        "Id": 123456,
        "Name": "Brand campaign - updated"
      }
    ]
  }
}
```
Required: `items` (must include `Id`).

## Direct - create ad groups
```json
{
  "tool": "direct.create_adgroups",
  "arguments": {
    "items": [
      {
        "Name": "Brand group",
        "CampaignId": 123456,
        "RegionIds": [213]
      }
    ]
  }
}
```
Required: `items` (fields depend on campaign type).

## Direct - update ad groups
```json
{
  "tool": "direct.update_adgroups",
  "arguments": {
    "items": [
      {
        "Id": 234567,
        "Name": "Brand group - updated"
      }
    ]
  }
}
```
Required: `items` (must include `Id`).

## Direct - create ads
```json
{
  "tool": "direct.create_ads",
  "arguments": {
    "items": [
      {
        "AdGroupId": 234567,
        "TextAd": {
          "Title": "Brand",
          "Text": "Ad text",
          "Href": "https://example.com"
        }
      }
    ]
  }
}
```
Required: `items` (fields depend on ad type).

## Direct - update ads
```json
{
  "tool": "direct.update_ads",
  "arguments": {
    "items": [
      {
        "Id": 345678,
        "TextAd": {
          "Title": "Brand updated"
        }
      }
    ]
  }
}
```
Required: `items` (must include `Id`).

## Direct - create keywords
```json
{
  "tool": "direct.create_keywords",
  "arguments": {
    "items": [
      {
        "AdGroupId": 234567,
        "Keyword": "brand"
      }
    ]
  }
}
```
Required: `items`.

## Direct - update keywords
```json
{
  "tool": "direct.update_keywords",
  "arguments": {
    "items": [
      {
        "Id": 456789,
        "Keyword": "brand exact"
      }
    ]
  }
}
```
Required: `items` (must include `Id`).

## Direct - list sitelinks
```json
{
  "tool": "direct.list_sitelinks",
  "arguments": {
    "selection_criteria": {},
    "field_names": ["Id", "Sitelinks"]
  }
}
```
Required: none.

## Direct - list vcards
```json
{
  "tool": "direct.list_vcards",
  "arguments": {
    "selection_criteria": {},
    "field_names": ["Id", "Phone", "ContactPerson"]
  }
}
```
Required: none.

## Direct - list ad extensions
```json
{
  "tool": "direct.list_adextensions",
  "arguments": {
    "selection_criteria": {},
    "field_names": ["Id", "Type"]
  }
}
```
Required: none.

## Direct - list bids
```json
{
  "tool": "direct.list_bids",
  "arguments": {
    "selection_criteria": {"CampaignIds": [123456]},
    "field_names": ["CampaignId", "KeywordId", "Bid"]
  }
}
```
Required: none.

## Direct - list bid modifiers
```json
{
  "tool": "direct.list_bidmodifiers",
  "arguments": {
    "selection_criteria": {"CampaignIds": [123456]},
    "field_names": ["CampaignId", "Type", "Multiplier"]
  }
}
```
Required: none.

## Direct - list clients (agency accounts)
```json
{
  "tool": "direct.list_clients",
  "arguments": {
    "selection_criteria": {},
    "field_names": ["ClientId", "Login"]
  }
}
```
Required: none.

## Direct - list dictionaries
```json
{
  "tool": "direct.list_dictionaries",
  "arguments": {
    "dictionary_names": ["Currencies", "Regions"]
  }
}
```
Required: `dictionary_names`.

## Direct - get changes
```json
{
  "tool": "direct.get_changes",
  "arguments": {
    "timestamp": "2026-01-01T00:00:00Z",
    "field_names": ["CampaignId", "AdGroupId"]
  }
}
```
Required: `timestamp`.

## Direct - raw call (campaigns.get)
```json
{
  "tool": "direct.raw_call",
  "arguments": {
    "resource": "campaigns",
    "method": "get",
    "params": {
      "SelectionCriteria": {},
      "FieldNames": ["Id", "Name"]
    }
  }
}
```
Required: `resource`.

## Metrica - list counters
```json
{
  "tool": "metrica.list_counters",
  "arguments": {}
}
```
Required: none.

## Metrica - counter info
```json
{
  "tool": "metrica.counter_info",
  "arguments": {
    "counter_id": "12345678"
  }
}
```
Required: `counter_id`.

## Metrica - create goal (management raw)
```json
{
  "tool": "metrica.raw_call",
  "arguments": {
    "api": "management",
    "resource": "goals",
    "method": "post",
    "data": {
      "goal": {
        "name": "Signup",
        "type": "action",
        "is_retargeting": 0,
        "conditions": [
          {
            "type": "exact",
            "url": "https://example.com/signup"
          }
        ]
      }
    }
  }
}
```

## Metrica - update goal (management raw)
```json
{
  "tool": "metrica.raw_call",
  "arguments": {
    "api": "management",
    "resource": "goal",
    "method": "put",
    "path_args": {"goalId": 10000},
    "data": {
      "goal": {
        "id": 10000,
        "name": "Signup - updated"
      }
    }
  }
}
```

## Metrica - report (visits by day)
```json
{
  "tool": "metrica.report",
  "arguments": {
    "counter_id": "12345678",
    "metrics": "ym:s:visits",
    "dimensions": "ym:s:date",
    "date_from": "2026-01-01",
    "date_to": "2026-01-31",
    "sort": "ym:s:date"
  }
}
```
Required: `counter_id`, `metrics` (unless `params` override is used).
Note: use `limit` + `offset` for paging large responses; reduce date ranges if you hit sampling or timeouts.
Note: if sampling is undesirable, try higher `accuracy` values at the cost of longer response times.

## Metrica - report (landing pages + time on site)
```json
{
  "tool": "metrica.report",
  "arguments": {
    "counter_id": "12345678",
    "metrics": "ym:s:visits,ym:s:avgVisitDurationSeconds",
    "dimensions": "ym:s:startURL",
    "date_from": "2026-01-01",
    "date_to": "2026-01-31",
    "sort": "-ym:s:visits",
    "limit": 50
  }
}
```
Required: `counter_id`, `metrics` (unless `params` override is used).

## Metrica - report (UTM campaign performance)
```json
{
  "tool": "metrica.report",
  "arguments": {
    "counter_id": "12345678",
    "metrics": "ym:s:visits,ym:s:pageviews,ym:s:avgVisitDurationSeconds",
    "dimensions": "ym:s:UTMCampaign",
    "date_from": "2026-01-01",
    "date_to": "2026-01-31",
    "sort": "-ym:s:visits",
    "limit": 100
  }
}
```
Required: `counter_id`, `metrics` (unless `params` override is used).

## Metrica - report (UTM source/medium)
```json
{
  "tool": "metrica.report",
  "arguments": {
    "counter_id": "12345678",
    "metrics": "ym:s:visits,ym:s:pageviews",
    "dimensions": "ym:s:UTMSource,ym:s:UTMMedium",
    "date_from": "2026-01-01",
    "date_to": "2026-01-31",
    "sort": "-ym:s:visits",
    "limit": 100
  }
}
```
Required: `counter_id`, `metrics` (unless `params` override is used).

## Metrica - report (device category)
```json
{
  "tool": "metrica.report",
  "arguments": {
    "counter_id": "12345678",
    "metrics": "ym:s:visits,ym:s:bounceRate",
    "dimensions": "ym:s:deviceCategory",
    "date_from": "2026-01-01",
    "date_to": "2026-01-31",
    "sort": "-ym:s:visits",
    "limit": 10
  }
}
```
Required: `counter_id`, `metrics` (unless `params` override is used).

## Metrica - report (city)
```json
{
  "tool": "metrica.report",
  "arguments": {
    "counter_id": "12345678",
    "metrics": "ym:s:visits",
    "dimensions": "ym:s:regionCity",
    "date_from": "2026-01-01",
    "date_to": "2026-01-31",
    "sort": "-ym:s:visits",
    "limit": 50
  }
}
```
Required: `counter_id`, `metrics` (unless `params` override is used).

## Combined workflow (Direct + Metrica, UTM join)
Step 1: pull Direct campaign performance.
```json
{
  "tool": "direct.report",
  "arguments": {
    "report_name": "campaign_performance_daily",
    "report_type": "CAMPAIGN_PERFORMANCE_REPORT",
    "date_range_type": "CUSTOM_DATE",
    "date_from": "2026-01-01",
    "date_to": "2026-01-31",
    "field_names": ["Date", "CampaignId", "Impressions", "Clicks", "Cost"],
    "order_by": [{"Field": "Date"}]
  }
}
```
Step 2: pull Metrica landing pages filtered by UTM campaign.
```json
{
  "tool": "metrica.report",
  "arguments": {
    "counter_id": "12345678",
    "metrics": "ym:s:visits,ym:s:avgVisitDurationSeconds",
    "dimensions": "ym:s:startURL,ym:s:UTMCampaign",
    "date_from": "2026-01-01",
    "date_to": "2026-01-31",
    "filters": "ym:s:UTMCampaign=='campaign_slug'",
    "sort": "-ym:s:visits",
    "limit": 100
  }
}
```
Note: adjust `filters` syntax per Metrica docs and your UTM naming.

## Combined workflow (Direct + Metrica, yclid join via Logs API)
Step 1: pull Direct report with clicks and a click identifier (if available in report type).
```json
{
  "tool": "direct.report",
  "arguments": {
    "report_name": "clicks_with_yclid",
    "report_type": "CUSTOM_REPORT",
    "date_range_type": "CUSTOM_DATE",
    "date_from": "2026-01-01",
    "date_to": "2026-01-02",
    "field_names": ["Date", "CampaignId", "Clicks", "Cost", "ExternalNetworkID"],
    "order_by": [{"Field": "Date"}]
  }
}
```
Step 2: export Metrica logs with yclid.
```json
{
  "tool": "metrica.logs_export",
  "arguments": {
    "action": "create",
    "counter_id": "12345678",
    "date_from": "2026-01-01",
    "date_to": "2026-01-02",
    "fields": "ym:s:date,ym:s:clientID,ym:s:yclid,ym:s:startURL",
    "source": "visits"
  }
}
```
Step 3: download log parts and join on yclid.
```json
{
  "tool": "metrica.logs_export",
  "arguments": {
    "action": "download",
    "counter_id": "12345678",
    "request_id": "REQUEST_ID",
    "part_number": 0
  }
}
```
Note: verify the correct Direct field for a click identifier in your report type; `ExternalNetworkID` is a placeholder and may differ.

## Metrica - logs export (evaluate)
```json
{
  "tool": "metrica.logs_export",
  "arguments": {
    "action": "evaluate",
    "counter_id": "12345678",
    "date_from": "2026-01-01",
    "date_to": "2026-01-01",
    "fields": "ym:s:date,ym:s:clientID",
    "source": "visits"
  }
}
```
Required: `counter_id`. For `action=create|evaluate`, also `date_from`, `date_to`, `fields`, `source` (unless `params` override is used).

## Metrica - logs export (yclid join example)
```json
{
  "tool": "metrica.logs_export",
  "arguments": {
    "action": "create",
    "counter_id": "12345678",
    "date_from": "2026-01-01",
    "date_to": "2026-01-01",
    "fields": "ym:s:date,ym:s:clientID,ym:s:yclid,ym:s:startURL",
    "source": "visits"
  }
}
```
Required: `counter_id`, `date_from`, `date_to`, `fields`, `source`.

## Metrica - logs export workflow (evaluate → create → download)
Evaluate size:
```json
{
  "tool": "metrica.logs_export",
  "arguments": {
    "action": "evaluate",
    "counter_id": "12345678",
    "date_from": "2026-01-01",
    "date_to": "2026-01-01",
    "fields": "ym:s:date,ym:s:clientID,ym:s:yclid",
    "source": "visits"
  }
}
```
Create export:
```json
{
  "tool": "metrica.logs_export",
  "arguments": {
    "action": "create",
    "counter_id": "12345678",
    "date_from": "2026-01-01",
    "date_to": "2026-01-01",
    "fields": "ym:s:date,ym:s:clientID,ym:s:yclid",
    "source": "visits"
  }
}
```
Download part (use request_id from create result):
```json
{
  "tool": "metrica.logs_export",
  "arguments": {
    "action": "download",
    "counter_id": "12345678",
    "request_id": "REQUEST_ID",
    "part_number": 0
  }
}
```
Note: if the export is split into multiple parts, increment `part_number` and repeat downloads until complete.

Check export status:
```json
{
  "tool": "metrica.logs_export",
  "arguments": {
    "action": "info",
    "counter_id": "12345678",
    "request_id": "REQUEST_ID"
  }
}
```
Note: clean exports after download to avoid hitting quota limits.

Clean export after download:
```json
{
  "tool": "metrica.logs_export",
  "arguments": {
    "action": "clean",
    "counter_id": "12345678",
    "request_id": "REQUEST_ID"
  }
}
```

Cancel export if needed:
```json
{
  "tool": "metrica.logs_export",
  "arguments": {
    "action": "cancel",
    "counter_id": "12345678",
    "request_id": "REQUEST_ID"
  }
}
```

## Metrica - raw call (stats)
```json
{
  "tool": "metrica.raw_call",
  "arguments": {
    "api": "stats",
    "method": "get",
    "params": {
      "ids": "12345678",
      "metrics": "ym:s:visits"
    }
  }
}
```
Required: none (for management/logs, `resource` is required).

## Error response (normalized)
```json
{
  "error": {
    "tool": "metrica.report",
    "type": "YandexMetrikaLimitError",
    "provider": "metrica",
    "error_code": 429,
    "message": "Rate limit",
    "hint": "Rate limit exceeded; retry with backoff.",
    "endpoint": "https://api-metrika.yandex.net/stat/v1/data",
    "request_id": "req-123"
  }
}
```

## Error response (Direct example)
```json
{
  "error": {
    "tool": "direct.report",
    "type": "YandexDirectTokenError",
    "provider": "direct",
    "error_code": 53,
    "request_id": "req-123",
    "message": "Invalid",
    "detail": "OAuth token is missing",
    "hint": "Check access/refresh token and API permissions.",
    "endpoint": "https://api.direct.yandex.com/json/v5/reports"
  }
}
```

## Client-side retry example (pseudo-code)
```python
import time


def call_with_retry(client, tool, args, max_attempts=4):
    backoff = 2
    for attempt in range(1, max_attempts + 1):
        result = client.call_tool(tool, args)
        error = result.get("error")
        if not error:
            return result
        hint = error.get("hint", "")
        if "Rate limit" in hint or "Report not ready" in hint:
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
            continue
        raise RuntimeError(error)
    raise RuntimeError("Max retry attempts exceeded")
```
