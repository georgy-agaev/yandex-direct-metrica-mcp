"""End-to-end flow using the MCP SSE server.

Creates ad groups, ads (with sitelinks + callouts), and keywords for an existing
Unified campaign.
"""

from __future__ import annotations

import anyio

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


SSE_URL = "http://localhost:8000/sse"

# Existing objects created earlier in this workspace/account:
UNIFIED_CAMPAIGN_ID = 706378387
SITELINK_SET_ID = 1454949244
CALLOUT_IDS = [41450823, 41450824, 41450825]

REGION_RUSSIA = 225
REGION_MOSCOW = 213


async def main() -> None:
    async with sse_client(SSE_URL) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            required = {
                "direct.create_adgroups",
                "direct.create_ads",
                "direct.create_keywords",
                "direct.list_keywords",
                "direct.update_keywords",
            }
            missing = sorted(required - names)
            if missing:
                raise RuntimeError(f"Server missing tools: {missing}")

            # 1) Create 3 ad groups under Unified campaign.
            adgroups_payload = [
                {
                    "Name": "КЗ индикаторы",
                    "CampaignId": UNIFIED_CAMPAIGN_ID,
                    "RegionIds": [REGION_RUSSIA, REGION_MOSCOW],
                },
                {
                    "Name": "Кабельные муфты",
                    "CampaignId": UNIFIED_CAMPAIGN_ID,
                    "RegionIds": [REGION_RUSSIA, REGION_MOSCOW],
                },
                {
                    "Name": "Изолированный инструмент",
                    "CampaignId": UNIFIED_CAMPAIGN_ID,
                    "RegionIds": [REGION_RUSSIA, REGION_MOSCOW],
                },
            ]
            adgroups_res = await session.call_tool(
                "direct.create_adgroups", arguments={"items": adgroups_payload}
            )
            print("create_adgroups:", adgroups_res.content[0].text)

            # Parse IDs from the returned JSON string (server returns text).
            import json

            adgroups_data = json.loads(adgroups_res.content[0].text)
            adgroup_ids = [r["Id"] for r in adgroups_data["result"]["AddResults"]]
            kz_id, mufta_id, tool_id = adgroup_ids

            # 2) Create ads with sitelinks + callouts.
            def mk_ads(adgroup_id: int, title: str, title2: str, text: str):
                return {
                    "AdGroupId": adgroup_id,
                    "TextAd": {
                        "Title": title,
                        "Title2": title2,
                        "Text": text,
                        "Href": "https://test-energy.ru/",
                        "SitelinkSetId": SITELINK_SET_ID,
                        # For ads.add, callouts are passed as AdExtensionIds.
                        "AdExtensions": {"AdExtensionIds": CALLOUT_IDS},
                    },
                }

            ads_payload = [
                mk_ads(
                    kz_id,
                    "Индикаторы КЗ для ЛЭП",
                    "6–110 кВ",
                    "Подбор индикаторов и комплектующих. Доставка по РФ.",
                ),
                mk_ads(
                    mufta_id,
                    "Кабельные муфты 6–10 кВ",
                    "Внутр/наружн. установка",
                    "Комплекты муфт и аксессуаров. Поможем подобрать.",
                ),
                mk_ads(
                    tool_id,
                    "Инструмент электрика до 1000В",
                    "Изолированный",
                    "Наборы, отвертки, ключи. Консультация инженера.",
                ),
            ]
            ads_res = await session.call_tool("direct.create_ads", arguments={"items": ads_payload})
            print("create_ads:", ads_res.content[0].text)

            # 3) Create keywords per group.
            keywords_by_group = {
                kz_id: [
                    "индикаторы короткого замыкания",
                    "индикатор кз для лэп",
                    "индикатор повреждения кабеля",
                ],
                mufta_id: [
                    "кабельные муфты 6 10 кв",
                    "концевая муфта холодной усадки",
                    "соединительная муфта спэ",
                ],
                tool_id: [
                    "изолированный инструмент электрика",
                    "инструмент до 1000в купить",
                    "набор инструмента для электромонтажа",
                ],
            }
            keywords_payload = [
                {"AdGroupId": gid, "Keyword": kw}
                for gid, kws in keywords_by_group.items()
                for kw in kws
            ]
            keywords_res = await session.call_tool(
                "direct.create_keywords", arguments={"items": keywords_payload}
            )
            print("create_keywords:", keywords_res.content[0].text)

            # 4) Switch keywords to phrase match (wrap with quotes).
            kw_list_res = await session.call_tool(
                "direct.list_keywords",
                arguments={"selection_criteria": {"CampaignIds": [UNIFIED_CAMPAIGN_ID]}, "field_names": ["Id", "Keyword"]},
            )
            kw_data = json.loads(kw_list_res.content[0].text)
            updates = []
            for kw in kw_data["result"]["Keywords"]:
                if kw["Keyword"].startswith("---"):
                    continue
                updates.append({"Id": kw["Id"], "Keyword": f"\"{kw['Keyword']}\""})
            upd_res = await session.call_tool("direct.update_keywords", arguments={"items": updates})
            print("update_keywords:", upd_res.content[0].text)


if __name__ == "__main__":
    anyio.run(main)
