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
    assert "SYMPHONY_HANDOFF.json" in body
    assert "SYMPHONY_STAGE_PATCH.diff" in body
    assert "do not continue this PR stage" in body
    assert "## PR Validation" in body
    assert "GitHub PR command succeeds." in body
    assert "## Release Validation" in body
    assert "Use `n/a`. Release publication is owned by a separate release follow-up issue." in body


def test_followup_description_for_release_contains_release_contract() -> None:
    body = linear_issue.followup_description(
        "release",
        _issue(["symphony", "issue-type:pr", "release-required"]),
        linear_issue.Path("/tmp/symphony/GEO-8"),
    )
    assert "## Execution Profile" in body
    assert "- Issue Class: release" in body
    assert "- Risk: high" in body
    assert "SYMPHONY_HANDOFF.json" in body
    assert "SYMPHONY_STAGE_HANDOFF.md" in body
    assert "GitHub Release exists." in body
    assert "## Release Validation" in body
    assert "python scripts/live_validation.py --suite direct,metrica,wordstat,search" in body
    assert "No new feature work." in body


def test_source_workspace_path_uses_env_override(monkeypatch) -> None:
    original = linear_issue.DEFAULT_WORKSPACE_ROOT
    monkeypatch.setenv("SYMPHONY_WORKSPACE_ROOT", "/tmp/symphony-workspaces")
    try:
        linear_issue.DEFAULT_WORKSPACE_ROOT = linear_issue.Path("/tmp/symphony-workspaces")
        assert str(linear_issue.source_workspace_path("GEO-99")) == "/tmp/symphony-workspaces/GEO-99"
    finally:
        linear_issue.DEFAULT_WORKSPACE_ROOT = original


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

    with pytest.raises(SystemExit, match="does not satisfy feature-verify"):
        linear_issue.verify_followup_source_workspace("pr", _issue(["symphony", "issue-type:feature"]))
