from __future__ import annotations

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


def make_feature_workspace(workspace: Path, patch_body: str) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "SYMPHONY_WORK_RESULT.md").write_text("# Result\n", encoding="utf-8")
    (workspace / "SYMPHONY_STAGE_HANDOFF.md").write_text(
        "# Handoff\n\nApply with `git apply SYMPHONY_STAGE_PATCH.diff`\n",
        encoding="utf-8",
    )
    (workspace / "SYMPHONY_STAGE_PATCH.diff").write_text(patch_body, encoding="utf-8")


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


def test_verify_feature_rejects_missing_patch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_repo(repo)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SYMPHONY_WORK_RESULT.md").write_text("# Result\n", encoding="utf-8")
    (workspace / "SYMPHONY_STAGE_HANDOFF.md").write_text("# Handoff\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="Missing handoff artifacts"):
        stage_handoff.verify_feature(workspace, repo)


def test_verify_pr_requires_branch_commit_and_pr_url(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SYMPHONY_WORK_RESULT.md").write_text("# Result\n", encoding="utf-8")
    (workspace / "SYMPHONY_STAGE_HANDOFF.md").write_text(
        "branch: test\ncommit: abc123\nPR URL: https://example.test/pr/1\n",
        encoding="utf-8",
    )

    stage_handoff.verify_pr(workspace)
