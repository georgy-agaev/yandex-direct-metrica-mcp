"""Set bid for the autotargeting pseudo-keyword in a campaign.

In Unified ad groups, Direct often creates a pseudo-keyword `---autotargeting`.
You can manage its aggressiveness by setting its bid via `bids.set`.

Flow:
1) List keywords in the campaign
2) Find keyword entries with Keyword == '---autotargeting'
3) Apply `bids.set` for their KeywordId(s)
"""

from __future__ import annotations

import argparse
import json

import anyio

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


SSE_URL = "http://localhost:8000/sse"


def _micros_from_rub(value: float) -> int:
    return int(round(value * 1_000_000))


def _parse(res) -> dict:
    return getattr(res, "structuredContent", None) or json.loads(res.content[0].text)


async def main(campaign_id: int, bid_rub: float, apply: bool) -> None:
    bid_micros = _micros_from_rub(bid_rub)
    async with sse_client(SSE_URL) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()

            kw_res = await session.call_tool(
                "direct.list_keywords",
                arguments={
                    "selection_criteria": {"CampaignIds": [campaign_id]},
                    "field_names": ["Id", "Keyword", "CampaignId", "AdGroupId"],
                },
            )
            kw_data = _parse(kw_res)
            keywords = kw_data.get("result", {}).get("Keywords", [])
            auto_ids: list[int] = []
            for kw in keywords:
                if not isinstance(kw, dict):
                    continue
                if kw.get("Keyword") != "---autotargeting":
                    continue
                if "Id" in kw:
                    auto_ids.append(int(kw["Id"]))

            if not auto_ids:
                raise RuntimeError("No ---autotargeting keywords found in this campaign.")

            preview = {
                "tool": "direct.raw_call",
                "arguments": {
                    "resource": "bids",
                    "method": "set",
                    "params": {"Bids": [{"KeywordId": kid, "Bid": bid_micros} for kid in auto_ids]},
                },
            }

            if not apply:
                print(
                    json.dumps(
                        {
                            "status": "dry_run",
                            "campaign_id": campaign_id,
                            "autotargeting_keyword_ids": auto_ids,
                            "bid_micros": bid_micros,
                            "preview": preview,
                            "hint": "Re-run with --apply to execute.",
                        },
                        ensure_ascii=True,
                    )
                )
                return

            res = await session.call_tool("direct.raw_call", arguments=preview["arguments"])
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "campaign_id": campaign_id,
                        "autotargeting_keyword_ids": auto_ids,
                        "bid_micros": bid_micros,
                        "preview": preview,
                        "result": _parse(res),
                    },
                    ensure_ascii=True,
                )
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", type=int, required=True)
    parser.add_argument("--bid-rub", type=float, required=True)
    parser.add_argument("--apply", action="store_true", help="Execute the change (default: dry-run).")
    args = parser.parse_args()
    anyio.run(main, args.campaign_id, args.bid_rub, args.apply)
