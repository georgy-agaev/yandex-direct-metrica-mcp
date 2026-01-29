"""Apply UTM parameters to TextAd.Href for all ads in a campaign.

This is a pragmatic alternative to Direct tracking templates when you want
consistent UTM tags quickly.

The script:
1) Lists ads in the campaign (Id, CampaignId, AdGroupId, TextAd.Href)
2) Builds a new URL by applying a template (placeholders supported)
3) Updates ads via `direct.update_ads`

Placeholders in the template string:
- {campaign_id}
- {adgroup_id}
- {ad_id}

Example:
--utm \"utm_source=yandex&utm_medium=cpc&utm_campaign={campaign_id}&utm_content={ad_id}\"
"""

from __future__ import annotations

import argparse
import json
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import anyio

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


SSE_URL = "http://localhost:8000/sse"


def _parse(res) -> dict:
    return json.loads(res.content[0].text)


def _merge_query(url: str, params: dict[str, str], *, overwrite: bool) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for k, v in params.items():
        if overwrite or k not in query:
            query[k] = v
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _parse_utm_kv(utm: str) -> dict[str, str]:
    # Allow "a=b&c=d" or "?a=b&c=d"
    q = utm.lstrip("?")
    return dict(parse_qsl(q, keep_blank_values=True))


async def main(campaign_id: int, utm_template: str, overwrite: bool) -> None:
    async with sse_client(SSE_URL) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()

            res = await session.call_tool(
                "direct.list_ads",
                arguments={
                    "params": {
                        "SelectionCriteria": {"CampaignIds": [campaign_id]},
                        "FieldNames": ["Id", "CampaignId", "AdGroupId", "Type", "Subtype"],
                        "TextAdFieldNames": ["Href"],
                    }
                },
            )
            data = _parse(res)
            ads = data.get("result", {}).get("Ads", [])

            updates = []
            changed = 0
            for ad in ads:
                if not isinstance(ad, dict) or "Id" not in ad:
                    continue
                if ad.get("Type") != "TEXT_AD":
                    continue
                text_ad = ad.get("TextAd")
                if not isinstance(text_ad, dict):
                    continue
                href = text_ad.get("Href")
                if not isinstance(href, str) or not href:
                    continue

                rendered = utm_template.format(
                    campaign_id=ad.get("CampaignId"),
                    adgroup_id=ad.get("AdGroupId"),
                    ad_id=ad.get("Id"),
                )
                kv = _parse_utm_kv(rendered)
                new_href = _merge_query(href, kv, overwrite=overwrite)
                if new_href == href:
                    continue

                updates.append({"Id": int(ad["Id"]), "TextAd": {"Href": new_href}})
                changed += 1

            if not updates:
                print(json.dumps({"campaign_id": campaign_id, "changed_ads": 0}, ensure_ascii=True))
                return

            upd = await session.call_tool("direct.update_ads", arguments={"items": updates})
            print(json.dumps({"campaign_id": campaign_id, "changed_ads": changed, "result": _parse(upd)}, ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", type=int, required=True)
    parser.add_argument("--utm", type=str, required=True, help="UTM template string (querystring).")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing UTM keys if present.")
    args = parser.parse_args()
    anyio.run(main, args.campaign_id, args.utm, args.overwrite)

