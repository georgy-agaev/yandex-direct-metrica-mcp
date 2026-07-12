"""Persist Symphony handoff artifacts before a workspace is removed."""

from __future__ import annotations

import argparse
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
    for marker in (".handoff-latest", ".handoff-"):
        if marker in workspace.name:
            return workspace.name.split(marker, 1)[0]
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


def run_capture(cwd: Path, command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
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


def github_repo_context(workspace: Path) -> Path:
    return workspace if (workspace / ".git").exists() else ROOT


def github_pr_view(repo: Path, number: int | str) -> dict[str, object] | None:
    try:
        output = run_capture(
            repo,
            [
                "gh",
                "pr",
                "view",
                str(number),
                "--json",
                "number,title,url,state,mergedAt,mergeCommit,headRefName,headRefOid",
            ],
        )
    except SystemExit:
        return None
    payload = json.loads(output or "{}")
    return payload if isinstance(payload, dict) else None


def github_pr_for_branch(repo: Path, branch: str) -> dict[str, object] | None:
    try:
        output = run_capture(
            repo,
            [
                "gh",
                "pr",
                "list",
                "--state",
                "all",
                "--head",
                branch,
                "--json",
                "number,title,url,state,mergedAt,mergeCommit,headRefName",
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
            number = candidate.get("number")
            return github_pr_view(repo, number) if number is not None else candidate
    if not payload:
        return None
    candidate = payload[0]
    number = candidate.get("number") if isinstance(candidate, dict) else None
    return github_pr_view(repo, number) if number is not None else candidate


def github_pr_for_issue_identifier(repo: Path, issue_identifier: str) -> dict[str, object] | None:
    try:
        output = run_capture(
            repo,
            [
                "gh",
                "pr",
                "list",
                "--state",
                "all",
                "--search",
                f"{issue_identifier} in:title",
                "--json",
                "number,title,url,state,mergedAt,mergeCommit,headRefName",
                "--limit",
                "10",
            ],
        )
    except SystemExit:
        return None
    payload = json.loads(output or "[]")
    if not isinstance(payload, list):
        return None

    def score(candidate: dict[str, object]) -> tuple[int, int]:
        title = str(candidate.get("title") or "")
        prefix_match = int(title.startswith(f"{issue_identifier}:") or title.startswith(f"{issue_identifier} "))
        merged = int(str(candidate.get("state") or "").strip().lower() == "merged")
        return (prefix_match, merged)

    candidates = [candidate for candidate in payload if isinstance(candidate, dict)]
    if not candidates:
        return None
    candidates.sort(key=score, reverse=True)
    number = candidates[0].get("number")
    return github_pr_view(repo, number) if number is not None else candidates[0]


def merged_pr_metadata(workspace: Path, issue_identifier: str) -> dict[str, str] | None:
    repo = github_repo_context(workspace)
    branch = git_current_branch(workspace)

    pr = None
    if branch and branch not in {"main", "master"}:
        pr = github_pr_for_branch(repo, branch)
    if pr is None:
        pr = github_pr_for_issue_identifier(repo, issue_identifier)
    if not pr:
        return None

    merged_at = str(pr.get("mergedAt") or "").strip()
    merge_commit = ((pr.get("mergeCommit") or {}).get("oid") or "").strip()
    pr_url = str(pr.get("url") or "").strip()
    pr_state = str(pr.get("state") or "").strip().lower()
    pr_branch = str(pr.get("headRefName") or "").strip()
    pr_commit = str(pr.get("headRefOid") or "").strip() or (git_head_commit(workspace) or "")
    if pr_state != "merged" or not merged_at or not merge_commit or not pr_url or not pr_branch or not pr_commit:
        return None
    return {
        "branch": pr_branch,
        "commit": pr_commit,
        "pr_url": pr_url,
        "merge_commit": merge_commit,
        "merged_at": merged_at,
    }


def recover_pr_stage_artifacts(workspace: Path, issue: dict[str, object]) -> dict[str, object] | None:
    if issue_stage(issue) != "pr":
        return None
    if (workspace / "SYMPHONY_STAGE_HANDOFF.md").exists() and (workspace / "SYMPHONY_WORK_RESULT.md").exists():
        return None

    metadata = merged_pr_metadata(workspace, str(issue["identifier"]))
    if not metadata:
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
                    f"branch: {metadata['branch']}",
                    f"commit: {metadata['commit']}",
                    f"PR URL: {metadata['pr_url']}",
                    "merge status: merged",
                    f"merge commit: {metadata['merge_commit']}",
                    f"merged at: {metadata['merged_at']}",
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

    return metadata


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, help="Workspace or archive directory to reconcile/archive")
    parser.add_argument("--issue-id", help="Linear issue identifier override, e.g. GEO-39")
    parser.add_argument(
        "--reconcile-only",
        action="store_true",
        help="Run follow-up recovery without creating a new archive directory",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = (args.workspace or Path.cwd()).resolve()
    issue_identifier = args.issue_id or load_issue_identifier(workspace)
    followup = reconcile_followup(workspace, issue_identifier)
    if args.reconcile_only:
        if followup:
            print("followup: " + json.dumps(followup, ensure_ascii=False))
        else:
            print("followup: null")
        return 0

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
