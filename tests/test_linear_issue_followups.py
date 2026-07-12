import json

import pytest

from scripts import linear_issue


def _issue(labels: list[str]) -> dict:
    return {
        "id": "issue-id",
        "identifier": "GEO-7",
        "title": "Add search_serp MCP tool",
        "description": "Body",
        "url": "https://linear.app/example/GEO-7",
        "state": {"name": "Done"},
        "team": {"id": "team-id"},
        "project": {"id": "project-id", "name": "Yandex.AD"},
        "labels": {"nodes": [{"id": f"id-{idx}", "name": label} for idx, label in enumerate(labels)]},
    }


def _issue_with_identifier(identifier: str, labels: list[str]) -> dict:
    issue = _issue(labels)
    issue["identifier"] = identifier
    issue["url"] = f"https://linear.app/example/{identifier}"
    return issue


def test_classify_issue_type_defaults_to_feature() -> None:
    assert linear_issue.classify_issue_type(["symphony", "search-api"]) == "feature"


def test_classify_issue_type_uses_specific_labels() -> None:
    assert linear_issue.classify_issue_type(["issue-type:pr", "symphony"]) == "pr"
    assert linear_issue.classify_issue_type(["issue-type:release", "symphony"]) == "release"


def test_inherited_followup_labels_replace_issue_type_and_preserve_context() -> None:
    labels = linear_issue.inherited_followup_labels(
        ["symphony", "search-api", "issue-type:feature", "release-required"],
        "pr",
        ["extra"],
    )
    assert labels == [
        "symphony",
        "search-api",
        "release-required",
        "issue-type:pr",
        "generated-followup",
        "extra",
    ]


def test_followup_description_for_pr_contains_pr_contract() -> None:
    body = linear_issue.followup_description(
        "pr",
        _issue(["symphony", "issue-type:feature"]),
        linear_issue.Path("/tmp/symphony/GEO-7"),
    )
    assert "## Execution Profile" in body
    assert "- Issue Class: feature" in body
    assert "- Source workspace: `/tmp/symphony/GEO-7`" in body
    assert "## Symphony Preflight Metadata" in body
    assert "source_issue: GEO-7" in body
    assert "source_workspace: /tmp/symphony/GEO-7" in body
    assert "SYMPHONY_HANDOFF.json" in body
    assert "SYMPHONY_STAGE_PATCH.diff" in body
    assert "do not continue this PR stage" in body
    assert "## PR Validation" in body
    assert "GitHub PR command succeeds." in body
    assert "## Release Validation" in body
    assert "Use `n/a`. Release publication is owned by a separate release follow-up issue." in body


def test_followup_description_for_release_contains_release_contract(tmp_path) -> None:
    workspace = tmp_path / "GEO-8"
    workspace.mkdir()
    (workspace / "SYMPHONY_HANDOFF.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "issue": {"identifier": "GEO-8", "title": "PR issue"},
                "stage": {"type": "pr", "role": "review"},
                "transition": {"from_state": "In Review", "to_state": "Done", "status": "approved"},
                "cycle": {"iteration": 1, "max_iterations": 3},
                "summary": "approved",
                "artifacts": ["SYMPHONY_WORK_RESULT.md", "SYMPHONY_HANDOFF.json", "SYMPHONY_STAGE_HANDOFF.md"],
                "validation": {"passed": ["pytest -q"]},
                "next_actor": "followup-release",
                "blockers": [],
                "pr": {
                    "url": "https://github.com/example/repo/pull/8",
                    "merge_status": "merged",
                    "merge_commit": "def456",
                    "branch": "issue/geo-8-pr-smoke",
                    "commit": "abc123",
                },
            }
        ),
        encoding="utf-8",
    )
    body = linear_issue.followup_description(
        "release",
        _issue_with_identifier("GEO-8", ["symphony", "issue-type:pr", "release-required"]),
        workspace,
    )
    assert "## Execution Profile" in body
    assert "- Issue Class: release" in body
    assert "- Risk: high" in body
    assert "## Symphony Preflight Metadata" in body
    assert "source_issue: GEO-8" in body
    assert "required_pr_merge: yes" in body
    assert "pr_url: https://github.com/example/repo/pull/8" in body
    assert "merge_status: merged" in body
    assert "merge_commit: def456" in body
    assert "SYMPHONY_HANDOFF.json" in body
    assert "SYMPHONY_STAGE_HANDOFF.md" in body
    assert "python scripts/release_followup.py --issue-id {{ issue.identifier }}" in body
    assert "next patch version from `pyproject.toml`" in body
    assert "GitHub Release exists." in body
    assert "The source PR is already merged before release publication starts." in body
    assert "## Release Validation" in body
    assert "python scripts/live_validation.py --suite direct,metrica,wordstat,search" in body
    assert "No new feature work." in body


