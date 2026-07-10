"""Pull released images and refresh local Docker aliases."""

from __future__ import annotations

import argparse
import os
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ImageSpec:
    remote: str
    local_aliases: tuple[str, ...]


@dataclass(frozen=True)
class PullFailure(Exception):
    remote: str
    status: str
    details: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Release version, for example 2.0.13")
    parser.add_argument("--owner", default="georgy-agaev", help="GHCR/Docker owner")
    parser.add_argument(
        "--include-pro",
        action="store_true",
        help="Also sync the PRO image from ghcr.io/<owner>/yandex-direct-metrica-mcp-pro:pro-vX.Y.Z",
    )
    return parser.parse_args()


def run(*args: str) -> None:
    subprocess.run(list(args), check=True)


def command_details(exc: subprocess.CalledProcessError) -> str:
    if exc.stderr:
        return exc.stderr.strip()
    if exc.stdout:
        return exc.stdout.strip()
    return str(exc)


def ghcr_login_if_possible(owner: str) -> bool:
    token = os.environ.get("GHCR_READ_TOKEN")
    if not token:
        return False
    try:
        subprocess.run(
            ["docker", "login", "ghcr.io", "-u", owner, "--password-stdin"],
            input=token.encode("utf-8"),
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            "GHCR login failed with GHCR_READ_TOKEN. "
            "Verify the token value and confirm it has read:packages for the private PRO package. "
            f"Original error: {command_details(exc)}"
        ) from exc
    return True


def classify_pull_failure(remote: str, details: str) -> PullFailure:
    lowered = details.lower()
    if "403" in lowered or "forbidden" in lowered or "requested access to the resource is denied" in lowered:
        return PullFailure(
            remote=remote,
            status="forbidden",
            details=(
                f"Missing GHCR read access for {remote}. "
                "Provide GHCR_READ_TOKEN with read:packages or docker login ghcr.io with a token that can read the package. "
                f"Original error: {details}"
            ),
        )
    if "404" in lowered or "not found" in lowered or "manifest unknown" in lowered:
        return PullFailure(
            remote=remote,
            status="not_found",
            details=f"Release image not found yet for {remote}. Original error: {details}",
        )
    return PullFailure(remote=remote, status="unknown", details=details)


def pull_remote_image(remote: str) -> None:
    try:
        subprocess.run(["docker", "pull", remote], check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        failure = classify_pull_failure(remote, command_details(exc))
        raise SystemExit(failure.details) from exc


def specs(owner: str, version: str, include_pro: bool) -> list[ImageSpec]:
    items = [
        ImageSpec(
            remote=f"ghcr.io/{owner}/yandex-direct-metrica-mcp:v{version}",
            local_aliases=(
                "yandex-direct-metrica-mcp:latest",
                f"ghcr.io/{owner}/yandex-direct-metrica-mcp:latest",
                f"docker.io/{owner}/yandex-direct-metrica-mcp:latest",
            ),
        )
    ]
    if include_pro:
        items.append(
            ImageSpec(
                remote=f"ghcr.io/{owner}/yandex-direct-metrica-mcp-pro:pro-v{version}",
                local_aliases=(
                    "yandex-direct-metrica-mcp-pro:latest",
                    f"ghcr.io/{owner}/yandex-direct-metrica-mcp-pro:latest",
                    f"docker.io/{owner}/yandex-direct-metrica-mcp-pro:latest",
                ),
            )
        )
    return items


def main() -> int:
    args = parse_args()
    if args.include_pro:
        ghcr_login_if_possible(args.owner)
    for item in specs(args.owner, args.version, args.include_pro):
        print(f"== pull {item.remote} ==")
        pull_remote_image(item.remote)
        for alias in item.local_aliases:
            print(f"tag {item.remote} -> {alias}")
            run("docker", "tag", item.remote, alias)
    print("Local Docker aliases refreshed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
