"""MCP server for Yandex Direct + Metrica (Python)."""

import asyncio
import logging
import os
import textwrap
import webbrowser

import click
from dotenv import load_dotenv

__version__ = "0.1.0"

logger = logging.getLogger("yandex-direct-metrica-mcp")


@click.group(invoke_without_command=True)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity (can be used multiple times)",
)
@click.option(
    "--env-file",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to .env file",
)
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="Transport type (stdio or sse)",
)
@click.option(
    "--port",
    default=8000,
    help="Port to listen on for SSE transport",
)
@click.pass_context
def main(
    ctx: click.Context,
    verbose: int,
    env_file: str | None,
    transport: str,
    port: int,
) -> None:
    """MCP server for Yandex Direct + Metrica."""
    logging_level = logging.WARNING
    if verbose == 1:
        logging_level = logging.INFO
    elif verbose >= 2:
        logging_level = logging.DEBUG

    logging.basicConfig(
        level=logging_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if env_file:
        logger.debug("Loading environment from file: %s", env_file)
        load_dotenv(env_file)
    else:
        load_dotenv()

    from . import server

    if ctx.invoked_subcommand is None:
        asyncio.run(server.run_server(transport=transport, port=port))


@main.command("auth")
@click.option("--client-id", default=lambda: os.getenv("YANDEX_CLIENT_ID"), help="Yandex OAuth client id")
@click.option(
    "--client-secret",
    default=lambda: os.getenv("YANDEX_CLIENT_SECRET"),
    help="Yandex OAuth client secret",
)
@click.option(
    "--redirect-uri",
    default=lambda: os.getenv("YANDEX_REDIRECT_URI") or "https://oauth.yandex.ru/verification_code",
    help="Redirect URI used in the app settings",
)
@click.option(
    "--scopes",
    default=lambda: os.getenv("YANDEX_SCOPES") or "",
    help="Space-separated scopes (example: 'direct:api metrika:read')",
)
@click.option(
    "--open-browser/--no-open-browser",
    default=True,
    help="Open authorization URL in a browser",
)
def auth_command(
    client_id: str | None,
    client_secret: str | None,
    redirect_uri: str,
    scopes: str,
    open_browser: bool,
) -> None:
    """Interactive OAuth helper: open auth URL and exchange code for tokens."""
    if not client_id or not client_secret:
        raise click.ClickException(
            "Missing YANDEX_CLIENT_ID / YANDEX_CLIENT_SECRET. Set env vars or pass --client-id/--client-secret."
        )

    from .oauth import build_authorize_url, exchange_code_for_tokens

    scopes_list = [s for s in scopes.split(" ") if s.strip()] if scopes else []
    auth_url = build_authorize_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=scopes_list or None,
    )

    click.echo("1) Open this URL and authorize the app:")
    click.echo(auth_url)
    if open_browser:
        webbrowser.open(auth_url)

    click.echo("\n2) Paste the authorization code from Yandex:")
    code = click.prompt("code", hide_input=False).strip()
    if not code:
        raise click.ClickException("Empty code")

    click.echo("\n3) Exchanging code for tokens...")
    try:
        tokens = exchange_code_for_tokens(
            code=code,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo("\n✓ Success. Add these to your `.env` (do not commit it):\n")
    refresh = tokens.refresh_token or ""
    click.echo(
        textwrap.dedent(
            f"""\
            # OAuth
            YANDEX_CLIENT_ID={client_id}
            YANDEX_CLIENT_SECRET={client_secret}
            YANDEX_ACCESS_TOKEN={tokens.access_token}
            YANDEX_REFRESH_TOKEN={refresh}
            YANDEX_REDIRECT_URI={redirect_uri}
            """
        ).rstrip()
    )


__all__ = ["__version__", "main", "server"]

if __name__ == "__main__":
    main()
