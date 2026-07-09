from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import followup_preflight, linear_issue


def _issue(identifier: str, labels: list[str], description: str) -> dict:
    return {
        "id": f"id-{identifier}",
        "identifier": identifier,
        "title": f"title {identifier}",
        "description": description,
        "url": f"https://linear.app/example/{identifier}",
        "state": {"name": "Todo"},
        "team": {"id": "team-id"},
        "project": {"id": "project-id", "name": "Yandex.AD"},
        "labels": {"nodes": [{"id": f"label-{idx}", "name": label} for idx, label in enumerate(labels)]},
    }


def test_parse_followup_metadata_from_structured_block() -> None:
    description = """
# PR follow-up

## Symphony Preflight Metadata
```text
stage: pr
source_issue: GEO-12
source_stage: feature
source_workspace: /tmp/symphony/GEO-12
required_review_outcome: approved
release_required: yes
```
""".strip()

    metadata = linear_issue.parse_followup_metadata(description)
    assert metadata == {
        "stage": "pr",
        "source_issue": "GEO-12",
        "source_stage": "feature",
        "source_workspace": "/tmp/symphony/GEO-12",
        "required_review_outcome": "approved",
        "release_required": "yes",
    }


def test_preflight_pr_uses_source_issue_metadata(monkeypatch) -> None:
    issue = _issue(
        "GEO-15",
        ["symphony", "issue-type:pr", "release-required"],
        linear_issue.followup_description(
            "pr",
            _issue("GEO-12", ["symphony", "issue-type:feature"], "Body"),
            Path("/tmp/symphony/GEO-12"),
        ),
    )

    monkeypatch.setattr(
        linear_issue,
        "verify_followup_source_workspace",
        lambda stage, source_issue: Path(f"/resolved/{stage}/{source_issue['identifier']}"),
    )

    payload = followup_preflight.preflight(issue, "pr")
    assert payload["ok"] is True
    assert payload["issue"] == "GEO-15"
    assert payload["source_issue"] == "GEO-12"
    assert payload["declared_source_workspace"] == "/tmp/symphony/GEO-12"
    assert payload["resolved_source_workspace"] == "/resolved/pr/GEO-12"


def test_preflight_release_requires_live_merged_pr(monkeypatch, tmp_path: Path) -> None:
    source_workspace = tmp_path / "GEO-15"
    source_workspace.mkdir()
    (source_workspace / "SYMPHONY_STAGE_HANDOFF.md").write_text(
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
    issue = _issue(
        "GEO-16",
        ["symphony", "issue-type:release", "release-required"],
        linear_issue.followup_description(
            "release",
            _issue("GEO-15", ["symphony", "issue-type:pr", "release-required"], "Body"),
            source_workspace,
        ),
    )

    monkeypatch.setattr(linear_issue, "verify_followup_source_workspace", lambda *_args, **_kwargs: source_workspace)
    monkeypatch.setattr(
        followup_preflight,
        "github_pr_state",
        lambda _url: {
            "state": "MERGED",
            "mergedAt": "2026-07-09T00:00:00Z",
            "mergeCommit": {"oid": "def456"},
            "url": "https://github.com/example/repo/pull/7",
        },
    )

    payload = followup_preflight.preflight(issue, "release")
    assert payload["ok"] is True
    assert payload["source_issue"] == "GEO-15"
    assert payload["pr_url"] == "https://github.com/example/repo/pull/7"
    assert payload["github_pr_state"] == "MERGED"


def test_main_returns_blocked_json_for_unmerged_release(monkeypatch, capsys, tmp_path: Path) -> None:
    source_workspace = tmp_path / "GEO-15"
    source_workspace.mkdir()
    (source_workspace / "SYMPHONY_STAGE_HANDOFF.md").write_text(
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
    issue = _issue(
        "GEO-16",
        ["symphony", "issue-type:release", "release-required"],
        linear_issue.followup_description(
            "release",
            _issue("GEO-15", ["symphony", "issue-type:pr", "release-required"], "Body"),
            source_workspace,
        ),
    )

    monkeypatch.setenv("LINEAR_API_KEY", "token")
    monkeypatch.setattr(followup_preflight, "load_issue", lambda _api_key, _issue_id: issue)
    monkeypatch.setattr(linear_issue, "verify_followup_source_workspace", lambda *_args, **_kwargs: source_workspace)
    monkeypatch.setattr(
        followup_preflight,
        "github_pr_state",
        lambda _url: {"state": "OPEN", "mergedAt": None, "url": "https://github.com/example/repo/pull/7"},
    )
    monkeypatch.setattr(followup_preflight, "parse_args", lambda: type("Args", (), {"issue_id": "GEO-16", "stage": "release"})())

    exit_code = followup_preflight.main()
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert output["ok"] is False
    assert "requires a merged PR" in output["blocker"]
