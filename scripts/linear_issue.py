"""Create Linear issues from local Markdown drafts.

This script is intentionally small and dependency-free. It reads Linear auth
from LINEAR_API_KEY and project/team defaults from a local JSON config.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = Path("/Users/georgyagaev/Projects/Symphony_yaad/linear.yandexad.json")
DEFAULT_SYMPHONY_ROOT = Path(
    os.environ.get("SYMPHONY_ROOT", str(Path.home() / "Projects" / "Symphony_yaad"))
).expanduser()
DEFAULT_WORKSPACE_ROOT = Path(
    os.environ.get("SYMPHONY_WORKSPACE_ROOT", str(DEFAULT_SYMPHONY_ROOT / "workspaces"))
).expanduser()
LINEAR_ENDPOINT = "https://api.linear.app/graphql"
ISSUE_TYPE_PREFIX = "issue-type:"
FOLLOWUP_LABEL = "generated-followup"
RELEASE_REQUIRED_LABEL = "release-required"


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Config not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON config {path}: {exc}") from None


def source_workspace_path(issue_identifier: str) -> Path:
    return DEFAULT_WORKSPACE_ROOT / issue_identifier


def read_markdown(path: Path | None, text: str | None) -> str:
    if path and text:
        raise SystemExit("Use either --from or --body, not both")
    if path:
        return path.read_text(encoding="utf-8").strip()
    if text:
        return text.strip()
    data = sys.stdin.read().strip()
    if data:
        return data
    raise SystemExit("Provide issue body with --from, --body, or stdin")


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def graphql(api_key: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        LINEAR_ENDPOINT,
        data=payload,
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Linear API HTTP {exc.code}: {details}") from None
    except urllib.error.URLError as exc:
        raise SystemExit(f"Linear API request failed: {exc}") from None

    data = json.loads(body)
    if data.get("errors"):
        raise SystemExit(json.dumps(data["errors"], indent=2, ensure_ascii=False))
    return data


def team_labels(api_key: str, team_id: str) -> dict[str, str]:
    query = """
    query($teamId: String!) {
      team(id: $teamId) {
        labels(first: 100) {
          nodes { id name }
        }
      }
    }
    """
    data = graphql(api_key, query, {"teamId": team_id})
    nodes = data["data"]["team"]["labels"]["nodes"]
    return {node["name"].strip().lower(): node["id"] for node in nodes}


def team_states(api_key: str, team_id: str) -> dict[str, str]:
    query = """
    query($teamId: String!) {
      team(id: $teamId) {
        states(first: 100) {
          nodes { id name }
        }
      }
    }
    """
    data = graphql(api_key, query, {"teamId": team_id})
    nodes = data["data"]["team"]["states"]["nodes"]
    return {node["name"].strip().lower(): node["id"] for node in nodes}


def create_label(api_key: str, team_id: str, name: str) -> str:
    query = """
    mutation($teamId: String!, $name: String!) {
      issueLabelCreate(input: {teamId: $teamId, name: $name}) {
        success
        issueLabel { id name }
      }
    }
    """
    data = graphql(api_key, query, {"teamId": team_id, "name": name})
    return data["data"]["issueLabelCreate"]["issueLabel"]["id"]


def resolve_label_ids(api_key: str, team_id: str, labels: list[str], create_missing: bool) -> list[str]:
    existing = team_labels(api_key, team_id)
    label_ids: list[str] = []
    for label in labels:
        key = label.strip().lower()
        if key in existing:
            label_ids.append(existing[key])
            continue
        if not create_missing:
            raise SystemExit(f"Linear label not found: {label}")
        label_id = create_label(api_key, team_id, label)
        existing[key] = label_id
        label_ids.append(label_id)
    return label_ids


def resolve_state_id(api_key: str, team_id: str, state: str) -> str:
    states = team_states(api_key, team_id)
    key = state.strip().lower()
    if key not in states:
        names = ", ".join(sorted(states))
        raise SystemExit(f"Linear state not found: {state}. Available: {names}")
    return states[key]


def build_input(args: argparse.Namespace, config: dict[str, Any], api_key: str | None) -> dict[str, Any]:
    team_id = args.team_id or config.get("teamId")
    project_id = args.project_id or config.get("projectId")
    if not team_id:
        raise SystemExit("Missing teamId in config or --team-id")
    if not project_id:
        raise SystemExit("Missing projectId in config or --project-id")

    body = read_markdown(args.body_file, args.body)
    labels = list(dict.fromkeys([*config.get("defaultLabels", []), *parse_csv(args.labels)]))
    state = args.state or config.get("defaultState") or "Backlog"

    result: dict[str, Any] = {
        "teamId": team_id,
        "projectId": project_id,
        "title": args.title,
        "description": body,
    }
    if api_key:
        result["stateId"] = resolve_state_id(api_key, team_id, state)
        result["labelIds"] = resolve_label_ids(api_key, team_id, labels, args.create_missing_labels)
    else:
        result["stateName"] = state
        result["labels"] = labels
    return result


def create_issue(api_key: str, input_payload: dict[str, Any]) -> dict[str, Any]:
    query = """
    mutation($input: IssueCreateInput!) {
      issueCreate(input: $input) {
        success
        issue {
          id
          identifier
          title
          url
          state { name }
          labels { nodes { name } }
        }
      }
    }
    """
    data = graphql(api_key, query, {"input": input_payload})
    return data["data"]["issueCreate"]["issue"]


def update_issue(api_key: str, issue_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
    query = """
    mutation($id: String!, $input: IssueUpdateInput!) {
      issueUpdate(id: $id, input: $input) {
        success
        issue {
          id
          identifier
          title
          url
          state { name }
          labels { nodes { name } }
        }
      }
    }
    """
    data = graphql(api_key, query, {"id": issue_id, "input": input_payload})
    return data["data"]["issueUpdate"]["issue"]


def update_issue_state(api_key: str, issue_id: str, state_id: str) -> dict[str, Any]:
    query = """
    mutation($id: String!, $input: IssueUpdateInput!) {
      issueUpdate(id: $id, input: $input) {
        success
        issue {
          id
          identifier
          title
          url
          state { name }
        }
      }
    }
    """
    data = graphql(api_key, query, {"id": issue_id, "input": {"stateId": state_id}})
    return data["data"]["issueUpdate"]["issue"]


def comment_issue(api_key: str, issue_id: str, body: str) -> dict[str, Any]:
    query = """
    mutation($issueId: String!, $body: String!) {
      commentCreate(input: {issueId: $issueId, body: $body}) {
        success
        comment {
          id
          body
          issue { identifier }
        }
      }
    }
    """
    data = graphql(api_key, query, {"issueId": issue_id, "body": body})
    return data["data"]["commentCreate"]["comment"]


def get_issue(api_key: str, issue_id: str) -> dict[str, Any]:
    query = """
    query($id: String!) {
      issue(id: $id) {
        id
        identifier
        title
        description
        url
        state { name }
        team { id }
        project { id name }
        labels(first: 100) {
          nodes { id name }
        }
      }
    }
    """
    data = graphql(api_key, query, {"id": issue_id})
    issue = data["data"]["issue"]
    if not issue:
        raise SystemExit(f"Linear issue not found: {issue_id}")
    return issue


def update_issue_labels(api_key: str, issue_id: str, label_ids: list[str]) -> dict[str, Any]:
    query = """
    mutation($id: String!, $input: IssueUpdateInput!) {
      issueUpdate(id: $id, input: $input) {
        success
        issue {
          id
          identifier
          title
          url
          labels { nodes { name } }
        }
      }
    }
    """
    data = graphql(api_key, query, {"id": issue_id, "input": {"labelIds": label_ids}})
    return data["data"]["issueUpdate"]["issue"]


def find_project_issue_by_title(api_key: str, project_id: str, title: str) -> dict[str, Any] | None:
    query = """
    query($projectId: String!) {
      project(id: $projectId) {
        issues(first: 250) {
          nodes {
            id
            identifier
            title
            url
            labels(first: 100) {
              nodes { name }
            }
          }
        }
      }
    }
    """
    data = graphql(api_key, query, {"projectId": project_id})
    nodes = data["data"]["project"]["issues"]["nodes"]
    for node in nodes:
        if node["title"].strip() == title.strip():
            return node
    return None


def issue_label_names(issue: dict[str, Any]) -> list[str]:
    return [node["name"] for node in issue["labels"]["nodes"]]


def classify_issue_type(label_names: list[str]) -> str:
    lowered = {label.strip().lower() for label in label_names}
    if f"{ISSUE_TYPE_PREFIX}release" in lowered:
        return "release"
    if f"{ISSUE_TYPE_PREFIX}pr" in lowered:
        return "pr"
    return "feature"


def inherited_followup_labels(label_names: list[str], stage: str, extra_labels: list[str]) -> list[str]:
    kept: list[str] = []
    for label in label_names:
        lowered = label.strip().lower()
        if lowered.startswith(ISSUE_TYPE_PREFIX):
            continue
        if lowered == FOLLOWUP_LABEL:
            continue
        kept.append(label)
    merged = [*kept, f"{ISSUE_TYPE_PREFIX}{stage}", FOLLOWUP_LABEL, *extra_labels]
    deduped: list[str] = []
    seen: set[str] = set()
    for label in merged:
        key = label.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(label)
    return deduped


def followup_title(stage: str, source_issue: dict[str, Any], explicit_title: str | None) -> str:
    if explicit_title:
        return explicit_title
    prefix = "PR" if stage == "pr" else "Release"
    return f"{prefix}: {source_issue['identifier']} {source_issue['title']}"


def followup_description(stage: str, source_issue: dict[str, Any]) -> str:
    source_workspace = str(source_workspace_path(source_issue["identifier"]))
    source_type = classify_issue_type(issue_label_names(source_issue))
    source_label_list = ", ".join(issue_label_names(source_issue)) or "none"
    common = [
        f"# {stage.upper()} follow-up for {source_issue['identifier']}",
        "",
        "## Execution Profile",
        f"- Issue Class: {'release' if stage == 'release' else source_type}",
        f"- Risk: {'high' if stage == 'release' else 'medium'}",
        "",
        "## Source Issue",
        f"- Identifier: {source_issue['identifier']}",
        f"- Title: {source_issue['title']}",
        f"- URL: {source_issue['url']}",
        f"- Source type: {source_type}",
        f"- Source labels: {source_label_list}",
        f"- Source workspace: `{source_workspace}`",
        "",
        "## Required Handoff Artifacts",
        "- `SYMPHONY_WORK_RESULT.md` from the source workspace is mandatory.",
        "- `SYMPHONY_STAGE_HANDOFF.md` from the source workspace is mandatory.",
        "",
        "## Boundary",
        "- This follow-up issue owns only this stage.",
        "- Do not widen scope beyond the source issue contract.",
        "- Read the source issue body, comments, and generated artifacts before starting.",
        "",
    ]
    if stage == "pr":
        common.extend(
            [
                "## Goal",
                "Publish the already-reviewed change as a branch and GitHub PR.",
                "",
                "## Scope",
                "- Read and follow the source-stage handoff before making any git changes.",
                "- Apply the approved source-stage patch from the source workspace into this fresh clone.",
                "- Re-run non-live gates.",
                "- Prepare deterministic PR metadata.",
                "- Commit the approved change.",
                "- Push the branch.",
                "- Create or update the GitHub PR.",
                "- Comment the PR URL back to Linear.",
                "",
                "## Non-goals",
                "- No version tag.",
                "- No GitHub Release.",
                "- No Docker publish.",
                "",
                "## Acceptance Criteria",
                "- The PR-stage workspace reproduces the approved feature diff from the source workspace.",
                "- Branch exists on GitHub.",
                "- PR exists or was updated.",
                "- Linear contains the PR URL.",
                "",
                "## Feature Validation",
                "Use `n/a`. Feature validation was completed in the source issue review.",
                "",
                "## PR Validation",
                "- `python -m compileall -q src/mcp_yandex_ad`",
                "- `pytest -q`",
                "- `python scripts/agent_lint.py`",
                "- GitHub PR command succeeds.",
                "",
                "## Source Handoff Requirements",
                f"- Preferred path: read `{source_workspace}/SYMPHONY_STAGE_HANDOFF.md` before applying the diff.",
                f"- Preferred path: apply `{source_workspace}/SYMPHONY_STAGE_PATCH.diff` into this workspace before rerunning validation.",
                f"- Legacy fallback only when the source issue predates the handoff-artifact contract: inspect `{source_workspace}` directly, reconstruct the approved diff from that workspace, and document the recovery in this stage's `SYMPHONY_WORK_RESULT.md`.",
                "- If neither the handoff artifacts nor a clear source-workspace diff are available, stop and move the issue to `Backlog` rather than inventing a new diff.",
                "",
                "## Release Validation",
                "Use `n/a`. Release publication is owned by a separate release follow-up issue.",
            ]
        )
    else:
        common.extend(
            [
                "## Goal",
                "Publish a versioned release and refresh local Docker aliases after successful publication.",
                "",
                "## Scope",
                "- Read and follow the source-stage handoff before changing release metadata.",
                "- Run full local gates.",
                "- Run bounded live validation.",
                "- Finalize version and release notes.",
                "- Push release commit if needed.",
                "- Create public and gated pro tags.",
                "- Create the GitHub Release.",
                "- Verify Docker publication workflows.",
                "- Refresh local Docker `latest` aliases from the published tag.",
                "",
                "## Non-goals",
                "- No new feature work.",
                "- No client-repo edits.",
                "",
                "## Acceptance Criteria",
                "- The release stage uses the approved PR-stage branch/commit metadata from the source workspace.",
                "- Release tag exists.",
                "- GitHub Release exists.",
                "- Docker publish workflows completed.",
                "- Local Docker aliases refreshed.",
                "",
                "## Feature Validation",
                "Use `n/a`. Feature validation was completed in the source issue review.",
                "",
                "## PR Validation",
                "Use `n/a`. PR publication was completed in the source PR follow-up issue.",
                "",
                "## Release Validation",
                "- `python -m compileall -q src/mcp_yandex_ad`",
                "- `pytest -q`",
                "- `python scripts/agent_lint.py`",
                "- `python scripts/live_validation.py --suite direct,metrica,wordstat,search`",
                "- `python scripts/release_guard.py --version X.Y.Z --require-release-notes`",
                "",
                "## Source Handoff Requirements",
                f"- Preferred path: read `{source_workspace}/SYMPHONY_STAGE_HANDOFF.md` for the approved branch, commit, PR URL, and release notes context.",
                f"- Legacy fallback only when the source PR issue predates the handoff-artifact contract: inspect `{source_workspace}` directly and recover the approved branch/commit/PR metadata from its git state plus `SYMPHONY_WORK_RESULT.md`.",
                "- If the PR-stage handoff or recoverable source metadata does not clearly identify the publishable branch/commit, stop and move the issue to `Backlog`.",
            ]
        )
    return "\n".join(common).strip()


def build_followup_input(
    api_key: str,
    source_issue: dict[str, Any],
    stage: str,
    state: str,
    explicit_title: str | None,
    extra_labels: list[str],
    create_missing_labels: bool,
) -> dict[str, Any]:
    team_id = source_issue["team"]["id"]
    project = source_issue.get("project") or {}
    project_id = project.get("id")
    if not project_id:
        raise SystemExit(f"Source issue {source_issue['identifier']} has no project")
    label_names = inherited_followup_labels(issue_label_names(source_issue), stage, extra_labels)
    return {
        "teamId": team_id,
        "projectId": project_id,
        "title": followup_title(stage, source_issue, explicit_title),
        "description": followup_description(stage, source_issue),
        "stateId": resolve_state_id(api_key, team_id, state),
        "labelIds": resolve_label_ids(api_key, team_id, label_names, create_missing_labels),
    }


def comment_for_followup(stage: str, source_issue: dict[str, Any], created_issue: dict[str, Any]) -> str:
    stage_name = "PR publication" if stage == "pr" else "release publication"
    return (
        f"{stage_name.capitalize()} follow-up linked: "
        f"`{created_issue['identifier']}` {created_issue['url']} "
        f"for source `{source_issue['identifier']}`."
    )


def render_preview(input_payload: dict[str, Any]) -> str:
    visible = dict(input_payload)
    description = visible.get("description", "")
    if len(description) > 1_200:
        visible["description"] = description[:1_200] + "\n\n[truncated preview]"
    return json.dumps(visible, indent=2, ensure_ascii=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "preview",
            "create",
            "update",
            "state",
            "comment",
            "labels",
            "followup-pr",
            "followup-release",
        ],
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--from", dest="body_file", type=Path)
    parser.add_argument("--body")
    parser.add_argument("--title")
    parser.add_argument("--issue-id", help="Linear issue UUID or shorthand identifier, e.g. GEO-7")
    parser.add_argument("--labels", help="Comma-separated labels to add")
    parser.add_argument("--state", help="Linear state name; defaults to config defaultState or Backlog")
    parser.add_argument("--team-id")
    parser.add_argument("--project-id")
    parser.add_argument(
        "--create-missing-labels",
        action="store_true",
        help="Create missing team-level issue labels before creating the issue",
    )
    args = parser.parse_args()
    if args.command in {"preview", "create", "update"} and not args.title:
        parser.error("--title is required for preview/create/update")
    if args.command in {"state", "comment", "followup-pr", "followup-release"} and not args.issue_id:
        parser.error("--issue-id is required for state/comment")
    if args.command == "comment" and not (args.body_file or args.body):
        parser.error("--from or --body is required for comment")
    if args.command == "state" and not args.state:
        parser.error("--state is required for state")
    if args.command == "labels" and not args.labels:
        parser.error("--labels is required for labels")
    return args


def main() -> int:
    args = parse_args()
    config = load_json(args.config)

    api_key = os.environ.get("LINEAR_API_KEY")
    if args.command in {"create", "update", "state", "comment", "labels", "followup-pr", "followup-release"} and not api_key:
        raise SystemExit(
            "LINEAR_API_KEY is required for create/update/state/comment/labels/followup-pr/followup-release"
        )

    if args.command == "state":
        team_id = args.team_id or config.get("teamId")
        if not team_id:
            raise SystemExit("Missing teamId in config or --team-id")
        state_id = resolve_state_id(api_key or "", team_id, args.state)
        issue = update_issue_state(api_key or "", args.issue_id or "", state_id)
        print(f"{issue['identifier']} {issue['state']['name']} {issue['url']}")
        return 0

    if args.command == "comment":
        body = read_markdown(args.body_file, args.body)
        comment = comment_issue(api_key or "", args.issue_id or "", body)
        print(f"{comment['issue']['identifier']} {comment['id']}")
        return 0

    if args.command == "labels":
        issue = get_issue(api_key or "", args.issue_id or "")
        team_id = issue["team"]["id"]
        current_ids = [node["id"] for node in issue["labels"]["nodes"]]
        wanted_ids = resolve_label_ids(
            api_key or "",
            team_id,
            parse_csv(args.labels),
            args.create_missing_labels,
        )
        merged_ids = sorted(dict.fromkeys([*current_ids, *wanted_ids]))
        updated = update_issue_labels(api_key or "", args.issue_id or "", merged_ids)
        label_names = ",".join(node["name"] for node in updated["labels"]["nodes"])
        print(f"{updated['identifier']} {label_names}")
        return 0

    if args.command in {"followup-pr", "followup-release"}:
        stage = "pr" if args.command == "followup-pr" else "release"
        source_issue = get_issue(api_key or "", args.issue_id or "")
        if stage == "release" and RELEASE_REQUIRED_LABEL not in {
            label.strip().lower() for label in issue_label_names(source_issue)
        }:
            raise SystemExit(
                f"Source issue {source_issue['identifier']} is not marked `{RELEASE_REQUIRED_LABEL}`"
            )
        followup_state = args.state or "Todo"
        input_payload = build_followup_input(
            api_key or "",
            source_issue,
            stage,
            followup_state,
            args.title,
            parse_csv(args.labels),
            args.create_missing_labels,
        )
        existing = find_project_issue_by_title(api_key or "", input_payload["projectId"], input_payload["title"])
        if existing:
            issue = update_issue(
                api_key or "",
                existing["id"],
                {
                    "stateId": input_payload["stateId"],
                    "labelIds": input_payload["labelIds"],
                },
            )
        else:
            issue = create_issue(api_key or "", input_payload)
        comment_issue(api_key or "", source_issue["id"], comment_for_followup(stage, source_issue, issue))
        print(f"{issue['identifier']} {issue['url']}")
        return 0

    input_payload = build_input(args, config, api_key if args.command in {"create", "update"} else None)
    if args.command == "preview":
        print(render_preview(input_payload))
        return 0

    if args.command == "update":
        if not args.issue_id:
            raise SystemExit("--issue-id is required for update")
        update_payload = {
            "title": input_payload["title"],
            "description": input_payload["description"],
        }
        issue = update_issue(api_key or "", args.issue_id, update_payload)
        print(f"{issue['identifier']} {issue['url']}")
        return 0

    issue = create_issue(api_key or "", input_payload)
    print(f"{issue['identifier']} {issue['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
