from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import symphony_control


def test_resolve_codex_home_prefers_explicit_path(tmp_path) -> None:
    explicit = tmp_path / "explicit-codex-home"
    env = {"CODEX_HOME": str(tmp_path / "env-codex-home")}

    resolved = symphony_control.resolve_codex_home(explicit, env)

    assert resolved == explicit.resolve()


def test_resolve_codex_home_uses_env_when_no_explicit_path(tmp_path) -> None:
    env_home = tmp_path / "env-codex-home"

    resolved = symphony_control.resolve_codex_home(None, {"CODEX_HOME": str(env_home)})

    assert resolved == env_home.resolve()


def test_resolve_codex_home_falls_back_to_repo_default(monkeypatch, tmp_path) -> None:
    default_home = tmp_path / ".codex"
    monkeypatch.setattr(symphony_control, "DEFAULT_CODEX_HOME", default_home)

    resolved = symphony_control.resolve_codex_home(None, {})

    assert resolved == default_home.resolve()


def test_build_env_respects_state_env_codex_home_when_no_explicit_override(tmp_path) -> None:
    symphony_root = tmp_path / "symphony"
    symphony_root.mkdir()
    state_env = tmp_path / "state.env"
    state_env.write_text("CODEX_HOME=/tmp/state-codex-home\nLINEAR_API_KEY=test\n", encoding="utf-8")
    workspace_root = tmp_path / "workspaces"

    env = symphony_control.build_env(symphony_root, workspace_root, state_env, None)

    assert env["CODEX_HOME"] == str(Path("/tmp/state-codex-home").resolve())
    assert env["LINEAR_API_KEY"] == "test"


def test_build_env_explicit_codex_home_overrides_state_env(tmp_path) -> None:
    symphony_root = tmp_path / "symphony"
    symphony_root.mkdir()
    state_env = tmp_path / "state.env"
    state_env.write_text("CODEX_HOME=/tmp/state-codex-home\n", encoding="utf-8")
    workspace_root = tmp_path / "workspaces"
    explicit = tmp_path / "explicit-codex-home"

    env = symphony_control.build_env(symphony_root, workspace_root, state_env, explicit)

    assert env["CODEX_HOME"] == str(explicit.resolve())


def _completed(*, returncode: int = 0, stdout: str = "", stderr: str = ""):
    class Result:
        pass

    result = Result()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def test_verify_codex_runtime_accepts_logged_in_reachable_profile(monkeypatch, tmp_path) -> None:
    responses = iter(
        [
            _completed(stdout="Logged in using ChatGPT\n"),
            _completed(
                returncode=1,
                stdout=json.dumps(
                    {
                        "checks": {
                            "auth.credentials": {"status": "ok"},
                            "network.provider_reachability": {
                                "status": "ok",
                                "summary": "provider reachable",
                            },
                        }
                    }
                ),
            ),
        ]
    )
    monkeypatch.setattr(symphony_control, "run_codex_command", lambda *args, **kwargs: next(responses))

    symphony_control.verify_codex_runtime(tmp_path, {"CODEX_HOME": str(tmp_path / ".codex")})


def test_verify_codex_runtime_blocks_when_provider_unreachable(monkeypatch, tmp_path) -> None:
    responses = iter(
        [
            _completed(stdout="Logged in using ChatGPT\n"),
            _completed(
                returncode=1,
                stdout=json.dumps(
                    {
                        "checks": {
                            "auth.credentials": {"status": "ok"},
                            "network.provider_reachability": {
                                "status": "fail",
                                "summary": "required provider endpoints are unreachable",
                            },
                        }
                    }
                ),
            ),
        ]
    )
    monkeypatch.setattr(symphony_control, "run_codex_command", lambda *args, **kwargs: next(responses))

    with pytest.raises(SystemExit, match="required provider endpoints are unreachable"):
        symphony_control.verify_codex_runtime(tmp_path, {"CODEX_HOME": str(tmp_path / ".codex")})
