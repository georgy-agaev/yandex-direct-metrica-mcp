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

    monkeypatch.setenv("GHCR_READ_TOKEN", "token")
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
    assert payload["ghcr_auth"] == "env:GHCR_READ_TOKEN"


def test_preflight_repairs_reopened_source_issue(monkeypatch) -> None:
    issue = _issue(
        "GEO-33",
        ["symphony", "issue-type:pr", "release-required", "generated-followup"],
        linear_issue.followup_description(
            "pr",
            _issue("GEO-32", ["symphony", "issue-type:feature", "release-required"], "Body"),
            Path("/tmp/symphony/GEO-32"),
        ),
    )
    source_issue = _issue("GEO-32", ["symphony", "issue-type:feature", "release-required"], "Body")
    source_issue["state"] = {"name": "In Review"}
    move_calls: list[tuple[str, str, str, str | None]] = []

    monkeypatch.setattr(linear_issue, "get_issue", lambda _api_key, issue_id: source_issue if issue_id == "GEO-32" else issue)
    monkeypatch.setattr(
        followup_preflight.linear_state,
        "move_issue",
        lambda issue_id, *, to_state, by, expect=None, client=None: move_calls.append(
            (issue_id, to_state, by, expect)
        )
        or {
            "ok": True,
            "issue_id": issue_id,
            "reason": "allowed",
            "by": by,
            "from_state": expect or "unknown",
            "to_state": to_state,
            "updated_state": to_state,
        },
    )
    monkeypatch.setattr(
        linear_issue,
        "verify_followup_source_workspace",
        lambda stage, source: Path(f"/resolved/{stage}/{source['identifier']}"),
    )

    payload = followup_preflight.preflight(issue, "pr", api_key="token")

    assert payload["source_issue_state"] == "Done"
    assert payload["source_issue_repair"] == {
        "status": "repaired",
        "from_state": "In Review",
        "state": "Done",
    }
    assert move_calls == [("GEO-32", "Done", "followup", "In Review")]


def test_preflight_blocks_when_source_issue_is_not_repairable(monkeypatch) -> None:
    issue = _issue(
        "GEO-33",
        ["symphony", "issue-type:pr", "release-required", "generated-followup"],
        linear_issue.followup_description(
            "pr",
            _issue("GEO-32", ["symphony", "issue-type:feature", "release-required"], "Body"),
            Path("/tmp/symphony/GEO-32"),
        ),
    )
    source_issue = _issue("GEO-32", ["symphony", "issue-type:feature", "release-required"], "Body")
    source_issue["state"] = {"name": "In Progress"}

    monkeypatch.setattr(linear_issue, "get_issue", lambda _api_key, issue_id: source_issue if issue_id == "GEO-32" else issue)
    monkeypatch.setattr(
        linear_issue,
        "verify_followup_source_workspace",
        lambda stage, source: Path(f"/resolved/{stage}/{source['identifier']}"),
    )

    with pytest.raises(SystemExit, match="must be `Done` before follow-up preflight"):
        followup_preflight.preflight(issue, "pr", api_key="token")


def test_preflight_release_requires_ghcr_read_token(monkeypatch, tmp_path: Path) -> None:
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

    monkeypatch.delenv("GHCR_READ_TOKEN", raising=False)
    monkeypatch.setattr(linear_issue, "verify_followup_source_workspace", lambda *_args, **_kwargs: source_workspace)

    with pytest.raises(SystemExit, match="GHCR_READ_TOKEN"):
        followup_preflight.preflight(issue, "release")


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
    monkeypatch.setenv("GHCR_READ_TOKEN", "token")
    monkeypatch.setattr(followup_preflight, "load_issue", lambda _api_key, _issue_id: issue)
    monkeypatch.setattr(
        linear_issue,
        "get_issue",
        lambda _api_key, issue_id: _issue(
            "GEO-15",
            ["symphony", "issue-type:pr", "release-required"],
            "Body",
        )
        | {"state": {"name": "Done"}}
        if issue_id == "GEO-15"
        else issue,
    )
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
