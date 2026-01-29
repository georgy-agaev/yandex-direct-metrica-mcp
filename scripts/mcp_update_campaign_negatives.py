"""Update campaign negative keywords via Direct API through MCP (SSE).

Uses:
- `direct.update_campaigns` with the full Direct payload shape.
"""

from __future__ import annotations

import argparse
import json

import anyio

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


SSE_URL = "http://localhost:8000/sse"


def _split_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


async def main(campaign_id: int, negatives: list[str], apply: bool) -> None:
    async with sse_client(SSE_URL) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            preview = {
                "tool": "direct.update_campaigns",
                "arguments": {
                    "items": [
                        {
                            "Id": campaign_id,
                            "NegativeKeywords": {"Items": negatives},
                        }
                    ]
                },
            }
            if not apply:
                print(
                    json.dumps(
                        {"status": "dry_run", "preview": preview, "hint": "Re-run with --apply to execute."},
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
        "--negatives",
        type=str,
        required=True,
        help="Comma-separated negative keywords.",
    )
    parser.add_argument("--apply", action="store_true", help="Execute the change (default: dry-run).")
    args = parser.parse_args()
    anyio.run(main, args.campaign_id, _split_csv(args.negatives), args.apply)
