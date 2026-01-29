"""Seed a minimal Direct campaign structure via the MCP SSE server.

Goal: for an existing (or newly created) campaign named "MCP test-energy.ru",
create:
- 1 ad group with regions Russia + Moscow
- 3 text ads (draft)
- 5 keywords (phrase match)

This script is best-effort idempotent:
- It does not create duplicate ad groups (by Name).
- It does not create duplicate keywords (by Keyword).
- It tries to avoid duplicate ads (by Title+Href).

Requirements:
- MCP server running with SSE transport (default `docker compose up -d --build`)
- `.env` exported to the environment (docker compose uses env_file automatically)
"""

from __future__ import annotations

import json

import anyio

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


SSE_URL = "http://localhost:8000/sse"

CAMPAIGN_NAME = "MCP test-energy.ru"
ADGROUP_NAME = "MCP test-energy.ru / RU+Moscow"

REGION_RUSSIA = 225
REGION_MOSCOW = 213

TARGET_URL = "https://test-energy.ru/"

KEYWORDS = [
    "индикаторы короткого замыкания",
    "кабельные муфты 6 10 кв",
    "изолированный инструмент электрика",
    "электротехническое оборудование",
    "оборудование для лэп",
]

ADS = [
    {
        "Title": "Электротехника и комплектующие",
        "Title2": "Подбор и поставка",
        "Text": "Индикаторы КЗ, муфты, изолированный инструмент. Доставка по РФ.",
    },
    {
        "Title": "Кабельные муфты 6–10 кВ",
        "Title2": "Комплекты и аксессуары",
        "Text": "Поможем подобрать. Консультация инженера. Доставка по РФ.",
    },
    {
        "Title": "Изолированный инструмент до 1000В",
        "Title2": "Наборы для электрика",
        "Text": "Отвертки, ключи, наборы. Подбор под задачу. Заказ онлайн.",
    },
]


def _parse_text_response(res) -> dict:
    return json.loads(res.content[0].text)


async def _get_or_create_campaign(session: ClientSession) -> int:
    res = await session.call_tool(
        "direct.list_campaigns",
        arguments={"field_names": ["Id", "Name"]},
    )
    data = _parse_text_response(res)
    campaigns = data.get("result", {}).get("Campaigns", [])
    for campaign in campaigns:
        if campaign.get("Name") == CAMPAIGN_NAME:
            return int(campaign["Id"])

    # If not found, create a minimal campaign. It will remain a draft until fully configured.
    create = await session.call_tool(
        "direct.create_campaigns",
        arguments={
            "items": [
                {
                    "Name": CAMPAIGN_NAME,
                    # Minimal v5-compatible payload: keep it empty and let the account defaults apply.
                    # For Unified campaigns (v501), the server is expected to be configured with
                    # YANDEX_DIRECT_API_VERSION=v501 and the user can override via params if needed.
                }
            ]
        },
    )
    created = _parse_text_response(create)
    results = created.get("result", {}).get("AddResults", [])
    if not results or "Id" not in results[0]:
        raise RuntimeError(f"Failed to create campaign: {created}")
    return int(results[0]["Id"])


async def _get_or_create_adgroup(session: ClientSession, campaign_id: int) -> int:
    res = await session.call_tool(
        "direct.list_adgroups",
        arguments={
            "selection_criteria": {"CampaignIds": [campaign_id]},
            "field_names": ["Id", "Name"],
        },
    )
    data = _parse_text_response(res)
    groups = data.get("result", {}).get("AdGroups", [])
    for group in groups:
        if group.get("Name") == ADGROUP_NAME:
            return int(group["Id"])

    created = await session.call_tool(
        "direct.create_adgroups",
        arguments={
            "items": [
                {
                    "Name": ADGROUP_NAME,
                    "CampaignId": campaign_id,
                    "RegionIds": [REGION_RUSSIA, REGION_MOSCOW],
                }
            ]
        },
    )
    payload = _parse_text_response(created)
    results = payload.get("result", {}).get("AddResults", [])
    if not results or "Id" not in results[0]:
        raise RuntimeError(f"Failed to create ad group: {payload}")
    return int(results[0]["Id"])


async def _ensure_keywords(session: ClientSession, adgroup_id: int) -> None:
    res = await session.call_tool(
        "direct.list_keywords",
        arguments={
            "selection_criteria": {"AdGroupIds": [adgroup_id]},
            "field_names": ["Id", "Keyword"],
        },
    )
    existing = _parse_text_response(res).get("result", {}).get("Keywords", [])
    existing_keywords = {kw.get("Keyword") for kw in existing if isinstance(kw, dict)}

    to_add = []
    for keyword in KEYWORDS:
        phrase = f"\"{keyword}\""
        if phrase in existing_keywords:
            continue
        to_add.append({"AdGroupId": adgroup_id, "Keyword": phrase})

    if not to_add:
        return

    await session.call_tool("direct.create_keywords", arguments={"items": to_add})


async def _ensure_ads(session: ClientSession, adgroup_id: int) -> None:
    # Use raw params override to request TextAd details.
    res = await session.call_tool(
        "direct.list_ads",
        arguments={
            "params": {
                "SelectionCriteria": {"AdGroupIds": [adgroup_id]},
                "FieldNames": ["Id", "AdGroupId", "TextAd"],
                "TextAdFieldNames": ["Title", "Title2", "Text", "Href"],
            }
        },
    )
    existing = _parse_text_response(res).get("result", {}).get("Ads", [])
    existing_keys: set[tuple[str, str]] = set()
    for ad in existing:
        text_ad = ad.get("TextAd") if isinstance(ad, dict) else None
        if not isinstance(text_ad, dict):
            continue
        title = text_ad.get("Title")
        href = text_ad.get("Href")
        if isinstance(title, str) and isinstance(href, str):
            existing_keys.add((title, href))

    to_add = []
    for spec in ADS:
        key = (spec["Title"], TARGET_URL)
        if key in existing_keys:
            continue
        to_add.append(
            {
                "AdGroupId": adgroup_id,
                "TextAd": {
                    "Title": spec["Title"],
                    "Title2": spec["Title2"],
                    "Text": spec["Text"],
                    "Href": TARGET_URL,
                },
            }
        )

    if not to_add:
        return

    await session.call_tool("direct.create_ads", arguments={"items": to_add})


async def main() -> None:
    async with sse_client(SSE_URL) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()

            required = {
                "direct.list_campaigns",
                "direct.create_campaigns",
                "direct.list_adgroups",
                "direct.create_adgroups",
                "direct.list_ads",
                "direct.create_ads",
                "direct.list_keywords",
                "direct.create_keywords",
            }
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            missing = sorted(required - names)
            if missing:
                raise RuntimeError(f"Server missing tools: {missing}")

            campaign_id = await _get_or_create_campaign(session)
            adgroup_id = await _get_or_create_adgroup(session, campaign_id)
            await _ensure_ads(session, adgroup_id)
            await _ensure_keywords(session, adgroup_id)

            print(
                json.dumps(
                    {"campaign_id": campaign_id, "adgroup_id": adgroup_id},
                    ensure_ascii=True,
                )
            )


if __name__ == "__main__":
    anyio.run(main)

