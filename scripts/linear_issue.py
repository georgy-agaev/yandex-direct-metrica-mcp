"""Create Linear issues from local Markdown drafts.

This script is intentionally small and dependency-free. It reads Linear auth
from LINEAR_API_KEY and project/team defaults from a local JSON config.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = Path("/Users/georgyagaev/Projects/Symphony_yaad/linear.yandexad.json")
DEFAULT_SYMPHONY_ROOT = Path(
    os.environ.get("SYMPHONY_ROOT", str(Path.home() / "Projects" / "Symphony_yaad"))
).expanduser()
CANONICAL_WORKSPACE_ROOT = Path("/private/tmp/symphony_yandexad_workspaces")
LEGACY_WORKSPACE_ROOT = DEFAULT_SYMPHONY_ROOT / "workspaces"
DEFAULT_WORKSPACE_ROOT = Path(
    os.environ.get("SYMPHONY_WORKSPACE_ROOT", str(CANONICAL_WORKSPACE_ROOT))
).expanduser()
LINEAR_ENDPOINT = "https://api.linear.app/graphql"
ISSUE_TYPE_PREFIX = "issue-type:"
FOLLOWUP_LABEL = "generated-followup"
RELEASE_REQUIRED_LABEL = "release-required"
FOLLOWUP_METADATA_HEADER = "## Symphony Preflight Metadata"


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Config not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON config {path}: {exc}") from None


def source_workspace_path(issue_identifier: str) -> Path:
    return DEFAULT_WORKSPACE_ROOT / issue_identifier


def workspace_roots_for_lookup() -> list[Path]:
    roots = [DEFAULT_WORKSPACE_ROOT, CANONICAL_WORKSPACE_ROOT, LEGACY_WORKSPACE_ROOT]
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.expanduser())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root.expanduser())
    return deduped


def candidate_source_workspaces(issue_identifier: str) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()
    for root in workspace_roots_for_lookup():
        base = (root / issue_identifier).expanduser()
        explicit = [
            base,
            base.with_name(f"{issue_identifier}.handoff-latest"),
            base.with_name(f"{issue_identifier}.stale-latest"),
        ]
        for candidate in explicit:
            if not candidate.exists() or not candidate.is_dir():
                continue
            resolved = candidate.resolve()
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(resolved)

        parent = base.parent
        patterned: list[Path] = []
        for suffix in (".handoff-*", ".stale-*"):
            patterned.extend(candidate.resolve() for candidate in parent.glob(f"{issue_identifier}{suffix}") if candidate.is_dir())
        for candidate in sorted(patterned, key=lambda path: path.name, reverse=True):
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
    return candidates


def read_stage_handoff_metadata(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SystemExit(f"Missing stage handoff metadata: {path}") from exc

    data: dict[str, str] = {}
    for raw_line in text.splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        data[key.strip().lower()] = value.strip()
    return data


def read_release_source_metadata(source_workspace: Path) -> dict[str, str]:
    handoff_json = source_workspace / "SYMPHONY_HANDOFF.json"
    if handoff_json.exists():
        payload = json.loads(handoff_json.read_text(encoding="utf-8"))
        pr = payload.get("pr")
        if isinstance(pr, dict):
            metadata = {
                "pr_url": str(pr.get("url") or "").strip(),
                "merge_status": str(pr.get("merge_status") or "").strip(),
                "merge_commit": str(pr.get("merge_commit") or "").strip(),
                "branch": str(pr.get("branch") or "").strip(),
                "commit": str(pr.get("commit") or "").strip(),
            }
            if metadata["pr_url"] or metadata["merge_status"] or metadata["merge_commit"]:
                return metadata

    handoff = read_stage_handoff_metadata(source_workspace / "SYMPHONY_STAGE_HANDOFF.md")
    return {
        "pr_url": handoff.get("pr url", ""),
        "merge_status": handoff.get("merge status", ""),
        "merge_commit": handoff.get("merge commit", ""),
        "branch": handoff.get("branch", ""),
        "commit": handoff.get("commit", ""),
    }


def verify_release_source_metadata(source_workspace: Path) -> dict[str, str]:
    metadata = read_release_source_metadata(source_workspace)
    missing: list[str] = []
    if not metadata.get("pr_url"):
        missing.append("pr.url")
    if metadata.get("merge_status") != "merged":
        missing.append("pr.merge_status=merged")
    if not metadata.get("merge_commit"):
        missing.append("pr.merge_commit")
    if missing:
        raise SystemExit(
            "PR stage is not publishable for release follow-up; missing metadata: " + ", ".join(missing)
        )
    return metadata


def render_followup_metadata(
    stage: str,
    source_issue: dict[str, Any],
    source_workspace: Path,
    release_metadata: dict[str, str] | None = None,
) -> str:
    release_required = (
        "yes" if RELEASE_REQUIRED_LABEL in {name.strip().lower() for name in issue_label_names(source_issue)} else "no"
    )
    source_stage = classify_issue_type(issue_label_names(source_issue))
    lines = [
        FOLLOWUP_METADATA_HEADER,
        "```text",
        f"stage: {stage}",
        f"source_issue: {source_issue['identifier']}",
        f"source_stage: {source_stage}",
        f"source_workspace: {source_workspace}",
        "required_review_outcome: approved",
        f"release_required: {release_required}",
    ]
    if stage == "release":
        lines.append("required_pr_merge: yes")
        if release_metadata:
            if release_metadata.get("pr_url"):
                lines.append(f"pr_url: {release_metadata['pr_url']}")
            if release_metadata.get("merge_status"):
                lines.append(f"merge_status: {release_metadata['merge_status']}")
            if release_metadata.get("merge_commit"):
                lines.append(f"merge_commit: {release_metadata['merge_commit']}")
            if release_metadata.get("branch"):
                lines.append(f"pr_branch: {release_metadata['branch']}")
            if release_metadata.get("commit"):
                lines.append(f"pr_head_commit: {release_metadata['commit']}")
    lines.extend(["```", ""])
    return "\n".join(lines)


def parse_followup_metadata(description: str) -> dict[str, str]:
    metadata: dict[str, str] = {}

    block_match = re.search(
        rf"{re.escape(FOLLOWUP_METADATA_HEADER)}\s+```(?:text)?\n(.*?)```",
        description,
        flags=re.DOTALL,
    )
    if block_match:
        for raw_line in block_match.group(1).splitlines():
            line = raw_line.strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()

    fallback_patterns = {
        "source_issue": r"- Identifier:\s*([A-Z]+-\d+)",
        "source_workspace": r"- Source workspace:\s*`([^`]+)`",
        "source_stage": r"- Source type:\s*([a-z_]+)",
    }
    for key, pattern in fallback_patterns.items():
        if key in metadata:
            continue
        match = re.search(pattern, description)
        if match:
            metadata[key] = match.group(1).strip()

    return metadata


def review_verify_command(stage: str) -> list[str]:
    if stage == "pr":
        return [
            sys.executable,
            "scripts/stage_handoff.py",
            "review-verify",
            "--workspace",
            "__WORKSPACE__",
            "--stage",
            "feature",
            "--outcome",
            "approved",
        ]
    return [
        sys.executable,
        "scripts/stage_handoff.py",
        "review-verify",
        "--workspace",
        "__WORKSPACE__",
        "--stage",
        "pr",
        "--outcome",
        "approved",
    ]


def validate_followup_source_workspace(stage: str, source_issue: dict[str, Any], workspace: Path) -> Path:
    command = review_verify_command(stage)
    candidate_command = command[:]
    workspace_index = candidate_command.index("--workspace") + 1
    resolved = workspace.resolve()
    candidate_command[workspace_index] = str(resolved)
    repo_root = Path(__file__).resolve().parent.parent
    try:
        subprocess.run(candidate_command, cwd=repo_root, check=True, capture_output=True, text=True)
        if stage == "release":
            verify_release_source_metadata(resolved)
        return resolved
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        details = stderr or stdout or str(exc)
        raise SystemExit(f"{resolved}: {details}") from exc


def verify_followup_source_workspace(stage: str, source_issue: dict[str, Any]) -> Path:
    candidates = candidate_source_workspaces(source_issue["identifier"])
    if not candidates:
        raise SystemExit(f"Source workspace not found: {source_workspace_path(source_issue['identifier'])}")

    failures: list[str] = []
    for resolved in candidates:
        try:
            return validate_followup_source_workspace(stage, source_issue, resolved)
        except SystemExit as exc:
            failures.append(f"{resolved}: {exc}")

    raise SystemExit(
        f"Source workspace for {source_issue['identifier']} does not satisfy review-verify: " + " | ".join(failures)
    )


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


def delete_issue(api_key: str, issue_id: str, permanently_delete: bool = False) -> bool:
    query = """
    mutation($id: String!, $permanentlyDelete: Boolean) {
      issueDelete(id: $id, permanentlyDelete: $permanentlyDelete) {
        success
      }
    }
    """
    data = graphql(api_key, query, {"id": issue_id, "permanentlyDelete": permanently_delete})
    return bool(data["data"]["issueDelete"]["success"])


def project_issues(api_key: str, project_id: str) -> list[dict[str, Any]]:
    query = """
    query($projectId: String!) {
      project(id: $projectId) {
        issues(first: 250) {
          nodes {
            id
            identifier
            title
            url
            state { name }
            labels(first: 100) {
              nodes { name }
            }
          }
        }
      }
    }
    """
    data = graphql(api_key, query, {"projectId": project_id})
    return data["data"]["project"]["issues"]["nodes"]


def find_project_issue_by_title(api_key: str, project_id: str, title: str) -> dict[str, Any] | None:
    nodes = project_issues(api_key, project_id)
    for node in nodes:
        if node["title"].strip() == title.strip():
            return node
    return None


def find_generated_followup_issues(
    api_key: str,
    project_id: str,
    source_identifier: str,
    stages: list[str] | tuple[str, ...],
) -> list[dict[str, Any]]:
    nodes = project_issues(api_key, project_id)
    matches: list[dict[str, Any]] = []
    for stage in stages:
        expected_prefix = ("PR" if stage == "pr" else "Release") + f": {source_identifier} "
        wanted_labels = {f"{ISSUE_TYPE_PREFIX}{stage}", FOLLOWUP_LABEL}
        for node in nodes:
            labels = {name.strip().lower() for name in issue_label_names(node)}
            if not wanted_labels.issubset(labels):
                continue
            if node["title"].strip().startswith(expected_prefix):
                matches.append(node)
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in matches:
        if node["id"] in seen:
            continue
        seen.add(node["id"])
        deduped.append(node)
    return deduped


def find_generated_followup_issue(
    api_key: str,
    project_id: str,
    stage: str,
    source_identifier: str,
) -> dict[str, Any] | None:
    matches = find_generated_followup_issues(api_key, project_id, source_identifier, [stage])
    return matches[0] if matches else None


def cleanup_generated_followup_issues(
    api_key: str,
    source_issue: dict[str, Any],
    stages: list[str] | tuple[str, ...],
) -> list[dict[str, Any]]:
    project = source_issue.get("project") or {}
    project_id = project.get("id")
    if not project_id:
        raise SystemExit(f"Source issue {source_issue['identifier']} has no project")
    matches = find_generated_followup_issues(api_key, project_id, source_issue["identifier"], stages)
    for node in matches:
        delete_issue(api_key, node["id"])
    return matches


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


def followup_description(stage: str, source_issue: dict[str, Any], source_workspace: Path | None = None) -> str:
    workspace_path = source_workspace_path(source_issue["identifier"]) if source_workspace is None else source_workspace
    source_workspace_text = str(workspace_path)
    source_type = classify_issue_type(issue_label_names(source_issue))
    source_label_list = ", ".join(issue_label_names(source_issue)) or "none"
    release_metadata = verify_release_source_metadata(workspace_path) if stage == "release" else None
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
        f"- Source workspace: `{source_workspace_text}`",
        "",
        render_followup_metadata(stage, source_issue, workspace_path, release_metadata),
        "## Required Handoff Artifacts",
        "- `SYMPHONY_WORK_RESULT.md` from the source workspace is mandatory.",
        "- `SYMPHONY_HANDOFF.json` from the source workspace is mandatory.",
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
                f"- Required path: read `{source_workspace_text}/SYMPHONY_HANDOFF.json` first for stage, transition, and cycle metadata.",
                f"- Required path: read `{source_workspace_text}/SYMPHONY_STAGE_HANDOFF.md` before applying the diff.",
                f"- Required path: apply `{source_workspace_text}/SYMPHONY_STAGE_PATCH.diff` into this workspace before rerunning validation.",
                "- If the source workspace does not satisfy the feature handoff contract, do not continue this PR stage. Return the source issue to implementation or operator handling first.",
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
                "## Deterministic Runner",
                "- Run `python scripts/release_followup.py --issue-id {{ issue.identifier }}` immediately after release preflight.",
                "- Do not improvise a release sequence if the runner can execute it.",
                "- Default versioning policy is the next patch version from `pyproject.toml` unless the issue body explicitly overrides it.",
                "- If the runner fails but writes `SYMPHONY_WORK_RESULT.md` and `SYMPHONY_HANDOFF.json`, use those artifacts directly for the stage outcome.",
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
                "- The source PR is already merged before release publication starts.",
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
                f"- Required path: read `{source_workspace_text}/SYMPHONY_HANDOFF.json` first for stage, transition, and cycle metadata.",
                "- The release preflight metadata block in this issue is the machine-readable source of PR URL and merge metadata.",
                f"- Required path for human context: read `{source_workspace_text}/SYMPHONY_STAGE_HANDOFF.md` for branch and release notes context.",
                "- The source PR handoff must provide machine-readable `pr.url`, `pr.merge_status`, and `pr.merge_commit` metadata before this release issue may proceed.",
                "- If the source workspace does not satisfy the PR handoff contract, do not continue this release stage. Return the source issue to implementation or operator handling first.",
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
    source_workspace_override: Path | None = None,
) -> dict[str, Any]:
    source_workspace = (
        validate_followup_source_workspace(stage, source_issue, source_workspace_override)
        if source_workspace_override is not None
        else verify_followup_source_workspace(stage, source_issue)
    )
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
        "description": followup_description(stage, source_issue, source_workspace),
        "stateId": resolve_state_id(api_key, team_id, state),
        "labelIds": resolve_label_ids(api_key, team_id, label_names, create_missing_labels),
    }


def ensure_followup_issue(
    api_key: str,
    source_issue: dict[str, Any],
    stage: str,
    *,
    state: str = "Todo",
    explicit_title: str | None = None,
    extra_labels: list[str] | None = None,
    create_missing_labels: bool = True,
    source_workspace_override: Path | None = None,
) -> dict[str, Any]:
    if stage == "release" and RELEASE_REQUIRED_LABEL not in {
        label.strip().lower() for label in issue_label_names(source_issue)
    }:
        raise SystemExit(
            f"Source issue {source_issue['identifier']} is not marked `{RELEASE_REQUIRED_LABEL}`"
        )
    input_payload = build_followup_input(
        api_key,
        source_issue,
        stage,
        state,
        explicit_title,
        extra_labels or [],
        create_missing_labels,
        source_workspace_override,
    )
    existing = find_generated_followup_issue(
        api_key,
        input_payload["projectId"],
        stage,
        source_issue["identifier"],
    ) or find_project_issue_by_title(api_key, input_payload["projectId"], input_payload["title"])
    if existing:
        issue = update_issue(
            api_key,
            existing["id"],
            {
                "title": input_payload["title"],
                "description": input_payload["description"],
                "stateId": input_payload["stateId"],
                "labelIds": input_payload["labelIds"],
            },
        )
    else:
        issue = create_issue(api_key, input_payload)
    comment_issue(api_key, source_issue["id"], comment_for_followup(stage, source_issue, issue))
    return issue


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
            "cleanup-followups",
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
        "--stages",
        help="Comma-separated follow-up stages to target, e.g. pr,release; defaults to both for cleanup-followups",
    )
    parser.add_argument(
        "--create-missing-labels",
        action="store_true",
        help="Create missing team-level issue labels before creating the issue",
    )
    args = parser.parse_args()
    if args.command in {"preview", "create", "update"} and not args.title:
        parser.error("--title is required for preview/create/update")
    if args.command in {"state", "comment", "followup-pr", "followup-release", "cleanup-followups"} and not args.issue_id:
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
    if args.command in {"create", "update", "state", "comment", "labels", "followup-pr", "followup-release", "cleanup-followups"} and not api_key:
        raise SystemExit(
            "LINEAR_API_KEY is required for create/update/state/comment/labels/followup-pr/followup-release/cleanup-followups"
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

    if args.command == "cleanup-followups":
        source_issue = get_issue(api_key or "", args.issue_id or "")
        stages = parse_csv(args.stages) or ["pr", "release"]
        valid_stages = {"pr", "release"}
        invalid = [stage for stage in stages if stage not in valid_stages]
        if invalid:
            raise SystemExit(f"Unsupported follow-up stage(s): {', '.join(invalid)}")
        deleted = cleanup_generated_followup_issues(api_key or "", source_issue, stages)
        if not deleted:
            print(f"{source_issue['identifier']} no-followups")
            return 0
        for node in deleted:
            print(f"deleted {node['identifier']} {node['title']}")
        return 0

    if args.command in {"followup-pr", "followup-release"}:
        stage = "pr" if args.command == "followup-pr" else "release"
        source_issue = get_issue(api_key or "", args.issue_id or "")
        issue = ensure_followup_issue(
            api_key or "",
            source_issue,
            stage,
            state=args.state or "Todo",
            explicit_title=args.title,
            extra_labels=parse_csv(args.labels),
            create_missing_labels=args.create_missing_labels,
        )
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
