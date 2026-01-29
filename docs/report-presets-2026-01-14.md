# Direct report presets (raw)

Use with `direct.report`. These presets provide field lists and selection hints. Adjust dates, filters, and attribution as needed.

## Summary table
| Preset | ReportType | Fields (short) |
| --- | --- | --- |
| Campaign performance | CAMPAIGN_PERFORMANCE_REPORT | Date, CampaignId, Impressions, Clicks, Ctr, Cost, AvgCpc |
| Ad group performance | ADGROUP_PERFORMANCE_REPORT | Date, CampaignId, AdGroupId, Impressions, Clicks, Ctr, Cost, AvgCpc |
| Ad performance | AD_PERFORMANCE_REPORT | Date, CampaignId, AdGroupId, AdId, Impressions, Clicks, Ctr, Cost, AvgCpc |
| Keyword performance | KEYWORDS_PERFORMANCE_REPORT | Date, CampaignId, AdGroupId, KeywordId, Criterion, Impressions, Clicks, Ctr, Cost, AvgCpc |
| Search query performance | SEARCH_QUERY_PERFORMANCE_REPORT | Date, CampaignId, AdGroupId, AdId, Query, Impressions, Clicks, Ctr, Cost |
| Destination URL performance | URL_PERFORMANCE_REPORT | Date, CampaignId, AdGroupId, AdId, Url, Impressions, Clicks, Ctr, Cost |

## Campaign performance (daily)
- report_type: `CAMPAIGN_PERFORMANCE_REPORT`
- field_names: `["Date","CampaignId","Impressions","Clicks","Ctr","Cost","AvgCpc"]`
- order_by: `[{"Field":"Date"}]`
Example:
```json
{
  "tool": "direct.report",
  "arguments": {
    "report_name": "campaign_performance_daily",
    "report_type": "CAMPAIGN_PERFORMANCE_REPORT",
    "date_range_type": "CUSTOM_DATE",
    "date_from": "2026-01-01",
    "date_to": "2026-01-31",
    "field_names": ["Date", "CampaignId", "Impressions", "Clicks", "Ctr", "Cost", "AvgCpc"],
    "order_by": [{"Field": "Date"}]
  }
}
```

## Ad group performance (daily)
- report_type: `ADGROUP_PERFORMANCE_REPORT`
- field_names: `["Date","CampaignId","AdGroupId","Impressions","Clicks","Ctr","Cost","AvgCpc"]`
- order_by: `[{"Field":"Date"}]`
Example:
```json
{
  "tool": "direct.report",
  "arguments": {
    "report_name": "adgroup_performance_daily",
    "report_type": "ADGROUP_PERFORMANCE_REPORT",
    "date_range_type": "CUSTOM_DATE",
    "date_from": "2026-01-01",
    "date_to": "2026-01-31",
    "field_names": ["Date", "CampaignId", "AdGroupId", "Impressions", "Clicks", "Ctr", "Cost", "AvgCpc"],
    "order_by": [{"Field": "Date"}]
  }
}
```

## Ad performance (daily)
- report_type: `AD_PERFORMANCE_REPORT`
- field_names: `["Date","CampaignId","AdGroupId","AdId","Impressions","Clicks","Ctr","Cost","AvgCpc"]`
- order_by: `[{"Field":"Date"}]`
Example:
```json
{
  "tool": "direct.report",
  "arguments": {
    "report_name": "ad_performance_daily",
    "report_type": "AD_PERFORMANCE_REPORT",
    "date_range_type": "CUSTOM_DATE",
    "date_from": "2026-01-01",
    "date_to": "2026-01-31",
    "field_names": ["Date", "CampaignId", "AdGroupId", "AdId", "Impressions", "Clicks", "Ctr", "Cost", "AvgCpc"],
    "order_by": [{"Field": "Date"}]
  }
}
```

## Keyword performance (daily)
- report_type: `KEYWORDS_PERFORMANCE_REPORT`
- field_names: `["Date","CampaignId","AdGroupId","KeywordId","Criterion","Impressions","Clicks","Ctr","Cost","AvgCpc"]`
- order_by: `[{"Field":"Date"}]`
Example:
```json
{
  "tool": "direct.report",
  "arguments": {
    "report_name": "keyword_performance_daily",
    "report_type": "KEYWORDS_PERFORMANCE_REPORT",
    "date_range_type": "CUSTOM_DATE",
    "date_from": "2026-01-01",
    "date_to": "2026-01-31",
    "field_names": ["Date", "CampaignId", "AdGroupId", "KeywordId", "Criterion", "Impressions", "Clicks", "Ctr", "Cost", "AvgCpc"],
    "order_by": [{"Field": "Date"}]
  }
}
```

## Search query performance (daily)
- report_type: `SEARCH_QUERY_PERFORMANCE_REPORT`
- field_names: `["Date","CampaignId","AdGroupId","AdId","Query","Impressions","Clicks","Ctr","Cost"]`
- order_by: `[{"Field":"Date"}]`
Example:
```json
{
  "tool": "direct.report",
  "arguments": {
    "report_name": "search_query_performance_daily",
    "report_type": "SEARCH_QUERY_PERFORMANCE_REPORT",
    "date_range_type": "CUSTOM_DATE",
    "date_from": "2026-01-01",
    "date_to": "2026-01-31",
    "field_names": ["Date", "CampaignId", "AdGroupId", "AdId", "Query", "Impressions", "Clicks", "Ctr", "Cost"],
    "order_by": [{"Field": "Date"}]
  }
}
```

## Destination URL performance (daily)
- report_type: `URL_PERFORMANCE_REPORT`
- field_names: `["Date","CampaignId","AdGroupId","AdId","Url","Impressions","Clicks","Ctr","Cost"]`
- order_by: `[{"Field":"Date"}]`
Example:
```json
{
  "tool": "direct.report",
  "arguments": {
    "report_name": "url_performance_daily",
    "report_type": "URL_PERFORMANCE_REPORT",
    "date_range_type": "CUSTOM_DATE",
    "date_from": "2026-01-01",
    "date_to": "2026-01-31",
    "field_names": ["Date", "CampaignId", "AdGroupId", "AdId", "Url", "Impressions", "Clicks", "Ctr", "Cost"],
    "order_by": [{"Field": "Date"}]
  }
}
```
