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


def allow_linear_move(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str, str | None]]:
    calls: list[tuple[str, str, str, str | None]] = []

    def fake_move(issue_id: str, *, to_state: str, by: str, expect: str | None = None, client=None) -> dict:
        calls.append((issue_id, to_state, by, expect))
        return {
            "ok": True,
            "issue_id": issue_id,
            "reason": "allowed",
            "by": by,
            "from_state": expect or "unknown",
            "to_state": to_state,
            "updated_state": to_state,
        }

    monkeypatch.setattr(stage.linear_state, "move_issue", fake_move)
    return calls


def reject_linear_move(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str, str | None]]:
    calls: list[tuple[str, str, str, str | None]] = []

    def fake_move(issue_id: str, *, to_state: str, by: str, expect: str | None = None, client=None) -> dict:
        calls.append((issue_id, to_state, by, expect))
        return {
            "ok": False,
            "issue_id": issue_id,
            "reason": "state_mismatch",
            "by": by,
            "expected_state": expect,
            "actual_state": "Todo",
        }

    monkeypatch.setattr(stage.linear_state, "move_issue", fake_move)
    return calls


def allow_followup_creation(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, bool]]:
    calls: list[tuple[str, str, bool]] = []

    def fake_create_followup_for_review(*, issue_id: str, stage: str, release_required: bool = False) -> dict:
        calls.append((issue_id, stage, release_required))
        mapped_stage = "release" if stage == "pr" and release_required else "pr"
        return {
            "stage": mapped_stage,
            "identifier": "GEO-24",
            "url": "https://linear.app/example/GEO-24",
        }

    monkeypatch.setattr(stage, "create_followup_for_review", fake_create_followup_for_review)
    return calls


def reject_followup_creation(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, bool]]:
    calls: list[tuple[str, str, bool]] = []

    def fake_create_followup_for_review(*, issue_id: str, stage: str, release_required: bool = False) -> dict:
        calls.append((issue_id, stage, release_required))
        raise SystemExit("followup creation failed")

    monkeypatch.setattr(stage, "create_followup_for_review", fake_create_followup_for_review)
    return calls


def test_detect_stage_routes_feature_pr_release() -> None:
    assert stage.detect_stage(["symphony"]) == "feature"
    assert stage.detect_stage(["issue-type:pr", "symphony"]) == "pr"
    assert stage.detect_stage(["issue-type:release", "symphony"]) == "release"


def test_resolve_stage_uses_labels_when_stage_missing() -> None:
    assert stage.resolve_stage(Namespace(stage=None, labels="symphony,issue-type:pr")) == "pr"


def test_resolve_stage_extracts_issue_type_from_compact_label_text() -> None:
    # Guards launcher-provided label strings that arrive without separators.
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


def test_implementation_ready_writes_machine_readable_outcome_and_verifies_feature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = allow_linear_move(monkeypatch)
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
    assert calls == [("GEO-18", "In Review", "implementation", "In Progress")]


def test_review_finish_increments_retry_and_emits_machine_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = allow_linear_move(monkeypatch)
    monkeypatch.setattr(stage, "create_followup_for_review", lambda **_: None)
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
    assert calls == [("GEO-18", "Todo", "review", "In Review")]


def test_review_finish_feature_approved_creates_pr_followup_before_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[tuple[str, str]] = []

    def fake_move(issue_id: str, *, to_state: str, by: str, expect: str | None = None, client=None) -> dict:
        events.append(("move", f"{issue_id}:{to_state}:{by}:{expect}"))
        return {
            "ok": True,
            "issue_id": issue_id,
            "reason": "allowed",
            "by": by,
            "from_state": expect or "unknown",
            "to_state": to_state,
            "updated_state": to_state,
        }

    def fake_followup(*, issue_id: str, stage: str, release_required: bool = False) -> dict:
        events.append(("followup", f"{issue_id}:{stage}:{release_required}"))
        return {
            "stage": "pr",
            "identifier": "GEO-24",
            "url": "https://linear.app/example/GEO-24",
        }

    monkeypatch.setattr(stage.linear_state, "move_issue", fake_move)
    monkeypatch.setattr(stage, "create_followup_for_review", fake_followup)
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
            outcome="approved",
            summary="Approved",
            workspace=workspace,
            validation=["pytest -q tests/test_stage_runner.py"],
            artifact=["SYMPHONY_STAGE_HANDOFF.md", "SYMPHONY_STAGE_PATCH.diff"],
            blocker=[],
            details_file=None,
            next_actor=None,
            release_required=False,
            from_state="In Review",
        )
    )

    assert payload == {
        "ok": True,
        "stage": "feature",
        "to_state": "Done",
        "status": "approved",
        "followup_issue": {
            "stage": "pr",
            "identifier": "GEO-24",
            "url": "https://linear.app/example/GEO-24",
        },
    }
    assert events == [
        ("followup", "GEO-18:feature:False"),
        ("move", "GEO-18:Done:review:In Review"),
    ]


def test_review_finish_feature_approved_fails_closed_when_followup_creation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    move_calls = allow_linear_move(monkeypatch)
    followup_calls = reject_followup_creation(monkeypatch)
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

    with pytest.raises(SystemExit, match="followup creation failed"):
        stage.review_finish(
            Namespace(
                stage="feature",
                issue_id="GEO-18",
                title="Automation",
                outcome="approved",
                summary="Approved",
                workspace=workspace,
                validation=["pytest -q tests/test_stage_runner.py"],
                artifact=["SYMPHONY_STAGE_HANDOFF.md", "SYMPHONY_STAGE_PATCH.diff"],
                blocker=[],
                details_file=None,
                next_actor=None,
                release_required=False,
                from_state="In Review",
            )
        )

    assert followup_calls == [("GEO-18", "feature", False)]
    assert move_calls == []


def test_review_finish_routes_release_required_pr_to_followup_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = allow_linear_move(monkeypatch)
    followup_calls = allow_followup_creation(monkeypatch)
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

    assert payload == {
        "ok": True,
        "stage": "pr",
        "to_state": "Done",
        "status": "approved",
        "followup_issue": {
            "stage": "release",
            "identifier": "GEO-24",
            "url": "https://linear.app/example/GEO-24",
        },
    }
    handoff = json.loads((workspace / "SYMPHONY_HANDOFF.json").read_text(encoding="utf-8"))
    assert handoff["next_actor"] == "followup-release"
    assert handoff["pr"] == {
        "pr_url": "https://example.test/pr/1",
        "merge_status": "",
        "merge_commit": "",
        "branch": "issue/geo-18",
        "commit": "abc123",
    }
    assert followup_calls == [("GEO-18", "pr", True)]
    assert calls == [("GEO-18", "Done", "review", "In Review")]


def test_review_finish_infers_release_required_from_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = allow_linear_move(monkeypatch)
    followup_calls = allow_followup_creation(monkeypatch)
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
            labels="symphony,issue-type:pr,release-required",
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
            release_required=False,
            from_state="In Review",
        )
    )

    assert payload["followup_issue"]["stage"] == "release"
    handoff = json.loads((workspace / "SYMPHONY_HANDOFF.json").read_text(encoding="utf-8"))
    assert handoff["next_actor"] == "followup-release"
    assert handoff["pr"]["branch"] == "issue/geo-18"
    assert followup_calls == [("GEO-18", "pr", True)]
    assert calls == [("GEO-18", "Done", "review", "In Review")]


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
