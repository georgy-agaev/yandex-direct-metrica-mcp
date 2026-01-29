# Metrics glossary (selected)

Quick reference for fields used in examples. This is not exhaustive.

## Direct reports
- `Impressions`: ad impressions.
- `Clicks`: ad clicks.
- `Ctr`: click-through rate.
- `Cost`: spend (usually in micros, depends on API).
- `AvgCpc`: average cost per click.
- `Conversions`: conversions (requires goals configured).
- `ConversionRate`: conversions / clicks.
- `CostPerConversion`: cost per conversion (requires goals configured).
- `Revenue`: conversion revenue (requires ecommerce or revenue goals).
- `Roi`: return on investment (requires revenue and cost).
- `CampaignId`, `AdGroupId`, `AdId`, `KeywordId`: entity identifiers.
- `Query`: search query text (search query report).
- `Url`: destination URL (URL report).

## Metrica reports
- `ym:s:visits`: visits count.
- `ym:s:pageviews`: pageviews count.
- `ym:s:avgVisitDurationSeconds`: average visit duration in seconds.
- `ym:s:bounceRate`: bounce rate.
- `ym:s:date`: visit date dimension.
- `ym:s:startURL`: landing page URL.
- `ym:s:UTMCampaign`: UTM campaign value.
- `ym:s:UTMSource`: UTM source value.
- `ym:s:UTMMedium`: UTM medium value.
- `ym:s:deviceCategory`: device category.
- `ym:s:regionCity`: city.

## Metrica metrics vs dimensions (quick cheat sheet)
- Metrics: `ym:s:visits`, `ym:s:pageviews`, `ym:s:avgVisitDurationSeconds`, `ym:s:bounceRate`.
- Dimensions: `ym:s:date`, `ym:s:startURL`, `ym:s:UTMCampaign`, `ym:s:UTMSource`, `ym:s:UTMMedium`, `ym:s:deviceCategory`, `ym:s:regionCity`.
