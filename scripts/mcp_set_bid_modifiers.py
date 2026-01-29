"""Create/update bid modifiers via Direct API through MCP (SSE).

This script is generic and operates on raw payload because bid modifier
structures vary and are frequently extended by Direct.

Common methods: add, set, delete, get (depends on API/resource).

Example file for --payload:
{
  "SelectionCriteria": {"CampaignIds": [706377468]},
  "FieldNames": ["Id", "CampaignId", "Type"]
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


async def main(method: str, payload: dict, apply: bool) -> None:
    async with sse_client(SSE_URL) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            preview = {
                "tool": "direct.raw_call",
                "arguments": {"resource": "bidmodifiers", "method": method, "params": payload},
            }

            write_methods = {"add", "set", "delete", "update"}
            is_write = method.strip().lower() in write_methods
            if is_write and not apply:
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

            res = await session.call_tool("direct.raw_call", arguments=preview["arguments"])
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "preview": preview,
                        "result": getattr(res, "structuredContent", None) or json.loads(res.content[0].text),
                    },
                    ensure_ascii=True,
                )
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", type=str, required=True, help="Direct bidmodifiers method (get/add/set/delete).")
    parser.add_argument(
        "--payload",
        type=str,
        required=True,
        help="JSON string or path to JSON file with params payload.",
    )
    parser.add_argument("--apply", action="store_true", help="Execute the change for write methods (default: dry-run).")
    args = parser.parse_args()
    anyio.run(main, args.method, _load_json(args.payload), args.apply)