def test_verify_release_source_metadata_requires_merged_pr(tmp_path) -> None:
    workspace = tmp_path / "GEO-15"
    workspace.mkdir()
    (workspace / "SYMPHONY_HANDOFF.json").write_text(
        json.dumps({"pr": {"url": "https://github.com/example/repo/pull/7", "merge_status": "open"}}),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="missing metadata: pr.merge_status=merged, pr.merge_commit"):
        linear_issue.verify_release_source_metadata(workspace)


def test_verify_release_source_metadata_accepts_merged_pr(tmp_path) -> None:
    workspace = tmp_path / "GEO-15"
    workspace.mkdir()
    (workspace / "SYMPHONY_HANDOFF.json").write_text(
        json.dumps({"pr": {"url": "https://github.com/example/repo/pull/7", "merge_status": "merged", "merge_commit": "def456"}}),
        encoding="utf-8",
    )

    metadata = linear_issue.verify_release_source_metadata(workspace)
    assert metadata["pr_url"] == "https://github.com/example/repo/pull/7"
    assert metadata["merge_status"] == "merged"
    assert metadata["merge_commit"] == "def456"


def test_verify_release_source_metadata_falls_back_to_stage_handoff_markdown(tmp_path) -> None:
    workspace = tmp_path / "GEO-15"
    workspace.mkdir()
    (workspace / "SYMPHONY_STAGE_HANDOFF.md").write_text(
        "\n".join(
            [
                "branch: issue/geo-15",
                "commit: abc123",
                "PR URL: https://github.com/example/repo/pull/7",
                "merge status: merged",
                "merge commit: def456",
            ]
        ),
        encoding="utf-8",
    )

    metadata = linear_issue.verify_release_source_metadata(workspace)
    assert metadata["pr_url"] == "https://github.com/example/repo/pull/7"


def test_source_workspace_path_uses_env_override(monkeypatch) -> None:
    original = linear_issue.DEFAULT_WORKSPACE_ROOT
    monkeypatch.setenv("SYMPHONY_WORKSPACE_ROOT", "/tmp/symphony-workspaces")
    try:
        linear_issue.DEFAULT_WORKSPACE_ROOT = linear_issue.Path("/tmp/symphony-workspaces")
        assert str(linear_issue.source_workspace_path("GEO-99")) == "/tmp/symphony-workspaces/GEO-99"
    finally:
        linear_issue.DEFAULT_WORKSPACE_ROOT = original


def test_candidate_source_workspaces_checks_legacy_root(monkeypatch, tmp_path) -> None:
    current_root = tmp_path / "current"
    canonical_root = tmp_path / "canonical"
    legacy_root = tmp_path / "legacy"
    legacy_workspace = legacy_root / "GEO-99"
    legacy_workspace.mkdir(parents=True)
    monkeypatch.setattr(linear_issue, "DEFAULT_WORKSPACE_ROOT", current_root)
    monkeypatch.setattr(linear_issue, "CANONICAL_WORKSPACE_ROOT", canonical_root)
    monkeypatch.setattr(linear_issue, "LEGACY_WORKSPACE_ROOT", legacy_root)

    candidates = linear_issue.candidate_source_workspaces("GEO-99")

    assert candidates == [legacy_workspace.resolve()]


def test_candidate_source_workspaces_checks_canonical_root_even_when_env_root_differs(monkeypatch, tmp_path) -> None:
    current_root = tmp_path / "current"
    canonical_root = tmp_path / "canonical"
    legacy_root = tmp_path / "legacy"
    canonical_workspace = canonical_root / "GEO-100"
    canonical_workspace.mkdir(parents=True)
    monkeypatch.setattr(linear_issue, "DEFAULT_WORKSPACE_ROOT", current_root)
    monkeypatch.setattr(linear_issue, "CANONICAL_WORKSPACE_ROOT", canonical_root)
    monkeypatch.setattr(linear_issue, "LEGACY_WORKSPACE_ROOT", legacy_root)

    candidates = linear_issue.candidate_source_workspaces("GEO-100")

    assert candidates == [canonical_workspace.resolve()]


def test_candidate_source_workspaces_prefers_handoff_latest_over_older_archives(monkeypatch, tmp_path) -> None:
    root = tmp_path / "workspaces"
    handoff_latest = root / "GEO-101.handoff-latest"
    older = root / "GEO-101.handoff-2026-07-01T120000Z"
    newer = root / "GEO-101.handoff-2026-07-02T120000Z"
    handoff_latest.mkdir(parents=True)
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    monkeypatch.setattr(linear_issue, "DEFAULT_WORKSPACE_ROOT", root)
    monkeypatch.setattr(linear_issue, "CANONICAL_WORKSPACE_ROOT", root)
    monkeypatch.setattr(linear_issue, "LEGACY_WORKSPACE_ROOT", root)

    candidates = linear_issue.candidate_source_workspaces("GEO-101")

    assert candidates[0] == handoff_latest.resolve()
    assert candidates[1:] == [newer.resolve(), older.resolve()]


