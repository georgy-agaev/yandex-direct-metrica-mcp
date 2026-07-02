from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import stage_handoff


def init_repo(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)


def write_handoff(workspace: Path, payload: dict) -> None:
    (workspace / "SYMPHONY_HANDOFF.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def feature_handoff_payload(*, role: str, to_state: str, status: str, next_actor: str = "review") -> dict:
    return {
        "schema_version": 1,
        "issue": {"identifier": "GEO-12", "title": "Normalize search_serp"},
        "stage": {"type": "feature", "role": role},
        "transition": {"from_state": "In Progress", "to_state": to_state, "status": status},
        "cycle": {"iteration": 1},
        "summary": "Feature stage summary",
        "artifacts": [
            "SYMPHONY_WORK_RESULT.md",
            "SYMPHONY_HANDOFF.json",
            "SYMPHONY_STAGE_HANDOFF.md",
            "SYMPHONY_STAGE_PATCH.diff",
        ],
        "validation": {"passed": ["pytest -q tests/test_search_serp.py"]},
        "next_actor": next_actor,
        "blockers": [],
    }


def pr_handoff_payload(*, role: str, to_state: str, status: str, next_actor: str = "review") -> dict:
    return {
        "schema_version": 1,
        "issue": {"identifier": "GEO-13", "title": "PR: GEO-12"},
        "stage": {"type": "pr", "role": role},
        "transition": {"from_state": "In Progress", "to_state": to_state, "status": status},
        "cycle": {"iteration": 2},
        "summary": "PR stage summary",
        "artifacts": [
            "SYMPHONY_WORK_RESULT.md",
            "SYMPHONY_HANDOFF.json",
            "SYMPHONY_STAGE_HANDOFF.md",
        ],
        "validation": {"passed": ["pytest -q", "python scripts/agent_lint.py"]},
        "next_actor": next_actor,
        "blockers": [],
    }


def make_feature_workspace(workspace: Path, patch_body: str, payload: dict | None = None) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "SYMPHONY_WORK_RESULT.md").write_text("# Result\n", encoding="utf-8")
    (workspace / "SYMPHONY_STAGE_HANDOFF.md").write_text(
        "# Handoff\n\nApply with `git apply SYMPHONY_STAGE_PATCH.diff`\n",
        encoding="utf-8",
    )
    (workspace / "SYMPHONY_STAGE_PATCH.diff").write_text(patch_body, encoding="utf-8")
    write_handoff(workspace, payload or feature_handoff_payload(role="implementation", to_state="In Review", status="needs_review"))


def make_pr_workspace(workspace: Path, payload: dict | None = None) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "SYMPHONY_WORK_RESULT.md").write_text("# Result\n", encoding="utf-8")
    (workspace / "SYMPHONY_STAGE_HANDOFF.md").write_text(
        "branch: feature/geo-12\ncommit: abc123\nPR URL: https://example.test/pr/1\n",
        encoding="utf-8",
    )
    write_handoff(workspace, payload or pr_handoff_payload(role="implementation", to_state="In Review", status="needs_review"))


def test_verify_feature_accepts_portable_patch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)

    updated = repo / "README.md"
    updated.write_text("base\nfeature\n", encoding="utf-8")
    patch = subprocess.run(
        ["git", "diff", "--binary", "--", "README.md"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    updated.write_text("base\n", encoding="utf-8")

    workspace = tmp_path / "workspace"
    make_feature_workspace(workspace, patch)

    stage_handoff.verify_feature(workspace, repo)


def test_verify_feature_rejects_missing_universal_handoff(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SYMPHONY_WORK_RESULT.md").write_text("# Result\n", encoding="utf-8")
    (workspace / "SYMPHONY_STAGE_HANDOFF.md").write_text("# Handoff\n", encoding="utf-8")
    (workspace / "SYMPHONY_STAGE_PATCH.diff").write_text("", encoding="utf-8")

    with pytest.raises(SystemExit, match="SYMPHONY_HANDOFF.json"):
        stage_handoff.verify_feature(workspace, repo)


def test_verify_pr_requires_branch_commit_and_pr_url(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    make_pr_workspace(workspace)
    stage_handoff.verify_pr(workspace)


def test_review_verify_needs_changes_requires_review_handoff(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    make_feature_workspace(
        workspace,
        patch_body="",
        payload=feature_handoff_payload(
            role="review",
            to_state="Todo",
            status="needs_changes",
            next_actor="implementation",
        ),
    )
    stage_handoff.verify_review(workspace, "feature", "needs_changes")


def test_review_verify_blocked_requires_blockers(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SYMPHONY_WORK_RESULT.md").write_text("# Result\n", encoding="utf-8")
    write_handoff(
        workspace,
        {
            "schema_version": 1,
            "issue": {"identifier": "GEO-12", "title": "Normalize search_serp"},
            "stage": {"type": "feature", "role": "review"},
            "transition": {"from_state": "In Review", "to_state": "Backlog", "status": "blocked"},
            "cycle": {"iteration": 2},
            "summary": "Missing operator evidence",
            "artifacts": ["SYMPHONY_WORK_RESULT.md", "SYMPHONY_HANDOFF.json"],
            "validation": {"passed": ["pytest -q tests/test_search_serp.py"]},
            "next_actor": "operator",
            "blockers": [],
        },
    )

    with pytest.raises(SystemExit, match="Blocked handoff must include at least one blocker"):
        stage_handoff.verify_review(workspace, "feature", "blocked")


def test_apply_feature_patch_recovers_archived_workspace(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)

    updated = repo / "README.md"
    updated.write_text("base\nfeature\n", encoding="utf-8")
    patch = subprocess.run(
        ["git", "diff", "--binary", "--", "README.md"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    updated.write_text("base\n", encoding="utf-8")

    root = tmp_path / "workspaces"
    workspace = root / "GEO-12.stale-2026-07-02T0800"
    make_feature_workspace(workspace, patch)

    stage_handoff.apply_feature_patch(root / "GEO-12", repo)
    assert (repo / "README.md").read_text(encoding="utf-8") == "base\nfeature\n"
