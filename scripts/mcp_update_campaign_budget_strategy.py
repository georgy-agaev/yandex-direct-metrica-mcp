"""Update campaign budget/strategy by applying a JSON patch via MCP.

This is intentionally generic: Direct campaign schemas differ across campaign
types and API versions (`v5` vs `v501`). The recommended flow is:
1) Fetch the current campaign payload via `direct.raw_call` (campaigns.get)
2) Prepare a minimal patch JSON with only fields you want to change
3) Apply the patch with this script (campaigns.update)

Example patch (illustrative; field names depend on campaign type):
{
  "UnifiedCampaign": {
    "BiddingStrategy": {
      "Search": { "BiddingStrategyType": "HIGHEST_POSITION" },
      "Network": { "BiddingStrategyType": "SERVING_OFF" }
    }
  }
}
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import anyio

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


SSE_URL = "http://localhost:8000/sse"


def _load_json(value: str) -> dict:
    path = Path(value)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(value)


async def main(campaign_id: int, patch: dict, apply: bool) -> None:
    async with sse_client(SSE_URL) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            item = {"Id": campaign_id, **patch}
            preview = {"tool": "direct.update_campaigns", "arguments": {"items": [item]}}
            if not apply:
                print(
                    json.dumps(
                        {
                            "status": "dry_run",
                            "preview": preview,
                            "hint": "Re-run with --apply to execute.",
                        },
                        ensure_ascii=True,
                    )
                )
                return
            res = await session.call_tool("direct.update_campaigns", arguments=preview["arguments"])
            result = getattr(res, "structuredContent", None) or json.loads(res.content[0].text)
            print(json.dumps({"status": "ok", "preview": preview, "result": result}, ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", type=int, required=True)
    parser.add_argument(
        "--patch",
        type=str,
        required=True,
        help="JSON string or path to a JSON file with the patch object.",
    )
    parser.add_argument("--apply", action="store_true", help="Execute the change (default: dry-run).")
    args = parser.parse_args()
    anyio.run(main, args.campaign_id, _load_json(args.patch), args.apply)