def test_find_generated_followup_issue_prefers_stage_and_source_identifier(monkeypatch) -> None:
    def fake_graphql(_api_key: str, _query: str, _variables: dict) -> dict:
        return {
            "data": {
                "project": {
                    "issues": {
                        "nodes": [
                            {
                                "id": "1",
                                "identifier": "GEO-13",
                                "title": "PR: GEO-12 Old title",
                                "url": "https://linear.app/example/GEO-13",
                                "labels": {
                                    "nodes": [
                                        {"name": "generated-followup"},
                                        {"name": "issue-type:pr"},
                                        {"name": "symphony"},
                                    ]
                                },
                            },
                            {
                                "id": "2",
                                "identifier": "GEO-14",
                                "title": "PR: GEO-99 Other title",
                                "url": "https://linear.app/example/GEO-14",
                                "labels": {
                                    "nodes": [
                                        {"name": "generated-followup"},
                                        {"name": "issue-type:pr"},
                                    ]
                                },
                            },
                        ]
                    }
                }
            }
        }

    monkeypatch.setattr(linear_issue, "graphql", fake_graphql)
    found = linear_issue.find_generated_followup_issue("token", "project-id", "pr", "GEO-12")
    assert found is not None
    assert found["identifier"] == "GEO-13"


def test_find_generated_followup_issues_returns_matching_pr_and_release(monkeypatch) -> None:
    def fake_graphql(_api_key: str, _query: str, _variables: dict) -> dict:
        return {
            "data": {
                "project": {
                    "issues": {
                        "nodes": [
                            {
                                "id": "1",
                                "identifier": "GEO-13",
                                "title": "PR: GEO-12 Old title",
                                "url": "https://linear.app/example/GEO-13",
                                "state": {"name": "Backlog"},
                                "labels": {
                                    "nodes": [
                                        {"name": "generated-followup"},
                                        {"name": "issue-type:pr"},
                                    ]
                                },
                            },
                            {
                                "id": "2",
                                "identifier": "GEO-14",
                                "title": "Release: GEO-12 Old title",
                                "url": "https://linear.app/example/GEO-14",
                                "state": {"name": "Backlog"},
                                "labels": {
                                    "nodes": [
                                        {"name": "generated-followup"},
                                        {"name": "issue-type:release"},
                                    ]
                                },
                            },
                            {
                                "id": "3",
                                "identifier": "GEO-15",
                                "title": "PR: GEO-99 Other title",
                                "url": "https://linear.app/example/GEO-15",
                                "state": {"name": "Backlog"},
                                "labels": {
                                    "nodes": [
                                        {"name": "generated-followup"},
                                        {"name": "issue-type:pr"},
                                    ]
                                },
                            },
                        ]
                    }
                }
            }
        }

    monkeypatch.setattr(linear_issue, "graphql", fake_graphql)

    found = linear_issue.find_generated_followup_issues("token", "project-id", "GEO-12", ["pr", "release"])
    assert [node["identifier"] for node in found] == ["GEO-13", "GEO-14"]


