"""Attach sitelinks + callouts to the seeded test-energy.ru ads (draft).

Creates:
- a sitelinks set (via `direct.raw_call` -> `sitelinks.add`)
Attaches to all ads under the ad group:
- `TextAd.SitelinkSetId`
- callouts (via `direct.update_ads` using AdExtensionIds shape)

Requirements:
- MCP server running with SSE transport
- `MCP_WRITE_ENABLED=true`
- if using live API: `MCP_WRITE_SANDBOX_ONLY=false` and `YANDEX_DIRECT_SANDBOX=false`
"""

from __future__ import annotations

import json

import anyio

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


SSE_URL = "http://localhost:8000/sse"

CAMPAIGN_NAME = "MCP test-energy.ru"
ADGROUP_NAME = "MCP test-energy.ru / RU+Moscow"

TARGET_URL = "https://test-energy.ru/"

CALLOUT_TEXTS = [
    "Доставка по РФ",
    "Подбор инженером",
    "Оплата по счету",
]


def _parse(res) -> dict:
    return json.loads(res.content[0].text)


async def _find_campaign_id(session: ClientSession) -> int:
    res = await session.call_tool("direct.list_campaigns", arguments={"field_names": ["Id", "Name"]})
    data = _parse(res)
    campaigns = data.get("result", {}).get("Campaigns", [])
    for campaign in campaigns:
        if campaign.get("Name") == CAMPAIGN_NAME:
            return int(campaign["Id"])
    raise RuntimeError(f"Campaign not found: {CAMPAIGN_NAME}")


async def _find_adgroup_id(session: ClientSession, campaign_id: int) -> int:
    res = await session.call_tool(
        "direct.list_adgroups",
        arguments={
            "selection_criteria": {"CampaignIds": [campaign_id]},
            "field_names": ["Id", "Name"],
        },
    )
    data = _parse(res)
    groups = data.get("result", {}).get("AdGroups", [])
    for group in groups:
        if group.get("Name") == ADGROUP_NAME:
            return int(group["Id"])
    raise RuntimeError(f"Ad group not found: {ADGROUP_NAME}")


async def _list_ads_for_update(session: ClientSession, adgroup_id: int) -> list[dict]:
    res = await session.call_tool(
        "direct.list_ads",
        arguments={
            "params": {
                "SelectionCriteria": {"AdGroupIds": [adgroup_id]},
                "FieldNames": ["Id", "AdGroupId", "CampaignId", "Status", "State", "Type", "Subtype"],
                "TextAdFieldNames": ["Title", "Href", "SitelinkSetId", "AdExtensions"],
            }
        },
    )
    data = _parse(res)
    ads = data.get("result", {}).get("Ads", [])
    return [ad for ad in ads if isinstance(ad, dict) and "Id" in ad]


async def _create_sitelinks_set(session: ClientSession) -> int:
    res = await session.call_tool(
        "direct.raw_call",
        arguments={
            "resource": "sitelinks",
            "method": "add",
            "params": {
                "SitelinksSets": [
                    {
                        "Sitelinks": [
                            {"Title": "Каталог", "Href": TARGET_URL, "Description": "Товары и решения"},
                            {"Title": "Доставка", "Href": TARGET_URL, "Description": "По Москве и РФ"},
                            {"Title": "Контакты", "Href": TARGET_URL, "Description": "Связаться с нами"},
                            {"Title": "Подбор", "Href": TARGET_URL, "Description": "Поможем выбрать"},
                        ]
                    }
                ]
            },
        },
    )
    data = _parse(res)
    results = data.get("result", {}).get("AddResults", [])
    if not results or "Id" not in results[0]:
        raise RuntimeError(f"Failed to create sitelinks set: {data}")
    return int(results[0]["Id"])


async def _get_existing_callouts_by_text(session: ClientSession) -> dict[str, int]:
    res = await session.call_tool(
        "direct.raw_call",
        arguments={
            "resource": "adextensions",
            "method": "get",
            "params": {
                "SelectionCriteria": {"Types": ["CALLOUT"]},
                "FieldNames": ["Id", "Type", "State", "Status", "Associated"],
                "CalloutFieldNames": ["CalloutText"],
            },
        },
    )
    data = _parse(res)
    if "error" in data:
        return {}
    extensions = data.get("result", {}).get("AdExtensions", [])
    result: dict[str, int] = {}
    for ext in extensions:
        if not isinstance(ext, dict):
            continue
        if ext.get("Type") != "CALLOUT":
            continue
        callout = ext.get("Callout")
        if not isinstance(callout, dict):
            continue
        text = callout.get("CalloutText")
        if isinstance(text, str) and "Id" in ext:
            result[text] = int(ext["Id"])
    return result


async def _ensure_callouts(session: ClientSession) -> list[int]:
    existing = await _get_existing_callouts_by_text(session)
    missing = [text for text in CALLOUT_TEXTS if text not in existing]
    created_ids: list[int] = []

    if missing:
        res = await session.call_tool(
            "direct.raw_call",
            arguments={
                "resource": "adextensions",
                "method": "add",
                "params": {"AdExtensions": [{"Callout": {"CalloutText": text}} for text in missing]},
            },
        )
        data = _parse(res)
        results = data.get("result", {}).get("AddResults", [])
        for r in results:
            if isinstance(r, dict) and "Id" in r:
                created_ids.append(int(r["Id"]))

    ids: list[int] = []
    for text in CALLOUT_TEXTS:
        if text in existing:
            ids.append(existing[text])
    ids.extend(created_ids)
    return ids[: len(CALLOUT_TEXTS)]


def _extract_common_sitelink_set_id(ads: list[dict]) -> int | None:
    ids: set[int] = set()
    for ad in ads:
        text_ad = ad.get("TextAd")
        if not isinstance(text_ad, dict):
            continue
        value = text_ad.get("SitelinkSetId")
        if value is None:
            continue
        try:
            ids.add(int(value))
        except Exception:
            continue
    if len(ids) == 1:
        return next(iter(ids))
    return None


async def _update_ads(
    session: ClientSession,
    ads: list[dict],
    sitelink_set_id: int,
    callout_ids: list[int],
) -> list[int]:
    items = []
    updated: list[int] = []
    for ad in ads:
        ad_id = int(ad["Id"])
        text_ad: dict = {"SitelinkSetId": sitelink_set_id}
        if callout_ids:
            text_ad["AdExtensions"] = {"AdExtensionIds": callout_ids}
        items.append({"Id": ad_id, "TextAd": text_ad})
        updated.append(ad_id)
    await session.call_tool("direct.update_ads", arguments={"items": items})
    return updated


async def main() -> None:
    async with sse_client(SSE_URL) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()

            campaign_id = await _find_campaign_id(session)
            adgroup_id = await _find_adgroup_id(session, campaign_id)
            ads = await _list_ads_for_update(session, adgroup_id)
            if not ads:
                raise RuntimeError("No ads found to update; run scripts/mcp_seed_test_energy.py first.")

            sitelink_set_id = _extract_common_sitelink_set_id(ads) or await _create_sitelinks_set(session)
            callout_ids = await _ensure_callouts(session)

            updated_ads = await _update_ads(session, ads, sitelink_set_id, callout_ids)

            print(
                json.dumps(
                    {
                        "campaign_id": campaign_id,
                        "adgroup_id": adgroup_id,
                        "updated_ads": updated_ads,
                        "sitelink_set_id": sitelink_set_id,
                        "callout_ids": callout_ids,
                    },
                    ensure_ascii=True,
                )
            )


if __name__ == "__main__":
    anyio.run(main)
