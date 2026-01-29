# Data normalization tips (join-ready exports)

Use these tips before joining Direct and Metrica exports.

## IDs and keys
- Cast IDs to strings to avoid integer/string mismatches.
- Trim whitespace and normalize case for text-based keys.

## Dates and timezones
- Convert all dates to UTC (or the same timezone) before joins.
- Store dates in ISO 8601 format.

## URLs and UTMs
- Lowercase hostnames and remove trailing slashes.
- URL-decode UTM values and normalize to lowercase.
- Strip tracking params when matching landing pages (except UTMs used for joins).

## Numeric fields
- Convert cost fields to a consistent unit (e.g., micros to currency).
- Handle missing values as 0 or null consistently.

## Unit conversion (Direct costs)
- Some Direct reports return cost in micros; confirm the unit in the API response.
- Convert micros to currency by dividing by 1000000.

## Currency and timezone alignment
- Capture account currency from Direct dictionaries and store it alongside cost fields.
- Align Direct report timezone with Metrica (use explicit date ranges and UTC where possible).