def test_verify_followup_source_workspace_fails_when_handoff_is_invalid(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "GEO-7"
    workspace.mkdir()
    monkeypatch.setattr(linear_issue, "DEFAULT_WORKSPACE_ROOT", tmp_path)

    def fake_run(*_args, **_kwargs):
        raise linear_issue.subprocess.CalledProcessError(
            1,
            ["python", "scripts/stage_handoff.py"],
            stderr="Missing handoff artifacts in workspace",
        )

    monkeypatch.setattr(linear_issue.subprocess, "run", fake_run)

    with pytest.raises(SystemExit, match="does not satisfy review-verify"):
        linear_issue.verify_followup_source_workspace("pr", _issue(["symphony", "issue-type:feature"]))


def test_verify_followup_source_workspace_uses_review_verify_for_pr(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "GEO-7"
    workspace.mkdir()
    monkeypatch.setattr(linear_issue, "DEFAULT_WORKSPACE_ROOT", tmp_path)
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs.get("cwd")
        return None

    monkeypatch.setattr(linear_issue.subprocess, "run", fake_run)

    resolved = linear_issue.verify_followup_source_workspace(
        "pr",
        _issue_with_identifier("GEO-7", ["symphony", "issue-type:feature"]),
    )

    assert resolved == workspace.resolve()
    assert captured["command"] == [
        linear_issue.sys.executable,
        "scripts/stage_handoff.py",
        "review-verify",
        "--workspace",
        str(workspace.resolve()),
        "--stage",
        "feature",
        "--outcome",
        "approved",
    ]


def test_verify_followup_source_workspace_uses_review_verify_for_release(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "GEO-8"
    workspace.mkdir()
    (workspace / "SYMPHONY_STAGE_HANDOFF.md").write_text(
        "\n".join(
            [
                "branch: issue/geo-8",
                "commit: abc123",
                "PR URL: https://example.test/pr/8",
                "merge status: merged",
                "merge commit: def456",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(linear_issue, "DEFAULT_WORKSPACE_ROOT", tmp_path)
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs.get("cwd")
        return None

    monkeypatch.setattr(linear_issue.subprocess, "run", fake_run)

    resolved = linear_issue.verify_followup_source_workspace(
        "release",
        _issue_with_identifier("GEO-8", ["symphony", "issue-type:pr"]),
    )

    assert resolved == workspace.resolve()
    assert captured["command"] == [
        linear_issue.sys.executable,
        "scripts/stage_handoff.py",
        "review-verify",
        "--workspace",
        str(workspace.resolve()),
        "--stage",
        "pr",
        "--outcome",
        "approved",
    ]


def test_verify_followup_source_workspace_prefers_valid_archived_candidate(monkeypatch, tmp_path) -> None:
    stale = tmp_path / "GEO-12.stale-2026-07-02T0800"
    stale.mkdir()
    archived = tmp_path / "GEO-12.handoff-2026-07-08T180401Z"
    archived.mkdir()
    monkeypatch.setattr(linear_issue, "DEFAULT_WORKSPACE_ROOT", tmp_path)
    seen: list[str] = []

    def fake_run(command, **kwargs):
        workspace = command[command.index("--workspace") + 1]
        seen.append(workspace)
        if workspace == str(stale.resolve()):
            raise linear_issue.subprocess.CalledProcessError(1, command, stderr="missing handoff")
        return None

    monkeypatch.setattr(linear_issue.subprocess, "run", fake_run)

    resolved = linear_issue.verify_followup_source_workspace(
        "pr",
        _issue_with_identifier("GEO-12", ["symphony", "issue-type:feature"]),
    )

    assert resolved == archived.resolve()
    assert seen == [str(stale.resolve()), str(archived.resolve())]


def test_build_followup_input_uses_workspace_override(monkeypatch, tmp_path) -> None:
    workspace = tmp_path / "GEO-12"
    workspace.mkdir()
    (workspace / "SYMPHONY_HANDOFF.json").write_text(
        json.dumps(
            {
                "pr": {
                    "url": "https://github.com/example/repo/pull/12",
                    "merge_status": "merged",
                    "merge_commit": "def456",
                }
            }
        ),
        encoding="utf-8",
    )
    seen: list[Path] = []

    monkeypatch.setattr(
        linear_issue,
        "validate_followup_source_workspace",
        lambda _stage, _source_issue, candidate: seen.append(candidate.resolve()) or candidate.resolve(),
    )
    monkeypatch.setattr(
        linear_issue,
        "verify_followup_source_workspace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("override path should bypass candidate lookup")),
    )
    monkeypatch.setattr(linear_issue, "resolve_state_id", lambda *_args, **_kwargs: "state-id")
    monkeypatch.setattr(linear_issue, "resolve_label_ids", lambda *_args, **_kwargs: ["label-id"])

    payload = linear_issue.build_followup_input(
        "token",
        _issue_with_identifier("GEO-12", ["symphony", "issue-type:pr", "release-required"]),
        "release",
        "Todo",
        None,
        [],
        True,
        source_workspace_override=workspace,
    )

    assert seen == [workspace.resolve()]
    assert payload["stateId"] == "state-id"
    assert payload["labelIds"] == ["label-id"]


def test_cleanup_generated_followup_issues_deletes_matches(monkeypatch) -> None:
    source_issue = {
        "identifier": "GEO-12",
        "project": {"id": "project-id"},
    }
    matches = [
        {"id": "1", "identifier": "GEO-13", "title": "PR: GEO-12 Example"},
        {"id": "2", "identifier": "GEO-14", "title": "Release: GEO-12 Example"},
    ]
    deleted: list[tuple[str, bool]] = []

    monkeypatch.setattr(linear_issue, "find_generated_followup_issues", lambda *_args, **_kwargs: matches)
    monkeypatch.setattr(
        linear_issue,
        "delete_issue",
        lambda _api_key, issue_id, permanently_delete=False: deleted.append((issue_id, permanently_delete)) or True,
    )

    result = linear_issue.cleanup_generated_followup_issues("token", source_issue, ["pr", "release"])

    assert result == matches
    assert deleted == [("1", False), ("2", False)]
