import argparse
import subprocess

import pytest

from scripts import sync_local_docker_release
from scripts.sync_local_docker_release import specs


def test_specs_public_only() -> None:
    items = specs("georgy-agaev", "2.0.13", include_pro=False)
    assert len(items) == 1
    assert items[0].remote == "ghcr.io/georgy-agaev/yandex-direct-metrica-mcp:v2.0.13"
    assert "yandex-direct-metrica-mcp:latest" in items[0].local_aliases


def test_specs_include_pro() -> None:
    items = specs("georgy-agaev", "2.0.13", include_pro=True)
    assert len(items) == 2
    assert items[1].remote == "ghcr.io/georgy-agaev/yandex-direct-metrica-mcp-pro:pro-v2.0.13"
    assert "yandex-direct-metrica-mcp-pro:latest" in items[1].local_aliases


def test_main_public_only_refreshes_public_aliases_without_ghcr_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    monkeypatch.setattr(
        sync_local_docker_release,
        "parse_args",
        lambda: argparse.Namespace(version="2.0.13", owner="georgy-agaev", include_pro=False),
    )
    monkeypatch.setattr(
        sync_local_docker_release,
        "ghcr_login_if_possible",
        lambda *_args: (_ for _ in ()).throw(AssertionError("public sync should not log in")),
    )
    monkeypatch.setattr(
        sync_local_docker_release,
        "pull_remote_image",
        lambda remote: calls.append(("pull", (remote,))),
    )
    monkeypatch.setattr(
        sync_local_docker_release,
        "run",
        lambda *args: calls.append(("run", tuple(args))),
    )

    assert sync_local_docker_release.main() == 0

    remote = "ghcr.io/georgy-agaev/yandex-direct-metrica-mcp:v2.0.13"
    assert calls == [
        ("pull", (remote,)),
        ("run", ("docker", "tag", remote, "yandex-direct-metrica-mcp:latest")),
        ("run", ("docker", "tag", remote, "ghcr.io/georgy-agaev/yandex-direct-metrica-mcp:latest")),
        ("run", ("docker", "tag", remote, "docker.io/georgy-agaev/yandex-direct-metrica-mcp:latest")),
    ]


def test_main_include_pro_refreshes_public_and_pro_aliases_after_ghcr_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    monkeypatch.setattr(
        sync_local_docker_release,
        "parse_args",
        lambda: argparse.Namespace(version="2.0.13", owner="georgy-agaev", include_pro=True),
    )
    monkeypatch.setattr(
        sync_local_docker_release,
        "ghcr_login_if_possible",
        lambda owner: calls.append(("login", (owner,))) or True,
    )
    monkeypatch.setattr(
        sync_local_docker_release,
        "pull_remote_image",
        lambda remote: calls.append(("pull", (remote,))),
    )
    monkeypatch.setattr(
        sync_local_docker_release,
        "run",
        lambda *args: calls.append(("run", tuple(args))),
    )

    assert sync_local_docker_release.main() == 0

    public_remote = "ghcr.io/georgy-agaev/yandex-direct-metrica-mcp:v2.0.13"
    pro_remote = "ghcr.io/georgy-agaev/yandex-direct-metrica-mcp-pro:pro-v2.0.13"
    assert calls == [
        ("login", ("georgy-agaev",)),
        ("pull", (public_remote,)),
        ("run", ("docker", "tag", public_remote, "yandex-direct-metrica-mcp:latest")),
        ("run", ("docker", "tag", public_remote, "ghcr.io/georgy-agaev/yandex-direct-metrica-mcp:latest")),
        ("run", ("docker", "tag", public_remote, "docker.io/georgy-agaev/yandex-direct-metrica-mcp:latest")),
        ("pull", (pro_remote,)),
        ("run", ("docker", "tag", pro_remote, "yandex-direct-metrica-mcp-pro:latest")),
        ("run", ("docker", "tag", pro_remote, "ghcr.io/georgy-agaev/yandex-direct-metrica-mcp-pro:latest")),
        ("run", ("docker", "tag", pro_remote, "docker.io/georgy-agaev/yandex-direct-metrica-mcp-pro:latest")),
    ]


def test_classify_pull_failure_forbidden() -> None:
    failure = sync_local_docker_release.classify_pull_failure(
        "ghcr.io/example/pro:pro-v2.0.14",
        "Error response from daemon: Head https://ghcr.io/v2/...: 403 Forbidden",
    )
    assert failure.status == "forbidden"
    assert "GHCR_READ_TOKEN" in failure.details


def test_classify_pull_failure_denied_phrase_maps_to_forbidden() -> None:
    failure = sync_local_docker_release.classify_pull_failure(
        "ghcr.io/example/pro:pro-v2.0.14",
        "denied: requested access to the resource is denied",
    )
    assert failure.status == "forbidden"
    assert "read:packages" in failure.details


def test_classify_pull_failure_not_found() -> None:
    failure = sync_local_docker_release.classify_pull_failure(
        "ghcr.io/example/pro:pro-v2.0.14",
        "manifest unknown: manifest unknown",
    )
    assert failure.status == "not_found"
    assert "not found yet" in failure.details


def test_ghcr_login_if_possible_uses_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], bytes | None]] = []

    def fake_run(args, *, input=None, check=None, capture_output=None):
        calls.append((list(args), input))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setenv("GHCR_READ_TOKEN", "secret-token")
    monkeypatch.setattr(sync_local_docker_release.subprocess, "run", fake_run)

    assert sync_local_docker_release.ghcr_login_if_possible("georgy-agaev") is True
    assert calls == [
        (
            ["docker", "login", "ghcr.io", "-u", "georgy-agaev", "--password-stdin"],
            b"secret-token",
        )
    ]


def test_ghcr_login_if_possible_skips_missing_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_run(*_args, **_kwargs):
        raise AssertionError("docker login should not run without GHCR_READ_TOKEN")

    monkeypatch.delenv("GHCR_READ_TOKEN", raising=False)
    monkeypatch.setattr(sync_local_docker_release.subprocess, "run", fail_run)

    assert sync_local_docker_release.ghcr_login_if_possible("georgy-agaev") is False


def test_ghcr_login_if_possible_raises_actionable_error_for_bad_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args, **_kwargs):
        raise subprocess.CalledProcessError(
            1,
            ["docker", "login", "ghcr.io"],
            stderr="unauthorized",
        )

    monkeypatch.setenv("GHCR_READ_TOKEN", "bad-token")
    monkeypatch.setattr(sync_local_docker_release.subprocess, "run", fake_run)

    with pytest.raises(SystemExit, match="GHCR login failed"):
        sync_local_docker_release.ghcr_login_if_possible("georgy-agaev")


def test_pull_remote_image_raises_actionable_system_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args, **_kwargs):
        raise subprocess.CalledProcessError(
            1,
            ["docker", "pull", "ghcr.io/example/pro:pro-v2.0.14"],
            stderr="Error response from daemon: 403 Forbidden",
        )

    monkeypatch.setattr(sync_local_docker_release.subprocess, "run", fake_run)

    with pytest.raises(SystemExit, match="GHCR_READ_TOKEN"):
        sync_local_docker_release.pull_remote_image("ghcr.io/example/pro:pro-v2.0.14")
