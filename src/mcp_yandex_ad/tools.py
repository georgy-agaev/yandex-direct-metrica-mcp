"""MCP tool definitions for Yandex Direct + Metrica."""

from mcp.types import Tool

from .config import AppConfig

HF_DESTRUCTIVE_TOOLS = {
    "direct.hf.delete_ads",
    "direct.hf.delete_keywords",
}

ACCOUNT_ID_SCHEMA_BASE = {
    "description": "Project profile id (resolves to Direct Client-Login and optional Metrica counter defaults).",
}

DIRECT_CLIENT_LOGIN_SCHEMA_BASE = {
    "type": "string",
    "description": "Override Direct Client-Login for this call (agency multi-project support).",
}


def _hf_tools() -> list[Tool]:
    # Schemas are intentionally compact; HF layer does ID resolution + builds raw payloads.
    return [
        Tool(
            name="direct.hf.find_campaigns",
            description="Human-friendly: find campaigns by name/status/type.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name_contains": {"type": "string"},
                    "states": {"type": "array", "items": {"type": "string"}},
                    "statuses": {"type": "array", "items": {"type": "string"}},
                    "types": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer"},
                },
            },
        ),
        Tool(
            name="direct.hf.find_adgroups",
            description="Human-friendly: find ad groups by campaign and name.",
            inputSchema={
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "integer"},
                    "campaign_name": {"type": "string"},
                    "name_contains": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        ),
        Tool(
            name="direct.hf.find_ads",
            description="Human-friendly: find ads by campaign/adgroup and title/href filters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "integer"},
                    "campaign_name": {"type": "string"},
                    "adgroup_id": {"type": "integer"},
                    "adgroup_name": {"type": "string"},
                    "title_contains": {"type": "string"},
                    "href_contains": {"type": "string"},
                    "statuses": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer"},
                },
            },
        ),
        Tool(
            name="direct.hf.find_keywords",
            description="Human-friendly: find keywords by campaign/adgroup and substring.",
            inputSchema={
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "integer"},
                    "campaign_name": {"type": "string"},
                    "adgroup_id": {"type": "integer"},
                    "adgroup_name": {"type": "string"},
                    "contains": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        ),
        Tool(
            name="direct.hf.get_campaign_summary",
            description="Human-friendly: summarize campaigns with counts (adgroups/ads/keywords).",
            inputSchema={
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "integer"},
                    "campaign_name": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        ),
        Tool(
            name="direct.hf.get_campaign_assets",
            description="Human-friendly: show sitelinks/callouts/vcards attached in campaign.",
            inputSchema={
                "type": "object",
                "properties": {"campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}},
            },
        ),
        # Campaign lifecycle
        Tool(
            name="direct.hf.pause_campaigns",
            description="Human-friendly: suspend campaigns (by id or name).",
            inputSchema={"type": "object", "properties": {"campaign_ids": {"type": "array", "items": {"type": "integer"}}, "campaign_name": {"type": "string"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.resume_campaigns",
            description="Human-friendly: resume campaigns (by id or name).",
            inputSchema={"type": "object", "properties": {"campaign_ids": {"type": "array", "items": {"type": "integer"}}, "campaign_name": {"type": "string"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.archive_campaigns",
            description="Human-friendly: archive campaigns (by id or name).",
            inputSchema={"type": "object", "properties": {"campaign_ids": {"type": "array", "items": {"type": "integer"}}, "campaign_name": {"type": "string"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.unarchive_campaigns",
            description="Human-friendly: unarchive campaigns (by id or name).",
            inputSchema={"type": "object", "properties": {"campaign_ids": {"type": "array", "items": {"type": "integer"}}, "campaign_name": {"type": "string"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        # Ads lifecycle
        Tool(
            name="direct.hf.moderate_ads",
            description="Human-friendly: send ads for moderation (by ids or campaign).",
            inputSchema={"type": "object", "properties": {"ad_ids": {"type": "array", "items": {"type": "integer"}}, "campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.pause_ads",
            description="Human-friendly: suspend ads.",
            inputSchema={"type": "object", "properties": {"ad_ids": {"type": "array", "items": {"type": "integer"}}, "campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.resume_ads",
            description="Human-friendly: resume ads.",
            inputSchema={"type": "object", "properties": {"ad_ids": {"type": "array", "items": {"type": "integer"}}, "campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.archive_ads",
            description="Human-friendly: archive ads.",
            inputSchema={"type": "object", "properties": {"ad_ids": {"type": "array", "items": {"type": "integer"}}, "campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.unarchive_ads",
            description="Human-friendly: unarchive ads.",
            inputSchema={"type": "object", "properties": {"ad_ids": {"type": "array", "items": {"type": "integer"}}, "campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.delete_ads",
            description="Human-friendly: delete ads (destructive, gated).",
            inputSchema={"type": "object", "properties": {"ad_ids": {"type": "array", "items": {"type": "integer"}}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.delete_keywords",
            description="Human-friendly: delete keywords (destructive, gated).",
            inputSchema={"type": "object", "properties": {"keyword_ids": {"type": "array", "items": {"type": "integer"}}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        # Campaign config + UTM
        Tool(
            name="direct.hf.set_campaign_strategy_preset",
            description="Human-friendly: apply a strategy preset to a campaign.",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "preset": {"type": "string"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.set_campaign_budget",
            description="Human-friendly: set campaign daily budget (rubles) if supported, else returns patch hint.",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "daily_budget_rub": {"type": "number"}, "mode": {"type": "string"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.set_campaign_geo",
            description="Human-friendly: set geo (RegionIds) for all ad groups in a campaign.",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "region_ids": {"type": "array", "items": {"type": "integer"}}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.set_campaign_schedule",
            description="Human-friendly: set campaign schedule/time targeting (best effort).",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "time_targeting": {"type": "object"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.set_campaign_negative_keywords",
            description="Human-friendly: set campaign negative keywords.",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "items": {"type": "array", "items": {"type": "string"}}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.set_campaign_tracking_params",
            description="Human-friendly: set TrackingParams for a campaign (best effort).",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "tracking_params": {"type": "string"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.set_campaign_utm_template",
            description="Human-friendly: apply UTM template to a campaign (utm_mode=auto).",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "utm_template": {"type": "string"}, "overwrite": {"type": "boolean"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.clone_campaign",
            description="Human-friendly: clone campaign structure into a new draft campaign (best effort).",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "new_name": {"type": "string"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        # Adgroups
        Tool(
            name="direct.hf.create_adgroup_simple",
            description="Human-friendly: create a simple ad group under a campaign.",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "name": {"type": "string"}, "region_ids": {"type": "array", "items": {"type": "integer"}}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.update_adgroup_geo",
            description="Human-friendly: set RegionIds for an ad group.",
            inputSchema={"type": "object", "properties": {"adgroup_id": {"type": "integer"}, "adgroup_name": {"type": "string"}, "campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "region_ids": {"type": "array", "items": {"type": "integer"}}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.set_adgroup_negative_keywords",
            description="Human-friendly: set ad group negative keywords.",
            inputSchema={"type": "object", "properties": {"adgroup_id": {"type": "integer"}, "adgroup_name": {"type": "string"}, "campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "items": {"type": "array", "items": {"type": "string"}}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.set_adgroup_autotargeting",
            description="Human-friendly: enable/disable autotargeting (best effort, depends on campaign type).",
            inputSchema={"type": "object", "properties": {"adgroup_id": {"type": "integer"}, "campaign_id": {"type": "integer"}, "enabled": {"type": "boolean"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.set_adgroup_tracking_params",
            description="Human-friendly: set TrackingParams for an ad group.",
            inputSchema={"type": "object", "properties": {"adgroup_id": {"type": "integer"}, "tracking_params": {"type": "string"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        # Ads / assets
        Tool(
            name="direct.hf.create_text_ads_bulk",
            description="Human-friendly: create multiple TextAds in an ad group.",
            inputSchema={"type": "object", "properties": {"adgroup_id": {"type": "integer"}, "ads": {"type": "array", "items": {"type": "object"}}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.update_ads_text_bulk",
            description="Human-friendly: update multiple TextAds fields (title/text/href).",
            inputSchema={"type": "object", "properties": {"ad_ids": {"type": "array", "items": {"type": "integer"}}, "patch": {"type": "object"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.apply_utm_to_ads",
            description="Human-friendly: apply UTM template to ads in a campaign (utm_mode=auto).",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "utm_template": {"type": "string"}, "overwrite": {"type": "boolean"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.attach_sitelinks_to_ads",
            description="Human-friendly: attach an existing sitelinks set to ads.",
            inputSchema={"type": "object", "properties": {"ad_ids": {"type": "array", "items": {"type": "integer"}}, "sitelink_set_id": {"type": "integer"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.attach_callouts_to_ads",
            description="Human-friendly: attach callouts (adextension ids) to ads.",
            inputSchema={"type": "object", "properties": {"ad_ids": {"type": "array", "items": {"type": "integer"}}, "callout_ids": {"type": "array", "items": {"type": "integer"}}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.attach_vcard_to_ads",
            description="Human-friendly: attach vcard id to ads (if supported).",
            inputSchema={"type": "object", "properties": {"ad_ids": {"type": "array", "items": {"type": "integer"}}, "vcard_id": {"type": "integer"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.create_sitelinks_set",
            description="Human-friendly: create a sitelinks set.",
            inputSchema={"type": "object", "properties": {"sitelinks": {"type": "array", "items": {"type": "object"}}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.create_callouts",
            description="Human-friendly: create callouts (AdExtensions CALLOUT).",
            inputSchema={"type": "object", "properties": {"texts": {"type": "array", "items": {"type": "string"}}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.ensure_assets_for_campaign",
            description="Human-friendly: ensure sitelinks+callouts exist and attach to ads in campaign.",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "sitelinks": {"type": "array", "items": {"type": "object"}}, "callouts": {"type": "array", "items": {"type": "string"}}, "overwrite": {"type": "boolean"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        # Bids/modifiers
        Tool(
            name="direct.hf.set_keyword_bid",
            description="Human-friendly: set a bid for a single keyword (rubles).",
            inputSchema={"type": "object", "properties": {"keyword_id": {"type": "integer"}, "bid_rub": {"type": "number"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.set_keyword_bids_bulk",
            description="Human-friendly: set a uniform bid (rubles) for all keywords in a campaign/adgroup.",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "adgroup_id": {"type": "integer"}, "bid_rub": {"type": "number"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.set_autotargeting_bid",
            description="Human-friendly: set bid for ---autotargeting pseudo-keywords (rubles).",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "bid_rub": {"type": "number"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.get_bids_summary",
            description="Human-friendly: summarize bids in a campaign (min/avg/max).",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}}},
        ),
        Tool(
            name="direct.hf.set_bid_modifier_mobile",
            description="Human-friendly: set mobile bid modifier (percent).",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "value_percent": {"type": "integer"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.set_bid_modifier_desktop",
            description="Human-friendly: set desktop bid modifier (percent).",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "value_percent": {"type": "integer"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.set_bid_modifier_demographics",
            description="Human-friendly: set demographics bid modifier (age+gender).",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "age": {"type": "string"}, "gender": {"type": "string"}, "value_percent": {"type": "integer"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.set_bid_modifier_geo",
            description="Human-friendly: set geo bid modifier (best effort).",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "region_id": {"type": "integer"}, "value_percent": {"type": "integer"}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        Tool(
            name="direct.hf.clear_bid_modifiers",
            description="Human-friendly: delete bid modifiers (by campaign/type).",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "types": {"type": "array", "items": {"type": "string"}}, "dry_run": {"type": "boolean"}, "apply": {"type": "boolean"}}},
        ),
        # Reporting presets
        Tool(
            name="direct.hf.report_performance",
            description="Human-friendly: Direct performance report preset (day/week/month).",
            inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "campaign_name": {"type": "string"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}, "granularity": {"type": "string"}}},
        ),
        Tool(name="direct.hf.report_keywords", description="Human-friendly: Direct keyword report preset.", inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}}}),
        Tool(name="direct.hf.report_ads", description="Human-friendly: Direct ads report preset.", inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}}}),
        Tool(name="direct.hf.report_adgroups", description="Human-friendly: Direct adgroups report preset.", inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}}}),
        Tool(name="direct.hf.report_search_phrases", description="Human-friendly: Direct search phrases report preset (optional).", inputSchema={"type": "object", "properties": {"campaign_id": {"type": "integer"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}}}),
        # Metrica HF (will error if no access; kept for discoverability)
        Tool(name="metrica.hf.list_accessible_counters", description="Human-friendly: list accessible counters.", inputSchema={"type": "object", "properties": {}}),
        Tool(name="metrica.hf.counter_summary", description="Human-friendly: counter summary.", inputSchema={"type": "object", "properties": {"counter_id": {"type": "string"}}}),
        Tool(name="metrica.hf.report_time_series", description="Human-friendly: time series report (day/week/month/quarter/year).", inputSchema={"type": "object", "properties": {"counter_id": {"type": "string"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}, "metric": {"type": "string"}, "granularity": {"type": "string"}}}),
        Tool(name="metrica.hf.report_landing_pages", description="Human-friendly: landing pages report.", inputSchema={"type": "object", "properties": {"counter_id": {"type": "string"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}, "limit": {"type": "integer"}}}),
        Tool(name="metrica.hf.report_utm_campaigns", description="Human-friendly: UTM campaigns report.", inputSchema={"type": "object", "properties": {"counter_id": {"type": "string"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}, "limit": {"type": "integer"}}}),
        Tool(name="metrica.hf.report_geo", description="Human-friendly: geo report (country/city).", inputSchema={"type": "object", "properties": {"counter_id": {"type": "string"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}, "level": {"type": "string"}, "limit": {"type": "integer"}}}),
        Tool(name="metrica.hf.report_devices", description="Human-friendly: device report.", inputSchema={"type": "object", "properties": {"counter_id": {"type": "string"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}, "limit": {"type": "integer"}}}),
        Tool(name="metrica.hf.logs_export_preset", description="Human-friendly: logs export preset (optional).", inputSchema={"type": "object", "properties": {"counter_id": {"type": "string"}, "date_from": {"type": "string"}, "date_to": {"type": "string"}}}),
        # Joins
        Tool(
            name="join.hf.direct_vs_metrica_by_utm",
            description="Human-friendly: join Direct daily performance with Metrica daily visits using a stable UTMCampaign value.",
            inputSchema={
                "type": "object",
                "properties": {
                    "campaign_id": {"type": "integer", "description": "Direct campaign id."},
                    "campaign_name": {"type": "string", "description": "Optional campaign name (used to infer utm_campaign)."},
                    "utm_campaign": {"type": "string", "description": "Explicit ym:s:UTMCampaign value to match in Metrica."},
                    "counter_id": {"type": "string", "description": "Metrica counter id."},
                    "date_from": {"type": "string", "description": "YYYY-MM-DD."},
                    "date_to": {"type": "string", "description": "YYYY-MM-DD."},
                },
            },
        ),
        Tool(
            name="join.hf.direct_vs_metrica_by_yclid",
            description="Human-friendly: join Metrica visits (Logs API yclid) with Direct click identifiers (best effort).",
            inputSchema={
                "type": "object",
                "properties": {
                    "counter_id": {"type": "string", "description": "Metrica counter id."},
                    "date_from": {"type": "string", "description": "YYYY-MM-DD."},
                    "date_to": {"type": "string", "description": "YYYY-MM-DD."},
                    "request_id": {"type": "string", "description": "Optional existing Logs API request id to resume."},
                    "max_wait_seconds": {"type": "number", "description": "Max time to wait for Logs export readiness (default: 60)."},
                    "poll_interval_seconds": {"type": "number", "description": "Polling interval for Logs export status (default: 2)."},
                    "max_rows": {"type": "integer", "description": "Max log rows to download/parse (default: 20000)."},
                    "cleanup": {"type": "boolean", "description": "Call logs clean after download (default: true)."},
                    "logs_source": {"type": "string", "description": "Logs API source (default: visits)."},
                    "logs_fields": {"type": "string", "description": "CSV fields list (default: ym:s:dateTime,ym:s:startURL,ym:s:lastDirectClickBanner)."},
                    "logs_delimiter": {"type": "string", "description": "Override delimiter for downloaded logs (default: autodetect)."},
                    "yclid_field": {"type": "string", "description": "Field name for yclid in logs (default: ym:s:yclid)."},
                    "start_url_field": {"type": "string", "description": "Field name for start URL in logs (default: ym:s:startURL)."},
                    "banner_field": {"type": "string", "description": "Field name for Direct banner/ad id in logs (default: ym:s:lastDirectClickBanner)."},
                    "direct_report_type": {"type": "string", "description": "Direct report type (default: CUSTOM_REPORT)."},
                    "direct_field_names": {"type": "array", "items": {"type": "string"}, "description": "Direct report field names (default: [Date, CampaignId, ClickId])."},
                    "direct_click_id_field": {"type": "string", "description": "Column name to use as click id in Direct report (default: ClickId)."},
                    "direct_campaign_id_field": {"type": "string", "description": "Column name to use as campaign id in Direct report (default: CampaignId)."},
                    "direct_max_rows": {"type": "integer", "description": "Max Direct report rows to parse (default: 200000)."},
                },
            },
        ),
    ]


def tool_definitions(config: AppConfig | None = None) -> list[Tool]:
    base = [
        Tool(
            name="dashboard.generate_option1",
            description="Generate a simple HTML+JSON dashboard from Direct+Metrica data (Option 1).",
            inputSchema={
                "type": "object",
                "required": ["date_from", "date_to"],
                "properties": {
                    "date_from": {"type": "string", "description": "YYYY-MM-DD."},
                    "date_to": {"type": "string", "description": "YYYY-MM-DD."},
                    "all_accounts": {
                        "type": "boolean",
                        "description": "When true, generate one dashboard containing data for all configured account profiles (account switcher in UI).",
                    },
                    "account_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional explicit list of account profile ids to include in a multi-account dashboard.",
                    },
                    "counter_id": {"type": "string", "description": "Metrica counter id (optional if account profile has exactly one)."},
                    "goal_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional Metrica goal IDs. When set, dashboard will include leads based on goal{ID}reaches (best effort).",
                    },
                    "dashboard_slug": {"type": "string", "description": "Optional suffix for output file names."},
                    "output_dir": {"type": "string", "description": "When set, write HTML+JSON files to this directory."},
                    "include_raw_reports": {"type": "boolean", "description": "Include raw Direct/Metrica payloads in output data (default: true)."},
                    "include_html": {"type": "boolean", "description": "Include HTML content in response (default: true if output_dir is not set)."},
                    "return_data": {
                        "type": "boolean",
                        "description": "Return the full data payload in response (default: false if output_dir is set, otherwise true).",
                    },
                },
            },
        ),
        Tool(
            name="accounts.list",
            description="List configured project profiles from the accounts registry file.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="accounts.reload",
            description="Reload accounts registry from disk (updates server cache).",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="accounts.upsert",
            description="Create or update a project profile in the accounts registry file.",
            inputSchema={
                "type": "object",
                "required": ["account_id"],
                "properties": {
                    "account_id": {"type": "string", "description": "Profile id (stable, human-friendly)."},
                    "name": {"type": "string", "description": "Optional display name."},
                    "direct_client_login": {
                        "type": "string",
                        "description": "Direct Client-Login for this project (agency child account login).",
                    },
                    "metrica_counter_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional default Metrica counter ids for this project.",
                    },
                    "replace": {
                        "type": "boolean",
                        "description": "When true, replace the whole profile; when false, patch existing fields.",
                    },
                },
            },
        ),
        Tool(
            name="accounts.delete",
            description="Delete a project profile from the accounts registry file.",
            inputSchema={
                "type": "object",
                "required": ["account_id"],
                "properties": {"account_id": {"type": "string", "description": "Profile id to delete."}},
            },
        ),
        Tool(
            name="direct.list_campaigns",
            description="List campaigns from Yandex Direct.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selection_criteria": {
                        "type": "object",
                        "description": "Direct API SelectionCriteria object (optional).",
                    },
                    "field_names": {
                        "type": "array",
                        "description": "Campaign field names (default: Id, Name).",
                        "items": {"type": "string"},
                    },
                    "text_campaign_field_names": {
                        "type": "array",
                        "description": "TextCampaignFieldNames (optional).",
                        "items": {"type": "string"},
                    },
                    "mobile_app_campaign_field_names": {
                        "type": "array",
                        "description": "MobileAppCampaignFieldNames (optional).",
                        "items": {"type": "string"},
                    },
                    "dynamic_text_campaign_field_names": {
                        "type": "array",
                        "description": "DynamicTextCampaignFieldNames (optional).",
                        "items": {"type": "string"},
                    },
                    "cpm_banner_campaign_field_names": {
                        "type": "array",
                        "description": "CpmBannerCampaignFieldNames (optional).",
                        "items": {"type": "string"},
                    },
                    "smart_campaign_field_names": {
                        "type": "array",
                        "description": "SmartCampaignFieldNames (optional).",
                        "items": {"type": "string"},
                    },
                    "page": {
                        "type": "object",
                        "description": "Pagination: {\"limit\": int, \"offset\": int}.",
                        "properties": {
                            "limit": {"type": "integer"},
                            "offset": {"type": "integer"},
                        },
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.list_adgroups",
            description="List ad groups from Yandex Direct.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selection_criteria": {
                        "type": "object",
                        "description": "Direct API SelectionCriteria object (optional).",
                    },
                    "field_names": {
                        "type": "array",
                        "description": "Ad group field names (default: Id, Name).",
                        "items": {"type": "string"},
                    },
                    "page": {
                        "type": "object",
                        "description": "Pagination: {\"limit\": int, \"offset\": int}.",
                        "properties": {
                            "limit": {"type": "integer"},
                            "offset": {"type": "integer"},
                        },
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.list_ads",
            description="List ads from Yandex Direct.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selection_criteria": {
                        "type": "object",
                        "description": "Direct API SelectionCriteria object (optional).",
                    },
                    "field_names": {
                        "type": "array",
                        "description": "Ad field names (default: Id, AdGroupId).",
                        "items": {"type": "string"},
                    },
                    "page": {
                        "type": "object",
                        "description": "Pagination: {\"limit\": int, \"offset\": int}.",
                        "properties": {
                            "limit": {"type": "integer"},
                            "offset": {"type": "integer"},
                        },
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.list_keywords",
            description="List keywords from Yandex Direct.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selection_criteria": {
                        "type": "object",
                        "description": "Direct API SelectionCriteria object (optional).",
                    },
                    "field_names": {
                        "type": "array",
                        "description": "Keyword field names (default: Id, Keyword).",
                        "items": {"type": "string"},
                    },
                    "page": {
                        "type": "object",
                        "description": "Pagination: {\"limit\": int, \"offset\": int}.",
                        "properties": {
                            "limit": {"type": "integer"},
                            "offset": {"type": "integer"},
                        },
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.create_campaigns",
            description="Create campaigns in Yandex Direct.",
            inputSchema={
                "type": "object",
                "required": ["items"],
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Campaign objects to create.",
                        "items": {"type": "object"},
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.update_campaigns",
            description="Update campaigns in Yandex Direct.",
            inputSchema={
                "type": "object",
                "required": ["items"],
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Campaign objects to update (must include Id).",
                        "items": {"type": "object"},
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.create_adgroups",
            description="Create ad groups in Yandex Direct.",
            inputSchema={
                "type": "object",
                "required": ["items"],
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Ad group objects to create.",
                        "items": {"type": "object"},
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.update_adgroups",
            description="Update ad groups in Yandex Direct.",
            inputSchema={
                "type": "object",
                "required": ["items"],
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Ad group objects to update (must include Id).",
                        "items": {"type": "object"},
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.create_ads",
            description="Create ads in Yandex Direct.",
            inputSchema={
                "type": "object",
                "required": ["items"],
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Ad objects to create.",
                        "items": {"type": "object"},
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.update_ads",
            description="Update ads in Yandex Direct.",
            inputSchema={
                "type": "object",
                "required": ["items"],
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Ad objects to update (must include Id).",
                        "items": {"type": "object"},
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.create_keywords",
            description="Create keywords in Yandex Direct.",
            inputSchema={
                "type": "object",
                "required": ["items"],
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Keyword objects to create.",
                        "items": {"type": "object"},
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.update_keywords",
            description="Update keywords in Yandex Direct.",
            inputSchema={
                "type": "object",
                "required": ["items"],
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Keyword objects to update (must include Id).",
                        "items": {"type": "object"},
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.report",
            description="Run a Direct report (raw output).",
            inputSchema={
                "type": "object",
                "required": ["field_names", "report_type"],
                "properties": {
                    "selection_criteria": {
                        "type": "object",
                        "description": "Direct report SelectionCriteria (optional).",
                    },
                    "field_names": {
                        "type": "array",
                        "description": "Report fields (required by Direct API).",
                        "items": {"type": "string"},
                    },
                    "order_by": {
                        "type": "array",
                        "description": "OrderBy array for reports.",
                        "items": {"type": "object"},
                    },
                    "report_name": {"type": "string"},
                    "report_type": {"type": "string"},
                    "date_range_type": {"type": "string"},
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                    "format": {"type": "string"},
                    "include_vat": {"type": "string"},
                    "include_discount": {"type": "string"},
                    "goals": {"type": "array", "items": {"type": "string"}},
                    "attribution_models": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct report params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.list_clients",
            description="List Direct clients (agency use).",
            inputSchema={
                "type": "object",
                "properties": {
                    "selection_criteria": {
                        "type": "object",
                        "description": "Direct API SelectionCriteria object (optional).",
                    },
                    "field_names": {
                        "type": "array",
                        "description": "Client field names (default: ClientId, Login).",
                        "items": {"type": "string"},
                    },
                    "page": {
                        "type": "object",
                        "description": "Pagination: {\"limit\": int, \"offset\": int}.",
                        "properties": {
                            "limit": {"type": "integer"},
                            "offset": {"type": "integer"},
                        },
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.list_dictionaries",
            description="Get Direct dictionaries.",
            inputSchema={
                "type": "object",
                "required": ["dictionary_names"],
                "properties": {
                    "dictionary_names": {
                        "type": "array",
                        "description": "Dictionary names to fetch (required by API).",
                        "items": {"type": "string"},
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.get_changes",
            description="Get changes since a given timestamp.",
            inputSchema={
                "type": "object",
                "required": ["timestamp"],
                "properties": {
                    "timestamp": {
                        "type": "string",
                        "description": "Timestamp string as required by Direct Changes.checkCampaigns.",
                    },
                    "field_names": {
                        "type": "array",
                        "description": "Fields for changes response (optional).",
                        "items": {"type": "string"},
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.list_sitelinks",
            description="List sitelinks sets.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ids": {
                        "type": "array",
                        "description": "Sitelinks set Ids (required unless using params override).",
                        "items": {"type": "integer"},
                    },
                    "selection_criteria": {
                        "type": "object",
                        "description": "Direct API SelectionCriteria object (optional).",
                    },
                    "field_names": {
                        "type": "array",
                        "description": "Sitelinks field names (default: Id, Sitelinks).",
                        "items": {"type": "string"},
                    },
                    "page": {
                        "type": "object",
                        "description": "Pagination: {\"limit\": int, \"offset\": int}.",
                        "properties": {
                            "limit": {"type": "integer"},
                            "offset": {"type": "integer"},
                        },
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.list_vcards",
            description="List vCards.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ids": {
                        "type": "array",
                        "description": "vCard Ids (required unless using params override).",
                        "items": {"type": "integer"},
                    },
                    "selection_criteria": {
                        "type": "object",
                        "description": "Direct API SelectionCriteria object (optional).",
                    },
                    "field_names": {
                        "type": "array",
                        "description": "VCard field names (default: Id).",
                        "items": {"type": "string"},
                    },
                    "page": {
                        "type": "object",
                        "description": "Pagination: {\"limit\": int, \"offset\": int}.",
                        "properties": {
                            "limit": {"type": "integer"},
                            "offset": {"type": "integer"},
                        },
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.list_adextensions",
            description="List ad extensions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selection_criteria": {
                        "type": "object",
                        "description": "Direct API SelectionCriteria object (optional).",
                    },
                    "field_names": {
                        "type": "array",
                        "description": "Ad extension field names (default: Id).",
                        "items": {"type": "string"},
                    },
                    "page": {
                        "type": "object",
                        "description": "Pagination: {\"limit\": int, \"offset\": int}.",
                        "properties": {
                            "limit": {"type": "integer"},
                            "offset": {"type": "integer"},
                        },
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.list_bids",
            description="List bids.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selection_criteria": {
                        "type": "object",
                        "description": "Direct API SelectionCriteria object (optional).",
                    },
                    "field_names": {
                        "type": "array",
                        "description": "Bid field names (default: CampaignId, KeywordId).",
                        "items": {"type": "string"},
                    },
                    "page": {
                        "type": "object",
                        "description": "Pagination: {\"limit\": int, \"offset\": int}.",
                        "properties": {
                            "limit": {"type": "integer"},
                            "offset": {"type": "integer"},
                        },
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.list_bidmodifiers",
            description="List bid modifiers.",
            inputSchema={
                "type": "object",
                "properties": {
                    "selection_criteria": {
                        "type": "object",
                        "description": "Direct API SelectionCriteria object (optional).",
                    },
                    "field_names": {
                        "type": "array",
                        "description": "Bid modifier field names (default: CampaignId).",
                        "items": {"type": "string"},
                    },
                    "page": {
                        "type": "object",
                        "description": "Pagination: {\"limit\": int, \"offset\": int}.",
                        "properties": {
                            "limit": {"type": "integer"},
                            "offset": {"type": "integer"},
                        },
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Direct params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="direct.raw_call",
            description="Raw Direct API call (escape hatch).",
            inputSchema={
                "type": "object",
                "required": ["resource"],
                "properties": {
                    "resource": {
                        "type": "string",
                        "description": "Direct resource name, e.g. campaigns, ads.",
                    },
                    "method": {
                        "type": "string",
                        "description": "Direct API method, e.g. get, add, update.",
                    },
                    "params": {
                        "type": "object",
                        "description": "Direct API params payload.",
                    },
                },
            },
        ),
        Tool(
            name="metrica.list_counters",
            description="List available Metrica counters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "params": {
                        "type": "object",
                        "description": "Raw Metrica management params override (optional).",
                    }
                },
            },
        ),
        Tool(
            name="metrica.report",
            description="Run a Metrica report (raw output).",
            inputSchema={
                "type": "object",
                "required": ["counter_id", "metrics"],
                "properties": {
                    "counter_id": {
                        "type": "string",
                        "description": "Metrica counter ID (required).",
                    },
                    "metrics": {
                        "type": "string",
                        "description": "Metrics string, e.g. ym:s:visits.",
                    },
                    "dimensions": {
                        "type": "string",
                        "description": "Dimensions string, e.g. ym:s:date.",
                    },
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                    "filters": {"type": "string"},
                    "sort": {"type": "string"},
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"},
                    "accuracy": {"type": "string"},
                    "params": {
                        "type": "object",
                        "description": "Raw Metrica stats params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="metrica.counter_info",
            description="Get details of a Metrica counter.",
            inputSchema={
                "type": "object",
                "required": ["counter_id"],
                "properties": {
                    "counter_id": {
                        "type": "string",
                        "description": "Metrica counter ID (required).",
                    },
                    "params": {
                        "type": "object",
                        "description": "Raw Metrica management params override (optional).",
                    },
                },
            },
        ),
        Tool(
            name="metrica.logs_export",
            description="Logs API export (optional).",
            inputSchema={
                "type": "object",
                "required": ["counter_id"],
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Logs API action: allinfo, info, download, clean, cancel, create, evaluate.",
                    },
                    "counter_id": {"type": "string"},
                    "request_id": {"type": "string"},
                    "part_number": {"type": "integer"},
                    "date_from": {"type": "string"},
                    "date_to": {"type": "string"},
                    "fields": {"type": "string"},
                    "source": {"type": "string"},
                    "params": {
                        "type": "object",
                        "description": "Raw Logs API params override (advanced).",
                    },
                },
            },
        ),
        Tool(
            name="metrica.raw_call",
            description="Raw Metrica API call (escape hatch).",
            inputSchema={
                "type": "object",
                "properties": {
                    "api": {
                        "type": "string",
                        "description": "Metrica API: stats, management, logs.",
                    },
                    "resource": {
                        "type": "string",
                        "description": "Management resource or logs action.",
                    },
                    "method": {
                        "type": "string",
                        "description": "HTTP method: get, post, put, delete.",
                    },
                    "path_args": {
                        "type": "object",
                        "description": "Path args for resource (e.g., counterId).",
                    },
                    "params": {
                        "type": "object",
                        "description": "Query/body params for the request.",
                    },
                    "data": {
                        "type": "object",
                        "description": "Request body for management API (create/update).",
                    },
                },
            },
        ),
    ]

    hf = _hf_tools()
    # Public read-only mode: expose only read-oriented tools (hide write + escape hatches by default).
    if config is not None and getattr(config, "public_readonly", False):
        # Hide write-capable tools from the published schema. Server-side guardrail still blocks any attempts.
        hide_prefixes = ("direct.create_", "direct.update_")
        hide_exact = {"direct.raw_call", "metrica.raw_call"}
        base = [t for t in base if not t.name.startswith(hide_prefixes) and t.name not in hide_exact]
        # Keep only read-oriented HF tools (find/get/report). Write HF tools remain available in pro builds.
        allowed_hf_prefixes = ("direct.hf.find_", "direct.hf.get_", "direct.hf.report_")
        allowed_hf_exact = {"direct.hf.get_bids_summary"}
        hf = [
            t
            for t in hf
            if not t.name.startswith("direct.hf.")
            or t.name.startswith(allowed_hf_prefixes)
            or t.name in allowed_hf_exact
        ]

    direct_client_logins: list[str] = []
    if config is not None and getattr(config, "direct_client_logins", None):
        direct_client_logins = [str(x) for x in config.direct_client_logins if str(x).strip()]

    account_ids: list[str] = []
    if config is not None and getattr(config, "accounts", None):
        account_ids = sorted([str(x) for x in (config.accounts or {}).keys() if str(x).strip()])

    def _inject_account_and_overrides(tools: list[Tool]) -> list[Tool]:
        for tool in tools:
            is_direct_or_join = tool.name.startswith(("direct.", "join.hf."))
            is_metrica = tool.name.startswith("metrica.")
            is_dashboard = tool.name.startswith("dashboard.")
            if not (is_direct_or_join or is_metrica or is_dashboard):
                continue
            schema = tool.inputSchema or {"type": "object"}
            if not isinstance(schema, dict):
                continue
            props = schema.setdefault("properties", {})
            if isinstance(props, dict):
                # Allow any string, but provide an enum hint when we have known ids.
                if account_ids:
                    account_id_schema = {
                        "anyOf": [
                            {"type": "string", "enum": account_ids},
                            {"type": "string"},
                        ],
                        **ACCOUNT_ID_SCHEMA_BASE,
                    }
                else:
                    account_id_schema = {"type": "string", **ACCOUNT_ID_SCHEMA_BASE}
                props.setdefault("account_id", account_id_schema)
                if account_ids and isinstance(props.get("account_ids"), dict):
                    # Multi-account dashboards: suggest known ids, but don't enforce (users may have more).
                    items_schema = {
                        "anyOf": [
                            {"type": "string", "enum": account_ids},
                            {"type": "string"},
                        ],
                    }
                    try:
                        props["account_ids"].setdefault("items", items_schema)
                    except Exception:
                        pass

                if is_direct_or_join or is_dashboard:
                    direct_client_login_schema = dict(DIRECT_CLIENT_LOGIN_SCHEMA_BASE)
                    if direct_client_logins:
                        direct_client_login_schema["enum"] = direct_client_logins
                    props.setdefault("direct_client_login", direct_client_login_schema)
            tool.inputSchema = schema
        return tools

    if config is None:
        return _inject_account_and_overrides(base + hf)
    if not config.hf_enabled:
        return _inject_account_and_overrides(base)
    if not config.hf_destructive_enabled:
        hf = [t for t in hf if t.name not in HF_DESTRUCTIVE_TOOLS]
    return _inject_account_and_overrides(base + hf)
