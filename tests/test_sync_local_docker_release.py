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


def test_classify_pull_failure_forbidden() -> None:
    failure = sync_local_docker_release.classify_pull_failure(
        "ghcr.io/example/pro:pro-v2.0.14",
        "Error response from daemon: Head https://ghcr.io/v2/...: 403 Forbidden",
    )
    assert failure.status == "forbidden"
    assert "GHCR_READ_TOKEN" in failure.details


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
