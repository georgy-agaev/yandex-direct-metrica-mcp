"""Bulk set keyword bids via Direct API through MCP (SSE).

Uses:
- `direct.list_keywords` (to collect KeywordIds)
- `direct.raw_call` -> `bids.set` (to set bids)

Notes:
- Direct expects bid values in micros (1 ruble == 1_000_000 micros).
- Skips autotargeting pseudo-keywords (Keyword starts with '---').
"""

from __future__ import annotations

import argparse
import json

import anyio

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


SSE_URL = "http://localhost:8000/sse"


def _parse(res) -> dict:
    return getattr(res, "structuredContent", None) or json.loads(res.content[0].text)


def _micros_from_rub(value: float) -> int:
    return int(round(value * 1_000_000))


async def _collect_keyword_ids(session: ClientSession, campaign_id: int) -> list[int]:
    res = await session.call_tool(
        "direct.list_keywords",
        arguments={
            "selection_criteria": {"CampaignIds": [campaign_id]},
            "field_names": ["Id", "Keyword"],
        },
    )
    data = _parse(res)
    keywords = data.get("result", {}).get("Keywords", [])
    ids: list[int] = []
    for kw in keywords:
        if not isinstance(kw, dict):
            continue
        text = kw.get("Keyword")
        if isinstance(text, str) and text.startswith("---"):
            continue
        if "Id" in kw:
            ids.append(int(kw["Id"]))
    return ids


async def _set_bids(session: ClientSession, keyword_ids: list[int], bid_micros: int) -> dict:
    payload = {
        "resource": "bids",
        "method": "set",
        "params": {"Bids": [{"KeywordId": kid, "Bid": bid_micros} for kid in keyword_ids]},
    }
    res = await session.call_tool("direct.raw_call", arguments=payload)
    return _parse(res)


async def main(campaign_id: int, bid_rub: float, apply: bool) -> None:
    bid_micros = _micros_from_rub(bid_rub)
    async with sse_client(SSE_URL) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            ids = await _collect_keyword_ids(session, campaign_id)
            if not ids:
                raise RuntimeError("No keywords found to update bids for.")
            preview = {
                "tool": "direct.raw_call",
                "arguments": {
                    "resource": "bids",
                    "method": "set",
                    "params": {"Bids": [{"KeywordId": kid, "Bid": bid_micros} for kid in ids]},
                },
            }
            if not apply:
                print(
                    json.dumps(
                        {
                            "status": "dry_run",
                            "campaign_id": campaign_id,
                            "keyword_count": len(ids),
                            "bid_micros": bid_micros,
                            "preview": preview,
                            "hint": "Re-run with --apply to execute.",
                        },
                        ensure_ascii=True,
                    )
                )
                return

            result = await _set_bids(session, ids, bid_micros)
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "campaign_id": campaign_id,
                        "keyword_count": len(ids),
                        "bid_micros": bid_micros,
                        "preview": preview,
                        "result": result,
                    },
                    ensure_ascii=True,
                )
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", type=int, required=True)
    parser.add_argument("--bid-rub", type=float, required=True, help="Bid in rubles (converted to micros).")
    parser.add_argument("--apply", action="store_true", help="Execute the change (default: dry-run).")
    args = parser.parse_args()
    anyio.run(main, args.campaign_id, args.bid_rub, args.apply)
