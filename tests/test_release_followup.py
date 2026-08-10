from __future__ import annotations

from pathlib import Path

import pytest

from scripts import release_followup


def test_next_patch_version() -> None:
    assert release_followup.next_patch_version("2.0.13") == "2.0.14"


def test_update_changelog_for_release_moves_unreleased(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## Unreleased\n\n- First item.\n- Second item.\n\n## 2.0.13 - 2026-07-01\n\n- Older.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release_followup, "CHANGELOG", changelog)

    body = release_followup.update_changelog_for_release("2.0.14", "2026-07-09")

    assert body == "- First item.\n- Second item."
    text = changelog.read_text(encoding="utf-8")
    assert "## Unreleased\n\n## 2.0.14 - 2026-07-09" in text
    assert text.index("## 2.0.14 - 2026-07-09") < text.index("## 2.0.13 - 2026-07-01")


def test_update_changelog_for_release_is_idempotent_for_existing_heading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## Unreleased\n\n## 2.0.14 - 2026-07-09\n\n- Released item.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release_followup, "CHANGELOG", changelog)

    body = release_followup.update_changelog_for_release("2.0.14", "2026-07-09")

    assert body == "- Released item."
    assert changelog.read_text(encoding="utf-8").count("## 2.0.14 - 2026-07-09") == 1


def test_write_release_notes_renders_summary_and_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    releases_dir = tmp_path / "docs" / "releases"
    monkeypatch.setattr(release_followup, "RELEASES_DIR", releases_dir)

    path = release_followup.write_release_notes(
        "2.0.14",
        "2026-07-09",
        "- Released item.",
        issue_identifier="GEO-17",
        source_issue="GEO-15",
        pr_url="https://github.com/example/repo/pull/7",
        validations=["pytest -q", "python scripts/agent_lint.py"],
    )

    assert path == releases_dir / "v2.0.14.md"
    text = path.read_text(encoding="utf-8")
    assert "# v2.0.14" in text
    assert "- Release issue: `GEO-17`" in text
    assert "- Source PR issue: `GEO-15`" in text
    assert "- Released item." in text
    assert "- `pytest -q`" in text


def test_write_release_notes_keeps_existing_file_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    releases_dir = tmp_path / "docs" / "releases"
    path = releases_dir / "v2.0.14.md"
    path.parent.mkdir(parents=True)
    path.write_text("# v2.0.14\n\nExisting release notes.\n", encoding="utf-8")
    monkeypatch.setattr(release_followup, "RELEASES_DIR", releases_dir)

    returned = release_followup.write_release_notes(
        "2.0.14",
        "2026-07-09",
        "- New generated item.",
        issue_identifier="GEO-17",
        source_issue="GEO-15",
        pr_url="https://github.com/example/repo/pull/7",
        validations=["pytest -q"],
    )

    assert returned == path
    assert path.read_text(encoding="utf-8") == "# v2.0.14\n\nExisting release notes.\n"


def test_remove_stale_artifacts_preserves_stage_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release_followup, "ROOT", tmp_path)
    for name in release_followup.STALE_ARTIFACTS:
        (tmp_path / name).write_text("stale\n", encoding="utf-8")
    stage_handoff = tmp_path / "SYMPHONY_STAGE_HANDOFF.md"
    stage_handoff.write_text("PR-stage evidence\n", encoding="utf-8")

    release_followup.remove_stale_artifacts()

    assert all(not (tmp_path / name).exists() for name in release_followup.STALE_ARTIFACTS)
    assert stage_handoff.read_text(encoding="utf-8") == "PR-stage evidence\n"


def test_ensure_repo_ready_for_release_allows_only_release_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release_followup, "remove_stale_artifacts", lambda: None)
    monkeypatch.setattr(
        release_followup,
        "dirty_paths",
        lambda: ["pyproject.toml", "CHANGELOG.md", "docs/releases/v2.0.14.md"],
    )

    release_followup.ensure_repo_ready_for_release()


def test_ensure_repo_ready_for_release_removes_stale_artifacts_before_dirty_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_remove_stale_artifacts() -> None:
        calls.append("remove")

    def fake_dirty_paths() -> list[str]:
        assert calls == ["remove"]
        return ["CHANGELOG.md"]

    monkeypatch.setattr(release_followup, "remove_stale_artifacts", fake_remove_stale_artifacts)
    monkeypatch.setattr(release_followup, "dirty_paths", fake_dirty_paths)

    release_followup.ensure_repo_ready_for_release()

    assert calls == ["remove"]


def test_ensure_repo_ready_for_release_rejects_unexpected_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release_followup, "remove_stale_artifacts", lambda: None)
    monkeypatch.setattr(
        release_followup,
        "dirty_paths",
        lambda: ["pyproject.toml", "src/mcp_yandex_ad/server.py"],
    )

    with pytest.raises(SystemExit, match="unexpected dirty paths"):
        release_followup.ensure_repo_ready_for_release()


def test_failure_route_marks_live_validation_as_external() -> None:
    route = release_followup.failure_route(
        "python scripts/live_validation.py --suite direct,metrica,wordstat,search",
        "Direct API unavailable",
        external=True,
    )
    assert route == ("Backlog", "blocked", "operator")


def test_failure_route_marks_metadata_drift_as_todo() -> None:
    route = release_followup.failure_route(
        "python scripts/release_guard.py --version 2.0.14 --require-release-notes",
        "CHANGELOG missing release heading for 2.0.14",
        external=False,
    )
    assert route == ("Todo", "needs_changes", "implementation")


def test_ghcr_login_prefers_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[str, ...], str | None]] = []

    def fake_run(args, *, capture_output=False, input_text=None):
        calls.append((tuple(args), input_text))

        class Result:
            stdout = ""

        return Result()

    monkeypatch.setenv("GHCR_READ_TOKEN", "read-token")
    monkeypatch.setattr(release_followup, "run", fake_run)
    monkeypatch.setattr(release_followup, "gh_output", lambda *_args: "gh-token")

    release_followup.ghcr_login("georgy-agaev")

    assert calls == [
        (("docker", "login", "ghcr.io", "-u", "georgy-agaev", "--password-stdin"), "read-token\n")
    ]


def test_ghcr_login_falls_back_to_gh_auth_token(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[str, ...], str | None]] = []

    def fake_run(args, *, capture_output=False, input_text=None):
        calls.append((tuple(args), input_text))

        class Result:
            stdout = ""

        return Result()

    monkeypatch.delenv("GHCR_READ_TOKEN", raising=False)
    monkeypatch.setattr(release_followup, "run", fake_run)
    monkeypatch.setattr(release_followup, "gh_output", lambda *args: "gh-cli-token")

    release_followup.ghcr_login("georgy-agaev")

    assert calls == [
        (("docker", "login", "ghcr.io", "-u", "georgy-agaev", "--password-stdin"), "gh-cli-token\n")
    ]
