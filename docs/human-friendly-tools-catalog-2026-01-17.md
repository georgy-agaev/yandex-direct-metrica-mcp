# Human-friendly tools catalog (Direct + Metrica) — 2026-01-17

This document defines the **full approved list** of “human-friendly” (HF) tools we want to support.

HF tools are a convenience layer on top of the existing raw MCP tools (`direct.*`, `metrica.*`), intended to:
- accept small, user-friendly inputs (names, rubles, percents, presets)
- resolve IDs safely (no guessing on ambiguous matches)
- offer safe defaults (dry-run previews)
- keep results easy to read (short summaries + raw payload preview)

## Global HF configuration (server flags)

These flags affect **HF tools only** (raw tools keep current guardrails).

- `HF_ENABLED` (`true|false`, default `true`)
  - If `false`: HF tools are not exposed / return “disabled”.
- `HF_WRITE_ENABLED` (`true|false`, default `false`)
  - If `false`: HF tools that change state return “write disabled”.
  - If `true`: write is still subject to existing write guardrails (`MCP_WRITE_ENABLED`, `MCP_WRITE_SANDBOX_ONLY`, etc).
- `HF_DESTRUCTIVE_ENABLED` (`true|false`, default `false`)
  - If `false`: destructive HF tools (delete) are not exposed / return “destructive disabled”.

HF write tools must also support:
- `dry_run` (default `true`)
- `apply` (default `false`)

Rule: **write executes only when** `apply=true` (dry-run is advisory/preview; not an execution gate).

## UTM mode (approved)

HF UTM tools use `utm_mode=auto`:
- First attempt: Direct tracking template/TrackingParams (where supported for the campaign type / entity level).
- Fallback: rewrite `TextAd.Href` (merge query parameters; optional overwrite).

## Naming convention

- `direct.hf.*`
- `metrica.hf.*`
- (later) `join.hf.*` for Direct+Metrica joins

## Tool catalog

Below is the full list, grouped by domain.

### A) Discovery / navigation (Direct)
1) `direct.hf.find_campaigns`
2) `direct.hf.find_adgroups`
3) `direct.hf.find_ads`
4) `direct.hf.find_keywords`
5) `direct.hf.get_campaign_summary`
6) `direct.hf.get_campaign_assets`

### B) Lifecycle / status management (Direct)
7) `direct.hf.pause_campaigns`
8) `direct.hf.resume_campaigns`
9) `direct.hf.archive_campaigns`
10) `direct.hf.unarchive_campaigns`
11) `direct.hf.moderate_ads`
12) `direct.hf.pause_ads`
13) `direct.hf.resume_ads`
14) `direct.hf.archive_ads`
15) `direct.hf.unarchive_ads`

Destructive (gated by `HF_DESTRUCTIVE_ENABLED`):
16) `direct.hf.delete_ads`
17) `direct.hf.delete_keywords`

### C) Campaign config: budget / strategy / settings (Direct)
18) `direct.hf.set_campaign_strategy_preset`
19) `direct.hf.set_campaign_budget`
20) `direct.hf.set_campaign_geo`
21) `direct.hf.set_campaign_schedule`
22) `direct.hf.set_campaign_negative_keywords`
23) `direct.hf.set_campaign_tracking_params`
24) `direct.hf.set_campaign_utm_template` (implements `utm_mode=auto`)
25) `direct.hf.clone_campaign` (draft clone; optional)

### D) Ad groups: targeting / settings (Direct)
26) `direct.hf.create_adgroup_simple`
27) `direct.hf.update_adgroup_geo`
28) `direct.hf.set_adgroup_negative_keywords`
29) `direct.hf.set_adgroup_autotargeting`
30) `direct.hf.set_adgroup_tracking_params`

### E) Ads: creation / editing / assets (Direct)
31) `direct.hf.create_text_ads_bulk`
32) `direct.hf.update_ads_text_bulk`
33) `direct.hf.apply_utm_to_ads` (implements `utm_mode=auto`)
34) `direct.hf.attach_sitelinks_to_ads`
35) `direct.hf.attach_callouts_to_ads`
36) `direct.hf.attach_vcard_to_ads` (only if supported by account/API)
37) `direct.hf.create_sitelinks_set`
38) `direct.hf.create_callouts`
39) `direct.hf.ensure_assets_for_campaign`

### F) Bids and bid adjustments (Direct)
40) `direct.hf.set_keyword_bid`
41) `direct.hf.set_keyword_bids_bulk`
42) `direct.hf.set_autotargeting_bid`
43) `direct.hf.get_bids_summary`
44) `direct.hf.set_bid_modifier_mobile`
45) `direct.hf.set_bid_modifier_desktop`
46) `direct.hf.set_bid_modifier_demographics`
47) `direct.hf.set_bid_modifier_geo` (if supported)
48) `direct.hf.clear_bid_modifiers`

### G) Reporting (Direct)
49) `direct.hf.report_performance`
50) `direct.hf.report_keywords`
51) `direct.hf.report_ads`
52) `direct.hf.report_adgroups`
53) `direct.hf.report_search_phrases` (if needed)

### H) Discovery / reporting (Metrica)
54) `metrica.hf.list_accessible_counters`
55) `metrica.hf.counter_summary`
56) `metrica.hf.report_time_series`
57) `metrica.hf.report_landing_pages`
58) `metrica.hf.report_utm_campaigns`
59) `metrica.hf.report_geo`
60) `metrica.hf.report_devices`
61) `metrica.hf.logs_export_preset` (optional)

### I) Direct+Metrica joins (later)
62) `join.hf.direct_vs_metrica_by_utm`
63) `join.hf.direct_vs_metrica_by_yclid`
