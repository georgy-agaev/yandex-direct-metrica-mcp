"""Persist Symphony handoff artifacts before a workspace is removed."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import linear_issue, stage_handoff


ARCHIVE_CANDIDATES = (
    "SYMPHONY_WORK_RESULT.md",
    "SYMPHONY_HANDOFF.json",
    "SYMPHONY_STAGE_HANDOFF.md",
    "SYMPHONY_STAGE_PATCH.diff",
    "PR_BODY.md",
)
DEFAULT_CYCLE = {"iteration": 1, "max_iterations": 3}


def load_issue_identifier(workspace: Path) -> str:
    handoff_path = workspace / "SYMPHONY_HANDOFF.json"
    if handoff_path.exists():
        try:
            payload = json.loads(handoff_path.read_text(encoding="utf-8"))
            identifier = payload.get("issue", {}).get("identifier")
            if isinstance(identifier, str) and identifier.strip():
                return identifier.strip()
        except json.JSONDecodeError:
            pass
    return workspace.name


def archive_root(workspace: Path) -> Path:
    configured = os.environ.get("SYMPHONY_HANDOFF_ARCHIVE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return workspace.parent


def lowercase_labels(issue: dict[str, object]) -> set[str]:
    return {label.strip().lower() for label in linear_issue.issue_label_names(issue)}


def issue_stage(issue: dict[str, object]) -> str:
    return linear_issue.classify_issue_type(linear_issue.issue_label_names(issue))


def required_followup_stage(issue: dict[str, object]) -> str | None:
    state_name = ((issue.get("state") or {}).get("name") or "").strip()
    if state_name != "Done":
        return None
    stage = issue_stage(issue)
    if stage == "feature":
        return "pr"
    labels = lowercase_labels(issue)
    if stage == "pr" and linear_issue.RELEASE_REQUIRED_LABEL in labels:
        return "release"
    return None


def existing_artifacts(workspace: Path) -> list[str]:
    return [name for name in ARCHIVE_CANDIDATES if (workspace / name).exists()]


def run_capture(workspace: Path, command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or str(exc)).strip()
        raise SystemExit(details) from None
    return completed.stdout.strip()


def git_current_branch(workspace: Path) -> str | None:
    try:
        branch = run_capture(workspace, ["git", "branch", "--show-current"]).strip()
    except SystemExit:
        return None
    return branch or None


def git_head_commit(workspace: Path) -> str | None:
    try:
        commit = run_capture(workspace, ["git", "rev-parse", "HEAD"]).strip()
    except SystemExit:
        return None
    return commit or None


def github_pr_for_branch(workspace: Path, branch: str) -> dict[str, object] | None:
    try:
        output = run_capture(
            workspace,
            [
                "gh",
                "pr",
                "list",
                "--state",
                "all",
                "--head",
                branch,
                "--json",
                "number,url,state,mergedAt,mergeCommit,headRefName",
                "--limit",
                "5",
            ],
        )
    except SystemExit:
        return None
    payload = json.loads(output or "[]")
    if not isinstance(payload, list):
        return None
    for candidate in payload:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("headRefName") == branch:
            return candidate
    return payload[0] if payload else None


def recover_pr_stage_artifacts(workspace: Path, issue: dict[str, object]) -> dict[str, object] | None:
    if issue_stage(issue) != "pr":
        return None
    if (workspace / "SYMPHONY_STAGE_HANDOFF.md").exists() and (workspace / "SYMPHONY_WORK_RESULT.md").exists():
        return None

    branch = git_current_branch(workspace)
    commit = git_head_commit(workspace)
    if not branch or not commit:
        return None

    pr = github_pr_for_branch(workspace, branch)
    if not pr:
        return None

    merged_at = str(pr.get("mergedAt") or "").strip()
    merge_commit = ((pr.get("mergeCommit") or {}).get("oid") or "").strip()
    pr_url = str(pr.get("url") or "").strip()
    pr_state = str(pr.get("state") or "").strip().lower()
    if pr_state != "merged" or not merged_at or not merge_commit or not pr_url:
        return None

    if not (workspace / "SYMPHONY_STAGE_HANDOFF.md").exists():
        (workspace / "SYMPHONY_STAGE_HANDOFF.md").write_text(
            "\n".join(
                [
                    f"# {issue['identifier']} PR Stage Handoff",
                    "",
                    "## Summary",
                    "",
                    "- Recovered PR-stage metadata during archive reconciliation after an interrupted or incomplete terminal pass.",
                    "",
                    "## Metadata",
                    "",
                    f"branch: {branch}",
                    f"commit: {commit}",
                    f"PR URL: {pr_url}",
                    "merge status: merged",
                    f"merge commit: {merge_commit}",
                    f"merged at: {merged_at}",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    if not (workspace / "SYMPHONY_WORK_RESULT.md").exists():
        (workspace / "SYMPHONY_WORK_RESULT.md").write_text(
            "\n".join(
                [
                    f"# {issue['identifier']} Work Result",
                    "",
                    "## Stage",
                    "",
                    "- lane: review",
                    "- stage: pr",
                    "",
                    "## Summary",
                    "",
                    f"- {issue['title']}",
                    "- Recovered final PR-stage publication metadata during archive reconciliation so the release follow-up can continue.",
                    "",
                    "## Validation",
                    "",
                    "- `archive:recovered-pr-stage-artifacts`",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    return {
        "branch": branch,
        "commit": commit,
        "pr_url": pr_url,
        "merge_commit": merge_commit,
        "merged_at": merged_at,
    }


def synthesized_next_actor(stage: str, issue: dict[str, object]) -> str:
    if stage == "feature":
        return "followup-pr"
    if stage == "pr" and linear_issue.RELEASE_REQUIRED_LABEL in lowercase_labels(issue):
        return "followup-release"
    return "none"


def can_synthesize_review_handoff(workspace: Path, stage: str) -> bool:
    required = {"SYMPHONY_WORK_RESULT.md"}
    if stage == "feature":
        required.update({"SYMPHONY_STAGE_HANDOFF.md", "SYMPHONY_STAGE_PATCH.diff"})
    elif stage == "pr":
        required.add("SYMPHONY_STAGE_HANDOFF.md")
    return all((workspace / name).exists() for name in required)


def synthesize_review_handoff(workspace: Path, issue: dict[str, object]) -> dict[str, object] | None:
    handoff_path = workspace / "SYMPHONY_HANDOFF.json"
    if handoff_path.exists():
        return None

    stage = issue_stage(issue)
    if not can_synthesize_review_handoff(workspace, stage):
        return None

    artifacts = existing_artifacts(workspace)
    if "SYMPHONY_HANDOFF.json" not in artifacts:
        artifacts = [*artifacts, "SYMPHONY_HANDOFF.json"]

    payload = {
        "schema_version": 1,
        "issue": {
            "identifier": issue["identifier"],
            "title": issue["title"],
        },
        "stage": {"type": stage, "role": "review"},
        "transition": {"from_state": "In Review", "to_state": "Done", "status": "approved"},
        "cycle": DEFAULT_CYCLE,
        "summary": "Recovered approved handoff during archive reconciliation.",
        "artifacts": artifacts,
        "validation": {"passed": ["archive:recovered-approved-handoff"]},
        "next_actor": synthesized_next_actor(stage, issue),
        "blockers": [],
    }
    handoff_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    stage_handoff.verify_review(workspace, stage, "approved")
    return payload


def reconcile_followup(workspace: Path, issue_identifier: str) -> dict[str, object] | None:
    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        return None

    issue = linear_issue.get_issue(api_key, issue_identifier)
    recover_pr_stage_artifacts(workspace, issue)
    synthesize_review_handoff(workspace, issue)

    followup_stage = required_followup_stage(issue)
    if not followup_stage:
        return None

    project = issue.get("project") or {}
    project_id = project.get("id")
    if not project_id:
        raise SystemExit(f"Issue {issue_identifier} has no project; cannot reconcile follow-up")

    existing = linear_issue.find_generated_followup_issue(
        api_key,
        project_id,
        followup_stage,
        issue["identifier"],
    )
    if existing:
        return {
            "status": "exists",
            "stage": followup_stage,
            "identifier": existing["identifier"],
            "url": existing["url"],
        }

    try:
        created = linear_issue.ensure_followup_issue(
            api_key,
            issue,
            followup_stage,
            state="Todo",
            explicit_title=None,
            extra_labels=[],
            create_missing_labels=True,
            source_workspace_override=workspace,
        )
    except SystemExit as exc:
        message = str(exc)
        linear_issue.comment_issue(
            api_key,
            issue["id"],
            f"Symphony follow-up recovery blocked for `{followup_stage}`: {message}",
        )
        return {
            "status": "blocked",
            "stage": followup_stage,
            "reason": message,
        }
    return {
        "status": "created",
        "stage": followup_stage,
        "identifier": created["identifier"],
        "url": created["url"],
    }


def main() -> int:
    workspace = Path.cwd().resolve()
    issue_identifier = load_issue_identifier(workspace)
    followup = reconcile_followup(workspace, issue_identifier)
    root = archive_root(workspace)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    archive_dir = root / f"{issue_identifier}.handoff-{timestamp}"
    archive_dir.mkdir(parents=True, exist_ok=False)

    copied: list[str] = []
    for name in ARCHIVE_CANDIDATES:
        source = workspace / name
        if not source.exists():
            continue
        shutil.copy2(source, archive_dir / name)
        copied.append(name)

    (archive_dir / "ARCHIVE_SOURCE.txt").write_text(f"{workspace}\n", encoding="utf-8")

    latest_link = root / f"{issue_identifier}.handoff-latest"
    try:
        if latest_link.is_symlink() or latest_link.exists():
            latest_link.unlink()
        latest_link.symlink_to(archive_dir.name)
    except OSError:
        pass

    print(f"archived {issue_identifier} -> {archive_dir}")
    if copied:
        print("files: " + ", ".join(copied))
    else:
        print("files: none")
    if followup:
        print("followup: " + json.dumps(followup, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
