"""Generate BI dashboard (Option 1) via MCP SSE.

This script is a thin wrapper over the MCP tool `dashboard.generate_option1`.
It exists for convenience when you want a one-liner to generate HTML+JSON into a folder.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
import click
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


DEFAULT_SSE_URL = "http://localhost:8000/sse"


def _parse_text_response(res: Any) -> dict[str, Any]:
    # MCP client returns a list of content items; our server uses TextContent(JSON-string).
    if isinstance(res, list) and res and isinstance(res[0], dict) and "text" in res[0]:
        return json.loads(res[0]["text"])
    if isinstance(res, list) and res and hasattr(res[0], "text"):
        return json.loads(res[0].text)
    raise ValueError("Unexpected MCP response shape")


@dataclass(frozen=True)
class Inputs:
    sse_url: str
    account_id: str | None
    direct_client_login: str | None
    counter_id: str | None
    goal_ids: list[str]
    date_from: str
    date_to: str
    output_dir: Path
    dashboard_slug: str | None
    include_raw_reports: bool


async def _run(inputs: Inputs) -> tuple[str | None, str | None]:
    args: dict[str, Any] = {
        "date_from": inputs.date_from,
        "date_to": inputs.date_to,
        "output_dir": str(inputs.output_dir),
        "include_raw_reports": inputs.include_raw_reports,
    }
    if inputs.account_id:
        args["account_id"] = inputs.account_id
    if inputs.direct_client_login:
        args["direct_client_login"] = inputs.direct_client_login
    if inputs.counter_id:
        args["counter_id"] = inputs.counter_id
    if inputs.dashboard_slug:
        args["dashboard_slug"] = inputs.dashboard_slug
    if inputs.goal_ids:
        args["goal_ids"] = inputs.goal_ids

    async with sse_client(inputs.sse_url) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            res = await session.call_tool("dashboard.generate_option1", arguments=args)
            payload = _parse_text_response(res)

    files = (payload.get("result") or {}).get("files") or {}
    return files.get("html_path"), files.get("json_path")


@click.command()
@click.option("--sse-url", default=DEFAULT_SSE_URL, show_default=True)
@click.option("--account-id", default=None)
@click.option("--direct-client-login", default=None)
@click.option("--counter-id", default=None)
@click.option("--goal-id", "goal_ids", multiple=True, help="Metrica goal id (repeatable).")
@click.option("--date-from", required=True, help="YYYY-MM-DD (current period).")
@click.option("--date-to", required=True, help="YYYY-MM-DD (current period).")
@click.option("--output-dir", required=True, type=click.Path(path_type=Path))
@click.option("--dashboard-slug", default=None)
@click.option("--include-raw-reports/--no-include-raw-reports", default=True, show_default=True)
def main(
    sse_url: str,
    account_id: str | None,
    direct_client_login: str | None,
    counter_id: str | None,
    goal_ids: tuple[str, ...],
    date_from: str,
    date_to: str,
    output_dir: Path,
    dashboard_slug: str | None,
    include_raw_reports: bool,
) -> None:
    """Generate dashboard HTML+JSON into OUTPUT_DIR."""
    html_path, json_path = anyio.run(
        _run,
        Inputs(
            sse_url=sse_url,
            account_id=account_id,
            direct_client_login=direct_client_login,
            counter_id=counter_id,
            goal_ids=[str(x).strip() for x in goal_ids if str(x).strip()],
            date_from=date_from,
            date_to=date_to,
            output_dir=output_dir,
            dashboard_slug=dashboard_slug,
            include_raw_reports=include_raw_reports,
        ),
    )
    click.echo(f"html: {html_path}")
    click.echo(f"json: {json_path}")


if __name__ == "__main__":
    main()

