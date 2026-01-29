"""Human-friendly (HF) tools for Yandex Direct."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .hf_common import (
    HFError,
    ResolveResult,
    dedupe_ints,
    ensure_hf_destructive_enabled,
    ensure_hf_enabled,
    ensure_hf_write_enabled,
    hf_payload,
    micros_from_rub,
    should_apply,
    today_plus,
)


def _merge_query(url: str, params: dict[str, str], *, overwrite: bool) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for k, v in params.items():
        if overwrite or k not in query:
            query[k] = v
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _parse_utm_kv(utm: str) -> dict[str, str]:
    return dict(parse_qsl(utm.lstrip("?"), keep_blank_values=True))


def _resolve_campaigns(ctx: Any, *, ids: list[int] | None, name: str | None) -> ResolveResult:
    if ids:
        return ResolveResult(ids=dedupe_ints(ids), matches=[], ambiguous=False)
    if not name:
        raise HFError("campaign_ids or campaign_name is required")

    res = ctx._direct_get(  # type: ignore[attr-defined]
        "campaigns",
        {
            "SelectionCriteria": {},
            "FieldNames": ["Id", "Name", "Type", "Status", "State"],
            "Page": {"Limit": 1000, "Offset": 0},
        },
    )
    items = res.get("result", {}).get("Campaigns", [])
    matches = [c for c in items if isinstance(c, dict) and c.get("Name") == name]
    if not matches:
        matches = [
            c
            for c in items
            if isinstance(c, dict) and isinstance(c.get("Name"), str) and name.lower() in c["Name"].lower()
        ]
    ids_out = [int(c["Id"]) for c in matches if "Id" in c]
    ambiguous = len(ids_out) != 1
    return ResolveResult(ids=ids_out, matches=matches, ambiguous=ambiguous)


def _resolve_adgroups(ctx: Any, *, campaign_id: int | None, adgroup_id: int | None, name: str | None) -> ResolveResult:
    if adgroup_id is not None:
        return ResolveResult(ids=[int(adgroup_id)], matches=[], ambiguous=False)
    if campaign_id is None:
        raise HFError("campaign_id (or campaign_name) is required to resolve adgroups by name")
    if not name:
        raise HFError("adgroup_name is required")

    res = ctx._direct_get(  # type: ignore[attr-defined]
        "adgroups",
        {
            "SelectionCriteria": {"CampaignIds": [int(campaign_id)]},
            "FieldNames": ["Id", "Name", "CampaignId", "Status", "Type"],
            "Page": {"Limit": 1000, "Offset": 0},
        },
    )
    items = res.get("result", {}).get("AdGroups", [])
    matches = [g for g in items if isinstance(g, dict) and g.get("Name") == name]
    if not matches:
        matches = [
            g
            for g in items
            if isinstance(g, dict) and isinstance(g.get("Name"), str) and name.lower() in g["Name"].lower()
        ]
    ids_out = [int(g["Id"]) for g in matches if "Id" in g]
    ambiguous = len(ids_out) != 1
    return ResolveResult(ids=ids_out, matches=matches, ambiguous=ambiguous)


def _campaigns_action_preview(action: str, ids: list[int]) -> dict[str, Any]:
    return {"resource": "campaigns", "method": action, "params": {"SelectionCriteria": {"Ids": ids}}}


def _ads_action_preview(action: str, ids: list[int]) -> dict[str, Any]:
    return {"resource": "ads", "method": action, "params": {"SelectionCriteria": {"Ids": ids}}}


def _keywords_action_preview(action: str, ids: list[int]) -> dict[str, Any]:
    return {"resource": "keywords", "method": action, "params": {"SelectionCriteria": {"Ids": ids}}}


def handle(tool: str, ctx: Any, args: dict[str, Any]) -> dict[str, Any]:
    ensure_hf_enabled(ctx.config)

    # Discovery
    if tool == "direct.hf.find_campaigns":
        res = ctx._direct_get(  # type: ignore[attr-defined]
            "campaigns",
            {
                "SelectionCriteria": {},
                "FieldNames": ["Id", "Name", "Type", "Status", "State"],
                "Page": {"Limit": 1000, "Offset": 0},
            },
        )
        campaigns = [c for c in res.get("result", {}).get("Campaigns", []) if isinstance(c, dict)]
        name_contains = args.get("name_contains")
        if name_contains:
            campaigns = [
                c
                for c in campaigns
                if isinstance(c.get("Name"), str) and name_contains.lower() in c["Name"].lower()
            ]
        if args.get("states"):
            states = set(args["states"])
            campaigns = [c for c in campaigns if c.get("State") in states]
        if args.get("statuses"):
            statuses = set(args["statuses"])
            campaigns = [c for c in campaigns if c.get("Status") in statuses]
        if args.get("types"):
            types = set(args["types"])
            campaigns = [c for c in campaigns if c.get("Type") in types]
        limit = int(args.get("limit") or 50)
        campaigns = campaigns[:limit]
        return hf_payload(tool=tool, status="ok", result={"campaigns": campaigns})

    if tool == "direct.hf.find_adgroups":
        campaign_id = args.get("campaign_id")
        if campaign_id is None and args.get("campaign_name"):
            rr = _resolve_campaigns(ctx, ids=None, name=args.get("campaign_name"))
            if rr.ambiguous:
                return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
            campaign_id = rr.ids[0]
        if campaign_id is None:
            raise HFError("campaign_id or campaign_name is required")
        res = ctx._direct_get(  # type: ignore[attr-defined]
            "adgroups",
            {
                "SelectionCriteria": {"CampaignIds": [int(campaign_id)]},
                "FieldNames": ["Id", "Name", "CampaignId", "Status", "Type", "RegionIds"],
                "Page": {"Limit": 1000, "Offset": 0},
            },
        )
        groups = [g for g in res.get("result", {}).get("AdGroups", []) if isinstance(g, dict)]
        name_contains = args.get("name_contains")
        if name_contains:
            groups = [
                g
                for g in groups
                if isinstance(g.get("Name"), str) and name_contains.lower() in g["Name"].lower()
            ]
        groups = groups[: int(args.get("limit") or 50)]
        return hf_payload(tool=tool, status="ok", result={"adgroups": groups})

    if tool == "direct.hf.find_ads":
        selection: dict[str, Any] = {}
        campaign_id = args.get("campaign_id")
        if campaign_id is None and args.get("campaign_name"):
            rr = _resolve_campaigns(ctx, ids=None, name=args.get("campaign_name"))
            if rr.ambiguous:
                return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
            campaign_id = rr.ids[0]
        if campaign_id is not None:
            selection["CampaignIds"] = [int(campaign_id)]

        adgroup_id = args.get("adgroup_id")
        if adgroup_id is None and args.get("adgroup_name"):
            if campaign_id is None:
                raise HFError("campaign_id/campaign_name is required to resolve adgroup_name")
            rr = _resolve_adgroups(ctx, campaign_id=int(campaign_id), adgroup_id=None, name=args.get("adgroup_name"))
            if rr.ambiguous:
                return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
            adgroup_id = rr.ids[0]
        if adgroup_id is not None:
            selection["AdGroupIds"] = [int(adgroup_id)]

        res = ctx._direct_get(  # type: ignore[attr-defined]
            "ads",
            {
                "SelectionCriteria": selection,
                "FieldNames": ["Id", "CampaignId", "AdGroupId", "Status", "State", "Type", "Subtype"],
                "TextAdFieldNames": ["Title", "Title2", "Href"],
                "Page": {"Limit": 1000, "Offset": 0},
            },
        )
        ads = [a for a in res.get("result", {}).get("Ads", []) if isinstance(a, dict)]
        if args.get("statuses"):
            statuses = set(args["statuses"])
            ads = [a for a in ads if a.get("Status") in statuses]
        title_contains = args.get("title_contains")
        href_contains = args.get("href_contains")
        if title_contains:
            ads = [
                a
                for a in ads
                if isinstance(a.get("TextAd"), dict)
                and isinstance(a["TextAd"].get("Title"), str)
                and title_contains.lower() in a["TextAd"]["Title"].lower()
            ]
        if href_contains:
            ads = [
                a
                for a in ads
                if isinstance(a.get("TextAd"), dict)
                and isinstance(a["TextAd"].get("Href"), str)
                and href_contains.lower() in a["TextAd"]["Href"].lower()
            ]
        ads = ads[: int(args.get("limit") or 50)]
        return hf_payload(tool=tool, status="ok", result={"ads": ads})

    if tool == "direct.hf.find_keywords":
        selection: dict[str, Any] = {}
        campaign_id = args.get("campaign_id")
        if campaign_id is None and args.get("campaign_name"):
            rr = _resolve_campaigns(ctx, ids=None, name=args.get("campaign_name"))
            if rr.ambiguous:
                return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
            campaign_id = rr.ids[0]
        if campaign_id is not None:
            selection["CampaignIds"] = [int(campaign_id)]

        adgroup_id = args.get("adgroup_id")
        if adgroup_id is None and args.get("adgroup_name"):
            if campaign_id is None:
                raise HFError("campaign_id/campaign_name is required to resolve adgroup_name")
            rr = _resolve_adgroups(ctx, campaign_id=int(campaign_id), adgroup_id=None, name=args.get("adgroup_name"))
            if rr.ambiguous:
                return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
            adgroup_id = rr.ids[0]
        if adgroup_id is not None:
            selection["AdGroupIds"] = [int(adgroup_id)]

        res = ctx._direct_get(  # type: ignore[attr-defined]
            "keywords",
            {
                "SelectionCriteria": selection,
                "FieldNames": ["Id", "CampaignId", "AdGroupId", "Keyword", "State", "Status"],
                "Page": {"Limit": 1000, "Offset": 0},
            },
        )
        kws = [k for k in res.get("result", {}).get("Keywords", []) if isinstance(k, dict)]
        contains = args.get("contains")
        if contains:
            kws = [
                k
                for k in kws
                if isinstance(k.get("Keyword"), str) and contains.lower() in k["Keyword"].lower()
            ]
        kws = kws[: int(args.get("limit") or 50)]
        return hf_payload(tool=tool, status="ok", result={"keywords": kws})

    if tool == "direct.hf.get_campaign_summary":
        rr = _resolve_campaigns(ctx, ids=[args["campaign_id"]] if args.get("campaign_id") else None, name=args.get("campaign_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        ids = rr.ids or []
        if not ids:
            raise HFError("campaign not found")
        cid = ids[0]
        adgroups = ctx._direct_get(  # type: ignore[attr-defined]
            "adgroups",
            {"SelectionCriteria": {"CampaignIds": [cid]}, "FieldNames": ["Id"], "Page": {"Limit": 1000, "Offset": 0}},
        ).get("result", {}).get("AdGroups", [])
        ads = ctx._direct_get(  # type: ignore[attr-defined]
            "ads",
            {"SelectionCriteria": {"CampaignIds": [cid]}, "FieldNames": ["Id"], "Page": {"Limit": 1000, "Offset": 0}},
        ).get("result", {}).get("Ads", [])
        kws = ctx._direct_get(  # type: ignore[attr-defined]
            "keywords",
            {"SelectionCriteria": {"CampaignIds": [cid]}, "FieldNames": ["Id"], "Page": {"Limit": 1000, "Offset": 0}},
        ).get("result", {}).get("Keywords", [])
        return hf_payload(
            tool=tool,
            status="ok",
            result={"campaign_id": cid, "counts": {"adgroups": len(adgroups), "ads": len(ads), "keywords": len(kws)}},
        )

    if tool == "direct.hf.get_campaign_assets":
        rr = _resolve_campaigns(ctx, ids=[args["campaign_id"]] if args.get("campaign_id") else None, name=args.get("campaign_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        cid = rr.ids[0]
        res = ctx._direct_get(  # type: ignore[attr-defined]
            "ads",
            {
                "SelectionCriteria": {"CampaignIds": [cid]},
                "FieldNames": ["Id", "AdGroupId", "CampaignId", "Type", "Subtype"],
                "TextAdFieldNames": ["SitelinkSetId", "AdExtensions"],
                "Page": {"Limit": 1000, "Offset": 0},
            },
        )
        ads = [a for a in res.get("result", {}).get("Ads", []) if isinstance(a, dict)]
        sitelinks: set[int] = set()
        callouts: set[int] = set()
        for ad in ads:
            ta = ad.get("TextAd")
            if not isinstance(ta, dict):
                continue
            sid = ta.get("SitelinkSetId")
            if sid is not None:
                try:
                    sitelinks.add(int(sid))
                except Exception:
                    pass
            adext = ta.get("AdExtensions")
            if isinstance(adext, list):
                for e in adext:
                    if isinstance(e, dict) and "AdExtensionId" in e:
                        callouts.add(int(e["AdExtensionId"]))
        return hf_payload(tool=tool, status="ok", result={"campaign_id": cid, "sitelink_set_ids": sorted(sitelinks), "callout_ids": sorted(callouts)})

    # Lifecycle / write tools
    if tool in {"direct.hf.pause_campaigns", "direct.hf.resume_campaigns", "direct.hf.archive_campaigns", "direct.hf.unarchive_campaigns"}:
        ensure_hf_write_enabled(ctx.config)
        action = tool.split(".")[-1].replace("campaigns", "")
        action_map = {
            "pause_": "suspend",
            "resume_": "resume",
            "archive_": "archive",
            "unarchive_": "unarchive",
        }
        method = action_map.get(action)
        if not method:
            raise HFError("Unknown campaign lifecycle action")
        rr = _resolve_campaigns(ctx, ids=args.get("campaign_ids"), name=args.get("campaign_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        preview = _campaigns_action_preview(method, rr.ids)
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview)
        result = ctx._direct_call("campaigns", method, preview["params"])  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool in {"direct.hf.pause_ads", "direct.hf.resume_ads", "direct.hf.archive_ads", "direct.hf.unarchive_ads", "direct.hf.delete_ads", "direct.hf.moderate_ads"}:
        ensure_hf_write_enabled(ctx.config)
        if tool == "direct.hf.delete_ads":
            ensure_hf_destructive_enabled(ctx.config)
        action_map = {
            "direct.hf.pause_ads": "suspend",
            "direct.hf.resume_ads": "resume",
            "direct.hf.archive_ads": "archive",
            "direct.hf.unarchive_ads": "unarchive",
            "direct.hf.delete_ads": "delete",
            "direct.hf.moderate_ads": "moderate",
        }
        method = action_map[tool]
        ad_ids = args.get("ad_ids")
        if not ad_ids:
            if args.get("campaign_id") or args.get("campaign_name"):
                rr = _resolve_campaigns(ctx, ids=[args["campaign_id"]] if args.get("campaign_id") else None, name=args.get("campaign_name"))
                if rr.ambiguous:
                    return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
                cid = rr.ids[0]
                ads = ctx._direct_get(  # type: ignore[attr-defined]
                    "ads",
                    {"SelectionCriteria": {"CampaignIds": [cid]}, "FieldNames": ["Id"], "Page": {"Limit": 1000, "Offset": 0}},
                ).get("result", {}).get("Ads", [])
                ad_ids = [int(a["Id"]) for a in ads if isinstance(a, dict) and "Id" in a]
            else:
                raise HFError("ad_ids or campaign selector is required")
        preview = _ads_action_preview(method, dedupe_ints(ad_ids))
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview)
        result = ctx._direct_call("ads", method, preview["params"])  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.delete_keywords":
        ensure_hf_write_enabled(ctx.config)
        ensure_hf_destructive_enabled(ctx.config)
        ids = args.get("keyword_ids") or []
        if not ids:
            raise HFError("keyword_ids is required")
        preview = _keywords_action_preview("delete", dedupe_ints(ids))
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview)
        result = ctx._direct_call("keywords", "delete", preview["params"])  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.set_campaign_strategy_preset":
        ensure_hf_write_enabled(ctx.config)
        rr = _resolve_campaigns(ctx, ids=[args["campaign_id"]] if args.get("campaign_id") else None, name=args.get("campaign_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        cid = rr.ids[0]
        preset = args.get("preset") or "search_only_highest_position"
        preset_map = {
            "search_only_highest_position": {
                "UnifiedCampaign": {"BiddingStrategy": {"Search": {"BiddingStrategyType": "HIGHEST_POSITION"}, "Network": {"BiddingStrategyType": "SERVING_OFF"}}}
            },
            "search_and_network_highest_position": {
                "UnifiedCampaign": {"BiddingStrategy": {"Search": {"BiddingStrategyType": "HIGHEST_POSITION"}, "Network": {"BiddingStrategyType": "HIGHEST_POSITION"}}}
            },
        }
        patch = preset_map.get(preset)
        if not patch:
            raise HFError(f"Unknown preset: {preset}")
        strategy = patch.get("UnifiedCampaign", {}).get("BiddingStrategy")
        patch_candidates = [
            {"UnifiedCampaign": {"BiddingStrategy": strategy}},
            {"TextCampaign": {"BiddingStrategy": strategy}},
            {"BiddingStrategy": strategy},
        ]
        preview = {"candidate_patches": patch_candidates}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview, message="Strategy schema varies by campaign type; this is a best-effort patch list.")

        last_error: Exception | None = None
        for patch in patch_candidates:
            try:
                result = ctx._direct_call("campaigns", "update", {"Campaigns": [{"Id": cid, **patch}]})  # type: ignore[attr-defined]
                return hf_payload(tool=tool, status="ok", preview={"applied_patch": patch}, result=result)
            except Exception as exc:  # pragma: no cover
                last_error = exc
                continue
        raise HFError(f"Failed to apply strategy patch candidates. Last error: {last_error}")

    if tool == "direct.hf.set_campaign_budget":
        ensure_hf_write_enabled(ctx.config)
        rr = _resolve_campaigns(ctx, ids=[args["campaign_id"]] if args.get("campaign_id") else None, name=args.get("campaign_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        cid = rr.ids[0]
        daily = args.get("daily_budget_rub")
        if daily is None:
            raise HFError("daily_budget_rub is required")
        mode = args.get("mode") or "STANDARD"
        budget_obj = {"Amount": micros_from_rub(daily), "Mode": mode}

        # Best-effort: try common shapes for budget placement.
        patch_candidates = [
            {"TextCampaign": {"DailyBudget": budget_obj}},
            {"UnifiedCampaign": {"DailyBudget": budget_obj}},
            {"DailyBudget": budget_obj},
        ]
        preview = {"candidate_patches": patch_candidates}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview, message="Budget schema varies by campaign type; this is a best-effort patch list.")

        last_error: Exception | None = None
        for patch in patch_candidates:
            try:
                result = ctx._direct_call("campaigns", "update", {"Campaigns": [{"Id": cid, **patch}]})  # type: ignore[attr-defined]
                return hf_payload(tool=tool, status="ok", preview={"applied_patch": patch}, result=result)
            except Exception as exc:  # pragma: no cover
                last_error = exc
                continue
        raise HFError(f"Failed to apply budget patch candidates. Last error: {last_error}")

    if tool == "direct.hf.set_campaign_geo":
        ensure_hf_write_enabled(ctx.config)
        rr = _resolve_campaigns(ctx, ids=[args["campaign_id"]] if args.get("campaign_id") else None, name=args.get("campaign_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        cid = rr.ids[0]
        region_ids = args.get("region_ids") or []
        if not region_ids:
            raise HFError("region_ids is required")
        groups = ctx._direct_get(  # type: ignore[attr-defined]
            "adgroups",
            {"SelectionCriteria": {"CampaignIds": [cid]}, "FieldNames": ["Id"], "Page": {"Limit": 1000, "Offset": 0}},
        ).get("result", {}).get("AdGroups", [])
        updates = [{"Id": int(g["Id"]), "RegionIds": region_ids} for g in groups if isinstance(g, dict) and "Id" in g]
        preview = {"tool": "direct.update_adgroups", "items": updates}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview)
        result = ctx._direct_call("adgroups", "update", {"AdGroups": updates})  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.set_campaign_schedule":
        ensure_hf_write_enabled(ctx.config)
        rr = _resolve_campaigns(ctx, ids=[args["campaign_id"]] if args.get("campaign_id") else None, name=args.get("campaign_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        cid = rr.ids[0]
        time_targeting = args.get("time_targeting")
        if not isinstance(time_targeting, dict):
            raise HFError("time_targeting (object) is required")
        patch = {"TimeTargeting": time_targeting}
        preview = {"tool": "direct.update_campaigns", "items": [{"Id": cid, **patch}]}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview, message="TimeTargeting support depends on campaign type; API may reject the patch.")
        result = ctx._direct_call("campaigns", "update", {"Campaigns": [{"Id": cid, **patch}]})  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.set_campaign_negative_keywords":
        ensure_hf_write_enabled(ctx.config)
        rr = _resolve_campaigns(ctx, ids=[args["campaign_id"]] if args.get("campaign_id") else None, name=args.get("campaign_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        cid = rr.ids[0]
        items = args.get("items") or []
        patch = {"NegativeKeywords": {"Items": items}}
        preview = {"tool": "direct.update_campaigns", "items": [{"Id": cid, **patch}]}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview)
        result = ctx._direct_call("campaigns", "update", {"Campaigns": [{"Id": cid, **patch}]})  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.set_campaign_tracking_params":
        ensure_hf_write_enabled(ctx.config)
        rr = _resolve_campaigns(ctx, ids=[args["campaign_id"]] if args.get("campaign_id") else None, name=args.get("campaign_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        cid = rr.ids[0]
        tracking = args.get("tracking_params")
        if not tracking:
            raise HFError("tracking_params is required")
        patch = {"TrackingParams": tracking}
        preview = {"tool": "direct.update_campaigns", "items": [{"Id": cid, **patch}]}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview, message="TrackingParams support depends on campaign type; API may reject.")
        result = ctx._direct_call("campaigns", "update", {"Campaigns": [{"Id": cid, **patch}]})  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    def _apply_utm_fallback_to_ads(campaign_id: int, utm_template: str, overwrite: bool) -> dict[str, Any]:
        res = ctx._direct_get(  # type: ignore[attr-defined]
            "ads",
            {
                "SelectionCriteria": {"CampaignIds": [campaign_id]},
                "FieldNames": ["Id", "CampaignId", "AdGroupId", "Type", "Subtype"],
                "TextAdFieldNames": ["Href"],
                "Page": {"Limit": 1000, "Offset": 0},
            },
        )
        ads = [a for a in res.get("result", {}).get("Ads", []) if isinstance(a, dict)]
        updates = []
        for ad in ads:
            if ad.get("Type") != "TEXT_AD":
                continue
            ta = ad.get("TextAd")
            if not isinstance(ta, dict):
                continue
            href = ta.get("Href")
            if not isinstance(href, str) or not href:
                continue
            rendered = utm_template.format(campaign_id=ad.get("CampaignId"), adgroup_id=ad.get("AdGroupId"), ad_id=ad.get("Id"))
            kv = _parse_utm_kv(rendered)
            new_href = _merge_query(href, kv, overwrite=overwrite)
            if new_href == href:
                continue
            updates.append({"Id": int(ad["Id"]), "TextAd": {"Href": new_href}})
        return {"updates": updates}

    if tool in {"direct.hf.apply_utm_to_ads", "direct.hf.set_campaign_utm_template"}:
        ensure_hf_write_enabled(ctx.config)
        rr = _resolve_campaigns(ctx, ids=[args["campaign_id"]] if args.get("campaign_id") else None, name=args.get("campaign_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        cid = rr.ids[0]
        utm_template = args.get("utm_template")
        if not utm_template:
            raise HFError("utm_template is required")
        overwrite = bool(args.get("overwrite", False))

        # Try TrackingParams on campaign first.
        tracking = utm_template.lstrip("?")
        preview_track = {"tool": "direct.update_campaigns", "items": [{"Id": cid, "TrackingParams": tracking}]}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview={"tracking_attempt": preview_track, "fallback": "href_rewrite"})

        try:
            result = ctx._direct_call("campaigns", "update", {"Campaigns": [{"Id": cid, "TrackingParams": tracking}]})  # type: ignore[attr-defined]
            return hf_payload(tool=tool, status="ok", preview=preview_track, result=result, message="Applied UTM via TrackingParams (template-first).")
        except Exception:
            # Fallback: rewrite hrefs.
            fb = _apply_utm_fallback_to_ads(cid, utm_template, overwrite)
            preview = {"tool": "direct.update_ads", "items": fb["updates"], "mode": "href_rewrite"}
            if not fb["updates"]:
                return hf_payload(tool=tool, status="ok", preview=preview, result={"note": "No changes needed"})
            result = ctx._direct_call("ads", "update", {"Ads": fb["updates"]})  # type: ignore[attr-defined]
            return hf_payload(tool=tool, status="ok", preview=preview, result=result, message="TrackingParams unsupported; applied UTM by rewriting Href.")

    if tool == "direct.hf.clone_campaign":
        ensure_hf_write_enabled(ctx.config)
        rr = _resolve_campaigns(ctx, ids=[args["campaign_id"]] if args.get("campaign_id") else None, name=args.get("campaign_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        source_id = rr.ids[0]
        new_name = args.get("new_name") or f"Clone {source_id}"

        # 1) Get campaign minimal config (Unified strategy best-effort).
        camp = ctx._direct_call(  # type: ignore[attr-defined]
            "campaigns",
            "get",
            {
                "SelectionCriteria": {"Ids": [source_id]},
                "FieldNames": ["Id", "Name", "Type"],
                "UnifiedCampaignFieldNames": ["BiddingStrategy"],
            },
        )
        campaigns = camp.get("result", {}).get("Campaigns", [])
        if not campaigns:
            raise HFError("Source campaign not found via API")
        src = campaigns[0]
        create_item: dict[str, Any] = {"Name": new_name, "StartDate": today_plus(1)}
        if isinstance(src.get("UnifiedCampaign"), dict):
            create_item["UnifiedCampaign"] = {"BiddingStrategy": src["UnifiedCampaign"].get("BiddingStrategy")}
        preview = {"tool": "direct.create_campaigns", "items": [create_item]}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview, message="Clone creates a new draft campaign and copies structure (adgroups/ads/keywords) best-effort.")

        created = ctx._direct_call("campaigns", "add", {"Campaigns": [create_item]})  # type: ignore[attr-defined]
        add_results = created.get("result", {}).get("AddResults", [])
        if not add_results or "Id" not in add_results[0]:
            return hf_payload(tool=tool, status="error", preview=preview, result=created, message="Failed to create cloned campaign.")
        new_campaign_id = int(add_results[0]["Id"])

        # 2) Clone ad groups.
        groups = ctx._direct_get(  # type: ignore[attr-defined]
            "adgroups",
            {
                "SelectionCriteria": {"CampaignIds": [source_id]},
                "FieldNames": ["Id", "Name", "RegionIds"],
                "Page": {"Limit": 1000, "Offset": 0},
            },
        ).get("result", {}).get("AdGroups", [])
        group_map: dict[int, int] = {}
        group_creates = []
        for g in groups:
            if not isinstance(g, dict) or "Id" not in g:
                continue
            group_creates.append(
                {
                    "Name": g.get("Name"),
                    "CampaignId": new_campaign_id,
                    "RegionIds": g.get("RegionIds") or [],
                }
            )
        if group_creates:
            resp = ctx._direct_call("adgroups", "add", {"AdGroups": group_creates})  # type: ignore[attr-defined]
            new_ids = [int(r["Id"]) for r in resp.get("result", {}).get("AddResults", []) if isinstance(r, dict) and "Id" in r]
            old_ids = [int(g["Id"]) for g in groups if isinstance(g, dict) and "Id" in g]
            for old, new in zip(old_ids, new_ids, strict=False):
                group_map[old] = new

        # 3) Clone keywords.
        kws = ctx._direct_get(  # type: ignore[attr-defined]
            "keywords",
            {"SelectionCriteria": {"CampaignIds": [source_id]}, "FieldNames": ["Id", "AdGroupId", "Keyword"], "Page": {"Limit": 1000, "Offset": 0}},
        ).get("result", {}).get("Keywords", [])
        kw_creates = []
        for kw in kws:
            if not isinstance(kw, dict):
                continue
            if kw.get("Keyword") == "---autotargeting":
                continue
            old_gid = kw.get("AdGroupId")
            if old_gid is None or int(old_gid) not in group_map:
                continue
            kw_creates.append({"AdGroupId": group_map[int(old_gid)], "Keyword": kw.get("Keyword")})
        if kw_creates:
            ctx._direct_call("keywords", "add", {"Keywords": kw_creates})  # type: ignore[attr-defined]

        # 4) Clone ads (TextAd only, best-effort).
        ads = ctx._direct_get(  # type: ignore[attr-defined]
            "ads",
            {
                "SelectionCriteria": {"CampaignIds": [source_id]},
                "FieldNames": ["Id", "AdGroupId", "Type", "Subtype"],
                "TextAdFieldNames": ["Title", "Title2", "Text", "Href", "SitelinkSetId", "AdExtensions"],
                "Page": {"Limit": 1000, "Offset": 0},
            },
        ).get("result", {}).get("Ads", [])
        ad_creates = []
        for ad in ads:
            if not isinstance(ad, dict) or ad.get("Type") != "TEXT_AD":
                continue
            old_gid = ad.get("AdGroupId")
            if old_gid is None or int(old_gid) not in group_map:
                continue
            ta = ad.get("TextAd")
            if not isinstance(ta, dict):
                continue
            new_ta = {k: ta.get(k) for k in ["Title", "Title2", "Text", "Href", "SitelinkSetId"] if ta.get(k) is not None}
            if isinstance(ta.get("AdExtensions"), list):
                new_ta["AdExtensions"] = {"AdExtensionIds": [int(x["AdExtensionId"]) for x in ta["AdExtensions"] if isinstance(x, dict) and "AdExtensionId" in x]}
            ad_creates.append({"AdGroupId": group_map[int(old_gid)], "TextAd": new_ta})
        if ad_creates:
            ctx._direct_call("ads", "add", {"Ads": ad_creates})  # type: ignore[attr-defined]

        return hf_payload(tool=tool, status="ok", result={"source_campaign_id": source_id, "new_campaign_id": new_campaign_id, "adgroup_map": group_map})

    # Ad groups
    if tool == "direct.hf.create_adgroup_simple":
        ensure_hf_write_enabled(ctx.config)
        rr = _resolve_campaigns(ctx, ids=[args["campaign_id"]] if args.get("campaign_id") else None, name=args.get("campaign_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        cid = rr.ids[0]
        name = args.get("name")
        if not name:
            raise HFError("name is required")
        region_ids = args.get("region_ids") or []
        item = {"Name": name, "CampaignId": cid, "RegionIds": region_ids}
        preview = {"tool": "direct.create_adgroups", "items": [item]}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview)
        result = ctx._direct_call("adgroups", "add", {"AdGroups": [item]})  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.update_adgroup_geo":
        ensure_hf_write_enabled(ctx.config)
        campaign_id = args.get("campaign_id")
        if campaign_id is None and args.get("campaign_name"):
            rr = _resolve_campaigns(ctx, ids=None, name=args.get("campaign_name"))
            if rr.ambiguous:
                return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
            campaign_id = rr.ids[0]
        rr = _resolve_adgroups(ctx, campaign_id=int(campaign_id) if campaign_id is not None else None, adgroup_id=args.get("adgroup_id"), name=args.get("adgroup_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        gid = rr.ids[0]
        region_ids = args.get("region_ids") or []
        item = {"Id": gid, "RegionIds": region_ids}
        preview = {"tool": "direct.update_adgroups", "items": [item]}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview)
        result = ctx._direct_call("adgroups", "update", {"AdGroups": [item]})  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.set_adgroup_negative_keywords":
        ensure_hf_write_enabled(ctx.config)
        rr = _resolve_adgroups(ctx, campaign_id=args.get("campaign_id"), adgroup_id=args.get("adgroup_id"), name=args.get("adgroup_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        gid = rr.ids[0]
        items = args.get("items") or []
        item = {"Id": gid, "NegativeKeywords": {"Items": items}}
        preview = {"tool": "direct.update_adgroups", "items": [item]}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview)
        result = ctx._direct_call("adgroups", "update", {"AdGroups": [item]})  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.set_adgroup_tracking_params":
        ensure_hf_write_enabled(ctx.config)
        adgroup_id = args.get("adgroup_id")
        tracking = args.get("tracking_params")
        if adgroup_id is None or not tracking:
            raise HFError("adgroup_id and tracking_params are required")
        item = {"Id": int(adgroup_id), "TrackingParams": tracking}
        preview = {"tool": "direct.update_adgroups", "items": [item]}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview, message="TrackingParams support depends on campaign type; API may reject.")
        result = ctx._direct_call("adgroups", "update", {"AdGroups": [item]})  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.set_adgroup_autotargeting":
        ensure_hf_write_enabled(ctx.config)
        adgroup_id = args.get("adgroup_id")
        enabled = args.get("enabled")
        if adgroup_id is None or enabled is None:
            raise HFError("adgroup_id and enabled are required")
        mode = "ON" if enabled else "OFF"
        patch_candidates = [
            {"Id": int(adgroup_id), "UnifiedAdGroup": {"Autotargeting": {"Mode": mode}}},
            {"Id": int(adgroup_id), "TextAdGroup": {"Autotargeting": {"Mode": mode}}},
            {"Id": int(adgroup_id), "Autotargeting": {"Mode": mode}},
        ]
        preview = {"candidate_patches": patch_candidates}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview, message="Autotargeting field support varies; this is a best-effort patch list.")

        last_error: Exception | None = None
        for patch in patch_candidates:
            try:
                result = ctx._direct_call("adgroups", "update", {"AdGroups": [patch]})  # type: ignore[attr-defined]
                return hf_payload(tool=tool, status="ok", preview={"applied_patch": patch}, result=result)
            except Exception as exc:  # pragma: no cover
                last_error = exc
                continue
        raise HFError(f"Failed to apply autotargeting patch candidates. Last error: {last_error}")

    # Ads / assets
    if tool == "direct.hf.create_text_ads_bulk":
        ensure_hf_write_enabled(ctx.config)
        adgroup_id = args.get("adgroup_id")
        ads = args.get("ads") or []
        if adgroup_id is None or not isinstance(ads, list) or not ads:
            raise HFError("adgroup_id and ads[] are required")
        items = []
        for a in ads:
            if not isinstance(a, dict):
                continue
            text_ad = {k: a.get(k) for k in ["Title", "Title2", "Text", "Href", "SitelinkSetId"] if a.get(k) is not None}
            if a.get("CalloutIds"):
                text_ad["AdExtensions"] = {"AdExtensionIds": a["CalloutIds"]}
            items.append({"AdGroupId": int(adgroup_id), "TextAd": text_ad})
        preview = {"tool": "direct.create_ads", "items": items}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview)
        result = ctx._direct_call("ads", "add", {"Ads": items})  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.update_ads_text_bulk":
        ensure_hf_write_enabled(ctx.config)
        ad_ids = args.get("ad_ids") or []
        patch = args.get("patch") or {}
        if not ad_ids or not isinstance(patch, dict):
            raise HFError("ad_ids and patch are required")
        items = []
        for ad_id in ad_ids:
            items.append({"Id": int(ad_id), "TextAd": {k: v for k, v in patch.items() if v is not None}})
        preview = {"tool": "direct.update_ads", "items": items}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview)
        result = ctx._direct_call("ads", "update", {"Ads": items})  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.attach_sitelinks_to_ads":
        ensure_hf_write_enabled(ctx.config)
        ad_ids = args.get("ad_ids") or []
        sid = args.get("sitelink_set_id")
        if not ad_ids or sid is None:
            raise HFError("ad_ids and sitelink_set_id are required")
        items = [{"Id": int(ad_id), "TextAd": {"SitelinkSetId": int(sid)}} for ad_id in ad_ids]
        preview = {"tool": "direct.update_ads", "items": items}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview)
        result = ctx._direct_call("ads", "update", {"Ads": items})  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.attach_callouts_to_ads":
        ensure_hf_write_enabled(ctx.config)
        ad_ids = args.get("ad_ids") or []
        callouts = args.get("callout_ids") or []
        if not ad_ids or not callouts:
            raise HFError("ad_ids and callout_ids are required")
        items = [{"Id": int(ad_id), "TextAd": {"AdExtensions": {"AdExtensionIds": callouts}}} for ad_id in ad_ids]
        preview = {"tool": "direct.update_ads", "items": items}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview)
        result = ctx._direct_call("ads", "update", {"Ads": items})  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.attach_vcard_to_ads":
        ensure_hf_write_enabled(ctx.config)
        ad_ids = args.get("ad_ids") or []
        vcard_id = args.get("vcard_id")
        if not ad_ids or vcard_id is None:
            raise HFError("ad_ids and vcard_id are required")
        items = [{"Id": int(ad_id), "TextAd": {"VCardId": int(vcard_id)}} for ad_id in ad_ids]
        preview = {"tool": "direct.update_ads", "items": items}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview, message="VCard support may be disabled in your account; API can reject.")
        result = ctx._direct_call("ads", "update", {"Ads": items})  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.create_sitelinks_set":
        ensure_hf_write_enabled(ctx.config)
        sitelinks = args.get("sitelinks") or []
        if not sitelinks:
            raise HFError("sitelinks[] is required")
        preview = {"resource": "sitelinks", "method": "add", "params": {"SitelinksSets": [{"Sitelinks": sitelinks}]}}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview)
        result = ctx._direct_call("sitelinks", "add", preview["params"])  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.create_callouts":
        ensure_hf_write_enabled(ctx.config)
        texts = args.get("texts") or []
        if not texts:
            raise HFError("texts[] is required")
        payload = {"AdExtensions": [{"Callout": {"CalloutText": t}} for t in texts]}
        preview = {"resource": "adextensions", "method": "add", "params": payload}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview)
        result = ctx._direct_call("adextensions", "add", payload)  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.ensure_assets_for_campaign":
        ensure_hf_write_enabled(ctx.config)
        rr = _resolve_campaigns(ctx, ids=[args["campaign_id"]] if args.get("campaign_id") else None, name=args.get("campaign_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        cid = rr.ids[0]
        sitelinks = args.get("sitelinks") or []
        callouts = args.get("callouts") or []
        overwrite = bool(args.get("overwrite", False))

        # Create assets (best effort, always creates new sitelinks set if provided).
        preview: dict[str, Any] = {"steps": []}
        sitelink_set_id = None
        callout_ids: list[int] = []
        if sitelinks:
            preview["steps"].append({"create_sitelinks": {"SitelinksSets": [{"Sitelinks": sitelinks}]}})
        if callouts:
            preview["steps"].append({"create_callouts": {"AdExtensions": [{"Callout": {"CalloutText": t}} for t in callouts]}})

        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview, message="Will create assets and attach to all TEXT_ADs in campaign.")

        if sitelinks:
            res = ctx._direct_call("sitelinks", "add", {"SitelinksSets": [{"Sitelinks": sitelinks}]})  # type: ignore[attr-defined]
            add = res.get("result", {}).get("AddResults", [])
            if add and "Id" in add[0]:
                sitelink_set_id = int(add[0]["Id"])
        if callouts:
            res = ctx._direct_call("adextensions", "add", {"AdExtensions": [{"Callout": {"CalloutText": t}} for t in callouts]})  # type: ignore[attr-defined]
            add = res.get("result", {}).get("AddResults", [])
            callout_ids = [int(r["Id"]) for r in add if isinstance(r, dict) and "Id" in r]

        # Attach to ads.
        ads = ctx._direct_get(  # type: ignore[attr-defined]
            "ads",
            {"SelectionCriteria": {"CampaignIds": [cid]}, "FieldNames": ["Id", "Type"], "Page": {"Limit": 1000, "Offset": 0}},
        ).get("result", {}).get("Ads", [])
        ad_ids = [int(a["Id"]) for a in ads if isinstance(a, dict) and a.get("Type") == "TEXT_AD" and "Id" in a]
        items = []
        for ad_id in ad_ids:
            ta: dict[str, Any] = {}
            if sitelink_set_id is not None:
                ta["SitelinkSetId"] = sitelink_set_id
            if callout_ids:
                ta["AdExtensions"] = {"AdExtensionIds": callout_ids}
            if not ta:
                continue
            items.append({"Id": ad_id, "TextAd": ta})
        if items:
            ctx._direct_call("ads", "update", {"Ads": items})  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", result={"campaign_id": cid, "sitelink_set_id": sitelink_set_id, "callout_ids": callout_ids, "updated_ads": len(items), "overwrite": overwrite})

    # Bids/modifiers
    if tool == "direct.hf.set_keyword_bid":
        ensure_hf_write_enabled(ctx.config)
        keyword_id = args.get("keyword_id")
        bid_rub = args.get("bid_rub")
        if keyword_id is None or bid_rub is None:
            raise HFError("keyword_id and bid_rub are required")
        preview = {"resource": "bids", "method": "set", "params": {"Bids": [{"KeywordId": int(keyword_id), "Bid": micros_from_rub(bid_rub)}]}}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview)
        result = ctx._direct_call("bids", "set", preview["params"])  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.set_keyword_bids_bulk":
        ensure_hf_write_enabled(ctx.config)
        bid_rub = args.get("bid_rub")
        if bid_rub is None:
            raise HFError("bid_rub is required")
        selection: dict[str, Any] = {}
        if args.get("campaign_id") is not None:
            selection["CampaignIds"] = [int(args["campaign_id"])]
        if args.get("adgroup_id") is not None:
            selection["AdGroupIds"] = [int(args["adgroup_id"])]
        if not selection:
            raise HFError("campaign_id or adgroup_id is required")
        kws = ctx._direct_get(  # type: ignore[attr-defined]
            "keywords",
            {"SelectionCriteria": selection, "FieldNames": ["Id", "Keyword"], "Page": {"Limit": 1000, "Offset": 0}},
        ).get("result", {}).get("Keywords", [])
        ids = [int(k["Id"]) for k in kws if isinstance(k, dict) and "Id" in k and k.get("Keyword") != "---autotargeting"]
        preview = {"resource": "bids", "method": "set", "params": {"Bids": [{"KeywordId": kid, "Bid": micros_from_rub(bid_rub)} for kid in ids]}}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview, result={"keyword_count": len(ids)})
        result = ctx._direct_call("bids", "set", preview["params"])  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.set_autotargeting_bid":
        ensure_hf_write_enabled(ctx.config)
        rr = _resolve_campaigns(ctx, ids=[args["campaign_id"]] if args.get("campaign_id") else None, name=args.get("campaign_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        cid = rr.ids[0]
        bid_rub = args.get("bid_rub")
        if bid_rub is None:
            raise HFError("bid_rub is required")
        kws = ctx._direct_get(  # type: ignore[attr-defined]
            "keywords",
            {"SelectionCriteria": {"CampaignIds": [cid]}, "FieldNames": ["Id", "Keyword"], "Page": {"Limit": 1000, "Offset": 0}},
        ).get("result", {}).get("Keywords", [])
        auto_ids = [int(k["Id"]) for k in kws if isinstance(k, dict) and k.get("Keyword") == "---autotargeting" and "Id" in k]
        preview = {"resource": "bids", "method": "set", "params": {"Bids": [{"KeywordId": kid, "Bid": micros_from_rub(bid_rub)} for kid in auto_ids]}}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview, result={"autotargeting_keyword_ids": auto_ids})
        result = ctx._direct_call("bids", "set", preview["params"])  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool == "direct.hf.get_bids_summary":
        rr = _resolve_campaigns(ctx, ids=[args["campaign_id"]] if args.get("campaign_id") else None, name=args.get("campaign_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        cid = rr.ids[0]
        res = ctx._direct_get(  # type: ignore[attr-defined]
            "bids",
            {"SelectionCriteria": {"CampaignIds": [cid]}, "FieldNames": ["Bid", "CampaignId", "KeywordId"], "Page": {"Limit": 1000, "Offset": 0}},
        )
        bids = [b for b in res.get("result", {}).get("Bids", []) if isinstance(b, dict) and b.get("Bid") is not None]
        values = [float(b["Bid"]) for b in bids if isinstance(b.get("Bid"), (int, float))]
        if not values:
            return hf_payload(tool=tool, status="ok", result={"campaign_id": cid, "count": 0})
        avg = sum(values) / len(values)
        return hf_payload(tool=tool, status="ok", result={"campaign_id": cid, "count": len(values), "min": min(values), "avg": avg, "max": max(values)})

    def _set_modifier(mod: dict[str, Any]) -> dict[str, Any]:
        preview = {"resource": "bidmodifiers", "method": "set", "params": {"BidModifiers": [mod]}}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview)
        result = ctx._direct_call("bidmodifiers", "set", preview["params"])  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    if tool in {"direct.hf.set_bid_modifier_mobile", "direct.hf.set_bid_modifier_desktop"}:
        ensure_hf_write_enabled(ctx.config)
        rr = _resolve_campaigns(ctx, ids=[args["campaign_id"]] if args.get("campaign_id") else None, name=args.get("campaign_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        cid = rr.ids[0]
        val = args.get("value_percent")
        if val is None:
            raise HFError("value_percent is required")
        if tool.endswith("mobile"):
            mod = {"CampaignId": cid, "Type": "MOBILE_ADJUSTMENT", "MobileAdjustment": {"BidModifier": int(val)}}
        else:
            mod = {"CampaignId": cid, "Type": "DESKTOP_ADJUSTMENT", "DesktopAdjustment": {"BidModifier": int(val)}}
        return _set_modifier(mod)

    if tool == "direct.hf.set_bid_modifier_demographics":
        ensure_hf_write_enabled(ctx.config)
        rr = _resolve_campaigns(ctx, ids=[args["campaign_id"]] if args.get("campaign_id") else None, name=args.get("campaign_name"))
        if rr.ambiguous:
            return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        cid = rr.ids[0]
        age = args.get("age")
        gender = args.get("gender")
        val = args.get("value_percent")
        if not age or not gender or val is None:
            raise HFError("age, gender, value_percent are required")
        mod = {
            "CampaignId": cid,
            "Type": "DEMOGRAPHICS_ADJUSTMENT",
            "DemographicsAdjustments": [{"Age": age, "Gender": gender, "BidModifier": int(val)}],
        }
        return _set_modifier(mod)

    if tool == "direct.hf.set_bid_modifier_geo":
        ensure_hf_write_enabled(ctx.config)
        cid = args.get("campaign_id")
        region_id = args.get("region_id")
        val = args.get("value_percent")
        if cid is None or region_id is None or val is None:
            raise HFError("campaign_id, region_id, value_percent are required")
        mod = {"CampaignId": int(cid), "Type": "REGIONAL_ADJUSTMENT", "RegionalAdjustments": [{"RegionId": int(region_id), "BidModifier": int(val)}]}
        return _set_modifier(mod)

    if tool == "direct.hf.clear_bid_modifiers":
        ensure_hf_write_enabled(ctx.config)
        cid = args.get("campaign_id")
        if cid is None:
            raise HFError("campaign_id is required")
        types = args.get("types") or []
        # best effort: list modifiers, then delete by ids
        mods = ctx._direct_get(  # type: ignore[attr-defined]
            "bidmodifiers",
            {"SelectionCriteria": {"CampaignIds": [int(cid)]}, "FieldNames": ["Id", "CampaignId", "Type"], "Page": {"Limit": 1000, "Offset": 0}},
        ).get("result", {}).get("BidModifiers", [])
        ids = []
        for m in mods:
            if not isinstance(m, dict) or "Id" not in m:
                continue
            if types and m.get("Type") not in set(types):
                continue
            ids.append(int(m["Id"]))
        preview = {"resource": "bidmodifiers", "method": "delete", "params": {"SelectionCriteria": {"Ids": ids}}}
        if not should_apply(args):
            return hf_payload(tool=tool, status="dry_run", preview=preview, result={"count": len(ids)})
        result = ctx._direct_call("bidmodifiers", "delete", preview["params"])  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", preview=preview, result=result)

    # Reports (presets): keep raw report output
    if tool.startswith("direct.hf.report_"):
        rr = None
        if args.get("campaign_id") or args.get("campaign_name"):
            rr = _resolve_campaigns(ctx, ids=[args["campaign_id"]] if args.get("campaign_id") else None, name=args.get("campaign_name"))
            if rr.ambiguous:
                return hf_payload(tool=tool, status="needs_disambiguation", choices=rr.matches)
        cid = rr.ids[0] if rr else None
        date_from = args.get("date_from")
        date_to = args.get("date_to")
        if not date_from or not date_to:
            raise HFError("date_from and date_to are required")
        # Minimal preset fields; user can still use direct.report directly for custom output.
        if tool == "direct.hf.report_performance":
            fields = ["Date", "CampaignId", "Impressions", "Clicks", "Cost"]
            report_type = "CAMPAIGN_PERFORMANCE_REPORT"
        elif tool == "direct.hf.report_keywords":
            fields = ["Date", "CampaignId", "AdGroupId", "KeywordId", "Impressions", "Clicks", "Cost"]
            report_type = "CRITERIA_PERFORMANCE_REPORT"
        elif tool == "direct.hf.report_ads":
            fields = ["Date", "CampaignId", "AdGroupId", "AdId", "Impressions", "Clicks", "Cost"]
            report_type = "AD_PERFORMANCE_REPORT"
        elif tool == "direct.hf.report_adgroups":
            fields = ["Date", "CampaignId", "AdGroupId", "Impressions", "Clicks", "Cost"]
            report_type = "ADGROUP_PERFORMANCE_REPORT"
        else:
            fields = ["Date", "CampaignId", "Impressions", "Clicks", "Cost"]
            report_type = "CAMPAIGN_PERFORMANCE_REPORT"
        selection = {"DateFrom": date_from, "DateTo": date_to}
        if cid is not None:
            selection["Filter"] = [{"Field": "CampaignId", "Operator": "IN", "Values": [str(cid)]}]
        params = {
            "SelectionCriteria": selection,
            "FieldNames": fields,
            "ReportName": f"HF_{tool}_{date_from}_{date_to}",
            "ReportType": report_type,
            "DateRangeType": "CUSTOM_DATE",
            "Format": "TSV",
            "IncludeVAT": "YES",
            "IncludeDiscount": "NO",
        }
        res = ctx._direct_report(params)  # type: ignore[attr-defined]
        return hf_payload(tool=tool, status="ok", result=res)

    raise HFError(f"Unknown HF Direct tool: {tool}")
