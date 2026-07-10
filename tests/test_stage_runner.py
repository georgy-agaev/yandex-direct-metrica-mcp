from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from scripts import stage


def init_repo(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)


def write_handoff(workspace: Path, payload: dict) -> None:
    (workspace / "SYMPHONY_HANDOFF.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def feature_impl_handoff(iteration: int = 1, max_iterations: int = 3) -> dict:
    return {
        "schema_version": 1,
        "issue": {"identifier": "GEO-18", "title": "Automation"},
        "stage": {"type": "feature", "role": "implementation"},
        "transition": {"from_state": "In Progress", "to_state": "In Review", "status": "needs_review"},
        "cycle": {"iteration": iteration, "max_iterations": max_iterations},
        "summary": "summary",
        "artifacts": ["SYMPHONY_WORK_RESULT.md", "SYMPHONY_HANDOFF.json"],
        "validation": {"passed": ["pytest -q tests/test_stage_runner.py"]},
        "next_actor": "review",
        "blockers": [],
    }


def test_detect_stage_routes_feature_pr_release() -> None:
    assert stage.detect_stage(["symphony"]) == "feature"
    assert stage.detect_stage(["issue-type:pr", "symphony"]) == "pr"
    assert stage.detect_stage(["issue-type:release", "symphony"]) == "release"


def test_resolve_stage_uses_labels_when_stage_missing() -> None:
    assert stage.resolve_stage(Namespace(stage=None, labels="symphony,issue-type:pr")) == "pr"


def test_resolve_stage_extracts_issue_type_from_compact_label_text() -> None:
    assert stage.resolve_stage(Namespace(stage=None, labels="symphonyissue-type:featureautomation")) == "feature"
    assert stage.resolve_stage(Namespace(stage=None, labels="symphonyissue-type:prautomation")) == "pr"
    assert stage.resolve_stage(Namespace(stage=None, labels="symphonyissue-type:releaseautomation")) == "release"


def test_resolve_stage_prefers_explicit_stage_over_labels() -> None:
    assert stage.resolve_stage(Namespace(stage="release", labels="symphony,issue-type:pr")) == "release"


def test_stage_script_context_runs_as_file(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/stage.py",
            "context",
            "--lane",
            "implementation",
            "--labels",
            "symphony",
            "--issue-id",
            "GEO-TEST",
            "--title",
            "t",
            "--state",
            "In Progress",
            "--workspace",
            str(tmp_path),
        ],
        cwd=Path(__file__).resolve().parent.parent,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["stage"] == "feature"
    assert payload["validation_section"] == "Feature Validation"


def test_context_loads_existing_handoff_cycle(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_handoff(workspace, feature_impl_handoff(iteration=2, max_iterations=4))

    payload = stage.context_payload(
        Namespace(
            lane="implementation",
            issue_id="GEO-18",
            title="Automation",
            state="Todo",
            labels="symphony,issue-type:feature",
            workspace=workspace,
        )
    )

    assert payload["stage"] == "feature"
    assert payload["handoff_exists"] is True
    assert payload["cycle"] == {"iteration": 2, "max_iterations": 4}
    assert payload["validation_section"] == "Feature Validation"


def test_context_rejects_invalid_cycle(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_handoff(workspace, feature_impl_handoff(iteration=5, max_iterations=4))

    with pytest.raises(SystemExit, match="must not exceed"):
        stage.context_payload(
            Namespace(
                lane="implementation",
                issue_id="GEO-18",
                title="Automation",
                state="Todo",
                labels="symphony,issue-type:feature",
                workspace=workspace,
            )
        )


def test_implementation_ready_writes_machine_readable_outcome_and_verifies_feature(tmp_path: Path) -> None:
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
    workspace.mkdir()
    (workspace / "SYMPHONY_STAGE_PATCH.diff").write_text(patch, encoding="utf-8")
    (workspace / "SYMPHONY_STAGE_HANDOFF.md").write_text(
        "# Handoff\n\nApply with `git apply SYMPHONY_STAGE_PATCH.diff`\n",
        encoding="utf-8",
    )

    payload = stage.implementation_ready(
        Namespace(
            stage="feature",
            issue_id="GEO-18",
            title="Automation",
            summary="Prepared feature handoff",
            workspace=workspace,
            repo=repo,
            from_state="In Progress",
            validation=["pytest -q tests/test_stage_runner.py"],
            artifact=["SYMPHONY_STAGE_HANDOFF.md", "SYMPHONY_STAGE_PATCH.diff"],
            details_file=None,
        )
    )

    assert payload == {"ok": True, "stage": "feature", "to_state": "In Review", "status": "needs_review"}
    handoff = json.loads((workspace / "SYMPHONY_HANDOFF.json").read_text(encoding="utf-8"))
    assert handoff["next_actor"] == "review"
    assert handoff["validation"]["passed"] == ["pytest -q tests/test_stage_runner.py"]


def test_review_finish_increments_retry_and_emits_machine_outcome(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SYMPHONY_STAGE_HANDOFF.md").write_text(
        "# Handoff\n\nApply with `git apply SYMPHONY_STAGE_PATCH.diff`\n",
        encoding="utf-8",
    )
    (workspace / "SYMPHONY_STAGE_PATCH.diff").write_text("", encoding="utf-8")
    (workspace / "SYMPHONY_WORK_RESULT.md").write_text("# Result\n", encoding="utf-8")
    write_handoff(
        workspace,
        {
            **feature_impl_handoff(iteration=1, max_iterations=3),
            "artifacts": [
                "SYMPHONY_WORK_RESULT.md",
                "SYMPHONY_HANDOFF.json",
                "SYMPHONY_STAGE_HANDOFF.md",
                "SYMPHONY_STAGE_PATCH.diff",
            ],
        },
    )

    payload = stage.review_finish(
        Namespace(
            stage="feature",
            issue_id="GEO-18",
            title="Automation",
            outcome="needs_changes",
            summary="Need one fix",
            workspace=workspace,
            validation=["pytest -q tests/test_stage_runner.py"],
            artifact=["SYMPHONY_STAGE_HANDOFF.md", "SYMPHONY_STAGE_PATCH.diff"],
            blocker=[],
            details_file=None,
            next_actor="implementation",
            from_state="In Review",
        )
    )

    assert payload == {"ok": True, "stage": "feature", "to_state": "Todo", "status": "needs_changes"}
    handoff = json.loads((workspace / "SYMPHONY_HANDOFF.json").read_text(encoding="utf-8"))
    assert handoff["cycle"] == {"iteration": 2, "max_iterations": 3}


def test_review_finish_routes_release_required_pr_to_followup_release(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SYMPHONY_STAGE_HANDOFF.md").write_text(
        "branch: issue/geo-18\ncommit: abc123\nPR URL: https://example.test/pr/1\n",
        encoding="utf-8",
    )
    (workspace / "SYMPHONY_WORK_RESULT.md").write_text("# Result\n", encoding="utf-8")
    write_handoff(
        workspace,
        {
            "schema_version": 1,
            "issue": {"identifier": "GEO-18", "title": "Automation"},
            "stage": {"type": "pr", "role": "implementation"},
            "transition": {"from_state": "In Progress", "to_state": "In Review", "status": "needs_review"},
            "cycle": {"iteration": 1, "max_iterations": 3},
            "summary": "summary",
            "artifacts": ["SYMPHONY_WORK_RESULT.md", "SYMPHONY_HANDOFF.json", "SYMPHONY_STAGE_HANDOFF.md"],
            "validation": {"passed": ["pytest -q tests/test_stage_runner.py"]},
            "next_actor": "review",
            "blockers": [],
        },
    )

    payload = stage.review_finish(
        Namespace(
            stage="pr",
            issue_id="GEO-18",
            title="Automation",
            outcome="approved",
            summary="Approved",
            workspace=workspace,
            validation=["pytest -q tests/test_stage_runner.py"],
            artifact=["SYMPHONY_STAGE_HANDOFF.md"],
            blocker=[],
            details_file=None,
            next_actor=None,
            release_required=True,
            from_state="In Review",
        )
    )

    assert payload == {"ok": True, "stage": "pr", "to_state": "Done", "status": "approved"}
    handoff = json.loads((workspace / "SYMPHONY_HANDOFF.json").read_text(encoding="utf-8"))
    assert handoff["next_actor"] == "followup-release"


def test_review_finish_rejects_needs_changes_at_max_iterations(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_handoff(workspace, feature_impl_handoff(iteration=3, max_iterations=3))

    with pytest.raises(SystemExit, match="use blocked instead"):
        stage.review_finish(
            Namespace(
                stage="feature",
                issue_id="GEO-18",
                title="Automation",
                outcome="needs_changes",
                summary="Need one fix",
                workspace=workspace,
                validation=["pytest -q tests/test_stage_runner.py"],
                artifact=[],
                blocker=[],
                details_file=None,
                next_actor="implementation",
                from_state="In Review",
            )
        )
