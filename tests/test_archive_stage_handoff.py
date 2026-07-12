from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import archive_stage_handoff


def make_issue(
    *,
    identifier: str = "GEO-29",
    title: str = "PR stage",
    state: str = "Done",
    labels: list[str] | None = None,
) -> dict:
    return {
        "id": "issue-id",
        "identifier": identifier,
        "title": title,
        "url": f"https://linear.app/example/{identifier}",
        "state": {"name": state},
        "team": {"id": "team-id"},
        "project": {"id": "project-id", "name": "Yandex.AD"},
        "labels": {"nodes": [{"name": label} for label in (labels or ["symphony"])]},
    }


def test_required_followup_stage_routes_feature_and_release_required_pr() -> None:
    feature = make_issue(labels=["symphony", "issue-type:feature"])
    pr_release = make_issue(labels=["symphony", "issue-type:pr", "release-required", "generated-followup"])
    release = make_issue(labels=["symphony", "issue-type:release", "generated-followup"])

    assert archive_stage_handoff.required_followup_stage(feature) == "pr"
    assert archive_stage_handoff.required_followup_stage(pr_release) == "release"
    assert archive_stage_handoff.required_followup_stage(release) is None


def test_synthesize_review_handoff_for_pr_issue(tmp_path: Path) -> None:
    workspace = tmp_path / "GEO-29"
    workspace.mkdir()
    (workspace / "SYMPHONY_WORK_RESULT.md").write_text("result\n", encoding="utf-8")
    (workspace / "SYMPHONY_STAGE_HANDOFF.md").write_text(
        "\n".join(
            [
                "# GEO-29 PR Stage Handoff",
                "branch: issue/geo-29",
                "commit: abc123",
                "PR URL: https://github.com/example/pr/11",
                "merge status: merged",
                "merge commit: def456",
            ]
        ),
        encoding="utf-8",
    )
    issue = make_issue(labels=["symphony", "issue-type:pr", "release-required", "generated-followup"])

    payload = archive_stage_handoff.synthesize_review_handoff(workspace, issue)

    assert payload is not None
    handoff = json.loads((workspace / "SYMPHONY_HANDOFF.json").read_text(encoding="utf-8"))
    assert handoff["stage"] == {"type": "pr", "role": "review"}
    assert handoff["transition"]["to_state"] == "Done"
    assert handoff["transition"]["status"] == "approved"
    assert handoff["next_actor"] == "followup-release"
    assert "SYMPHONY_STAGE_HANDOFF.md" in handoff["artifacts"]


