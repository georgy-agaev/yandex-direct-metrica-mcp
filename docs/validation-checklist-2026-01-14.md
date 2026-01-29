# Validation checklist (real credentials)

Use this checklist after you have working OAuth credentials and counter IDs.

## Pre-flight
- `python scripts/validate_env.py`
- `python scripts/smoke_test.py`
- For write tests: set `MCP_WRITE_ENABLED=true` and `YANDEX_DIRECT_SANDBOX=true`.

## Direct tools
- `direct.list_campaigns`: returns Campaigns list (non-empty if any campaigns exist).
- `direct.list_adgroups`: returns AdGroups list for a known campaign.
- `direct.list_ads`: returns Ads list for a known campaign/adgroup.
- `direct.list_keywords`: returns Keywords list for a known campaign/adgroup.
- `direct.create_campaigns`: create a campaign in Sandbox (or test account).
- `direct.update_campaigns`: update the created campaign name.
- `direct.create_adgroups`: create an ad group for the campaign.
- `direct.update_adgroups`: update the ad group name.
- `direct.create_ads`: create a basic text ad.
- `direct.update_ads`: update ad title/text.
- `direct.create_keywords`: create a keyword for the ad group.
- `direct.update_keywords`: update keyword text.
- `direct.report`: returns TSV data and `columns`.
- `direct.list_clients`: returns Clients list (agency accounts only).
- `direct.list_dictionaries`: returns dictionary data for requested names.
- `direct.get_changes`: returns changes for a valid timestamp.
- `direct.list_sitelinks`: returns sitelinks sets if any exist.
- `direct.list_vcards`: returns vcards if any exist.
- `direct.list_adextensions`: returns ad extensions if any exist.
- `direct.list_bids`: returns bids for campaigns/keywords.
- `direct.list_bidmodifiers`: returns bid modifiers if configured.
- `direct.raw_call`: run `resource=campaigns`, `method=get` as a sanity check.

## Metrica tools
- `metrica.list_counters`: returns counters array.
- `metrica.counter_info`: returns counter details for a known `counter_id`.
- `metrica.report`: returns `data` rows for visits by date.
- `metrica.report`: verify landing pages report (`ym:s:startURL`) returns rows.
- `metrica.report`: verify UTM campaign report (`ym:s:UTMCampaign`) returns rows.
- `metrica.logs_export`: run `action=evaluate` for a 1-day range (requires `date_from`, `date_to`, `fields`, `source`).
- `metrica.raw_call`: run `api=stats`, `method=get` with minimal params.

## Notes
- Some tools may return empty lists depending on account setup.
- `direct.list_clients` is only relevant for agency accounts.
- `metrica.logs_export` may require extra permissions/quotas.
