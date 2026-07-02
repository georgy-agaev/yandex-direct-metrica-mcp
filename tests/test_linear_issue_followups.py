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
    body = linear_issue.followup_description("pr", _issue(["symphony", "issue-type:feature"]))
    assert "## Execution Profile" in body
    assert "- Issue Class: feature" in body
    assert "- Source workspace: `/Users/georgyagaev/Projects/Symphony_yaad/workspaces/GEO-7`" in body
    assert "SYMPHONY_STAGE_PATCH.diff" in body
    assert "## PR Validation" in body
    assert "GitHub PR command succeeds." in body
    assert "## Release Validation" in body
    assert "Use `n/a`. Release publication is owned by a separate release follow-up issue." in body


def test_followup_description_for_release_contains_release_contract() -> None:
    body = linear_issue.followup_description(
        "release",
        _issue(["symphony", "issue-type:pr", "release-required"]),
    )
    assert "## Execution Profile" in body
    assert "- Issue Class: release" in body
    assert "- Risk: high" in body
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