def test_recover_pr_stage_artifacts_from_git_and_github(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "GEO-29"
    workspace.mkdir()
    issue = make_issue(labels=["symphony", "issue-type:pr", "release-required", "generated-followup"])
    monkeypatch.setattr(archive_stage_handoff, "ROOT", workspace)

    def fake_run(command: list[str], cwd: Path, check: bool, capture_output: bool, text: bool):
        assert cwd == workspace
        assert check is True
        assert capture_output is True
        assert text is True
        if command == ["git", "branch", "--show-current"]:
            return subprocess.CompletedProcess(command, 0, stdout="issue/geo-29\n", stderr="")
        if command == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(command, 0, stdout="abc123\n", stderr="")
        if command[:4] == ["gh", "pr", "list", "--state"]:
            payload = [
                {
                    "number": 11,
                    "title": "GEO-29: PR stage",
                    "headRefName": "issue/geo-29",
                }
            ]
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")
        if command[:4] == ["gh", "pr", "view", "11"]:
            payload = {
                "number": 11,
                "title": "GEO-29: PR stage",
                "url": "https://github.com/example/repo/pull/11",
                "state": "MERGED",
                "mergedAt": "2026-07-12T04:54:18Z",
                "mergeCommit": {"oid": "def456"},
                "headRefName": "issue/geo-29",
                "headRefOid": "abc123",
            }
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(archive_stage_handoff.subprocess, "run", fake_run)

    payload = archive_stage_handoff.recover_pr_stage_artifacts(workspace, issue)

    assert payload == {
        "branch": "issue/geo-29",
        "commit": "abc123",
        "pr_url": "https://github.com/example/repo/pull/11",
        "merge_commit": "def456",
        "merged_at": "2026-07-12T04:54:18Z",
    }
    stage_handoff = (workspace / "SYMPHONY_STAGE_HANDOFF.md").read_text(encoding="utf-8")
    assert "branch: issue/geo-29" in stage_handoff
    assert "PR URL: https://github.com/example/repo/pull/11" in stage_handoff
    assert "merge status: merged" in stage_handoff
    assert "merge commit: def456" in stage_handoff
    work_result = (workspace / "SYMPHONY_WORK_RESULT.md").read_text(encoding="utf-8")
    assert "Recovered final PR-stage publication metadata" in work_result


def test_recover_pr_stage_artifacts_from_issue_identifier_when_branch_is_gone(
    monkeypatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "GEO-29.handoff-2026-07-12T120340Z"
    workspace.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    issue = make_issue(labels=["symphony", "issue-type:pr", "release-required", "generated-followup"])

    monkeypatch.setattr(archive_stage_handoff, "ROOT", repo)

    def fake_run(command: list[str], cwd: Path, check: bool, capture_output: bool, text: bool):
        assert check is True
        assert capture_output is True
        assert text is True
        if command == ["git", "branch", "--show-current"]:
            raise subprocess.CalledProcessError(128, command, stderr="fatal: not a git repository")
        if command[:4] == ["gh", "pr", "list", "--state"]:
            assert cwd == repo
            assert command[4:6] == ["all", "--search"]
            payload = [
                {
                    "number": 16,
                    "title": "GEO-29: PR: smoke rerun",
                    "headRefName": "issue/geo-29-pr-smoke",
                }
            ]
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")
        if command[:4] == ["gh", "pr", "view", "16"]:
            assert cwd == repo
            payload = {
                "number": 16,
                "title": "GEO-29: PR: smoke rerun",
                "url": "https://github.com/example/repo/pull/16",
                "state": "MERGED",
                "mergedAt": "2026-07-12T12:03:36Z",
                "mergeCommit": {"oid": "220e22f"},
                "headRefName": "issue/geo-29-pr-smoke",
                "headRefOid": "5eb337e",
            }
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(archive_stage_handoff.subprocess, "run", fake_run)

    payload = archive_stage_handoff.recover_pr_stage_artifacts(workspace, issue)

    assert payload == {
        "branch": "issue/geo-29-pr-smoke",
        "commit": "5eb337e",
        "pr_url": "https://github.com/example/repo/pull/16",
        "merge_commit": "220e22f",
        "merged_at": "2026-07-12T12:03:36Z",
    }
    assert "issue/geo-29-pr-smoke" in (workspace / "SYMPHONY_STAGE_HANDOFF.md").read_text(encoding="utf-8")


def test_reconcile_followup_creates_missing_release_followup(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "GEO-29"
    workspace.mkdir()
    (workspace / "SYMPHONY_WORK_RESULT.md").write_text("result\n", encoding="utf-8")
    (workspace / "SYMPHONY_STAGE_HANDOFF.md").write_text(
        "\n".join(
            [
                "# GEO-29 PR Stage Handoff",
                "branch: issue/geo-29",
                "commit: abc123",
                "PR URL: https://github.com/example/pr/11",
                "merge status: merged",
                "merge commit: def456",
            ]
        ),
        encoding="utf-8",
    )
    issue = make_issue(labels=["symphony", "issue-type:pr", "release-required", "generated-followup"])
    created_calls: list[tuple[str, str]] = []

    monkeypatch.setenv("LINEAR_API_KEY", "token")
    monkeypatch.setattr(archive_stage_handoff.linear_issue, "get_issue", lambda *_args, **_kwargs: issue)
    monkeypatch.setattr(
        archive_stage_handoff.linear_issue,
        "find_generated_followup_issue",
        lambda *_args, **_kwargs: None,
    )

    def fake_ensure_followup_issue(_api_key: str, source_issue: dict, stage: str, **_kwargs) -> dict:
        created_calls.append((source_issue["identifier"], stage))
        return {
            "identifier": "GEO-30",
            "url": "https://linear.app/example/GEO-30",
        }

    monkeypatch.setattr(archive_stage_handoff.linear_issue, "ensure_followup_issue", fake_ensure_followup_issue)

    payload = archive_stage_handoff.reconcile_followup(workspace, "GEO-29")

    assert payload == {
        "status": "created",
        "stage": "release",
        "identifier": "GEO-30",
        "url": "https://linear.app/example/GEO-30",
    }
    assert created_calls == [("GEO-29", "release")]
    assert (workspace / "SYMPHONY_HANDOFF.json").exists()


def test_reconcile_followup_recovers_pr_artifacts_before_creating_release_followup(
    monkeypatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "GEO-29"
    workspace.mkdir()
    issue = make_issue(labels=["symphony", "issue-type:pr", "release-required", "generated-followup"])
    created_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(archive_stage_handoff, "ROOT", workspace)

    def fake_run(command: list[str], cwd: Path, check: bool, capture_output: bool, text: bool):
        assert cwd == workspace
        if command == ["git", "branch", "--show-current"]:
            return subprocess.CompletedProcess(command, 0, stdout="issue/geo-29\n", stderr="")
        if command == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(command, 0, stdout="abc123\n", stderr="")
        if command[:4] == ["gh", "pr", "list", "--state"]:
            payload = [
                {
                    "number": 11,
                    "title": "GEO-29: PR stage",
                    "headRefName": "issue/geo-29",
                }
            ]
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")
        if command[:4] == ["gh", "pr", "view", "11"]:
            payload = {
                "number": 11,
                "title": "GEO-29: PR stage",
                "url": "https://github.com/example/repo/pull/11",
                "state": "MERGED",
                "mergedAt": "2026-07-12T04:54:18Z",
                "mergeCommit": {"oid": "def456"},
                "headRefName": "issue/geo-29",
                "headRefOid": "abc123",
            }
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setenv("LINEAR_API_KEY", "token")
    monkeypatch.setattr(archive_stage_handoff.subprocess, "run", fake_run)
    monkeypatch.setattr(archive_stage_handoff.linear_issue, "get_issue", lambda *_args, **_kwargs: issue)
    monkeypatch.setattr(
        archive_stage_handoff.linear_issue,
        "find_generated_followup_issue",
        lambda *_args, **_kwargs: None,
    )

    def fake_ensure_followup_issue(_api_key: str, source_issue: dict, stage: str, **_kwargs) -> dict:
        created_calls.append((source_issue["identifier"], stage))
        assert (workspace / "SYMPHONY_STAGE_HANDOFF.md").exists()
        assert (workspace / "SYMPHONY_WORK_RESULT.md").exists()
        assert (workspace / "SYMPHONY_HANDOFF.json").exists()
        return {
            "identifier": "GEO-30",
            "url": "https://linear.app/example/GEO-30",
        }

    monkeypatch.setattr(archive_stage_handoff.linear_issue, "ensure_followup_issue", fake_ensure_followup_issue)

    payload = archive_stage_handoff.reconcile_followup(workspace, "GEO-29")

    assert payload == {
        "status": "created",
        "stage": "release",
        "identifier": "GEO-30",
        "url": "https://linear.app/example/GEO-30",
    }
    assert created_calls == [("GEO-29", "release")]


def test_load_issue_identifier_from_archive_name(tmp_path: Path) -> None:
    workspace = tmp_path / "GEO-39.handoff-2026-07-12T120340Z"
    workspace.mkdir()
    assert archive_stage_handoff.load_issue_identifier(workspace) == "GEO-39"


def test_reconcile_followup_noops_when_followup_already_exists(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "GEO-29"
    workspace.mkdir()
    issue = make_issue(labels=["symphony", "issue-type:pr", "release-required", "generated-followup"])

    monkeypatch.setenv("LINEAR_API_KEY", "token")
    monkeypatch.setattr(archive_stage_handoff.linear_issue, "get_issue", lambda *_args, **_kwargs: issue)
    monkeypatch.setattr(
        archive_stage_handoff.linear_issue,
        "find_generated_followup_issue",
        lambda *_args, **_kwargs: {
            "identifier": "GEO-30",
            "url": "https://linear.app/example/GEO-30",
        },
    )

    payload = archive_stage_handoff.reconcile_followup(workspace, "GEO-29")

    assert payload == {
        "status": "exists",
        "stage": "release",
        "identifier": "GEO-30",
        "url": "https://linear.app/example/GEO-30",
    }


def test_reconcile_followup_records_blocker_when_workspace_cannot_seed_followup(
    monkeypatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "GEO-29"
    workspace.mkdir()
    issue = make_issue(labels=["symphony", "issue-type:pr", "release-required", "generated-followup"])
    comments: list[tuple[str, str]] = []

    monkeypatch.setenv("LINEAR_API_KEY", "token")
    monkeypatch.setattr(archive_stage_handoff.linear_issue, "get_issue", lambda *_args, **_kwargs: issue)
    monkeypatch.setattr(
        archive_stage_handoff.linear_issue,
        "find_generated_followup_issue",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        archive_stage_handoff.linear_issue,
        "ensure_followup_issue",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SystemExit("Missing handoff artifacts in workspace")),
    )
    monkeypatch.setattr(
        archive_stage_handoff.linear_issue,
        "comment_issue",
        lambda _api_key, issue_id, body: comments.append((issue_id, body)) or {"id": "comment-1"},
    )

    payload = archive_stage_handoff.reconcile_followup(workspace, "GEO-29")

    assert payload == {
        "status": "blocked",
        "stage": "release",
        "reason": "Missing handoff artifacts in workspace",
    }
    assert comments == [
        (
            "issue-id",
            "Symphony follow-up recovery blocked for `release`: Missing handoff artifacts in workspace",
        )
    ]
