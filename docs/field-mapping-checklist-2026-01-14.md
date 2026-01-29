# Field mapping checklist (Direct + Metrica)

Use this after credentials are available to confirm identifier fields before joins.

## Direct
- Confirm report type supports required identifiers (e.g., CampaignId, AdGroupId, AdId, KeywordId).
- Identify the click identifier field (yclid or equivalent) in the chosen report type.
- Verify field names in Direct dictionaries if unsure (use `direct.list_dictionaries`).

## Metrica
- Confirm Logs API fields include `ym:s:yclid` in your counter.
- Validate `ym:s:startURL` and UTM dimensions return expected values.

## Join checklist
- Ensure date ranges overlap between Direct and Metrica exports.
- Normalize identifiers (string/number format) before joining.
- Keep join keys in lowercase and trim whitespace where applicable.
- Use UTC dates for joins where possible to avoid timezone drift.
- Normalize URLs (lowercase host, remove trailing slashes) before matching landing pages.
- Normalize UTM values (lowercase, URL-decode) before joining.
