"""Execute the deterministic Symphony release follow-up for a merged PR issue."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"
RELEASES_DIR = ROOT / "docs" / "releases"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import followup_preflight, linear_issue


VERSION_RE = re.compile(r'(?m)^version = "([^"]+)"$')
ALLOWED_DIRTY_PREFIXES = (
    "pyproject.toml",
    "CHANGELOG.md",
    "docs/releases/",
)
STALE_ARTIFACTS = (
    "SYMPHONY_WORK_RESULT.md",
    "SYMPHONY_HANDOFF.json",
    "RELEASE_SUMMARY.json",
)


@dataclass(frozen=True)
class WorkflowRun:
    workflow: str
    head_branch: str
    head_sha: str
    status: str
    conclusion: str | None
    url: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue-id", required=True, help="Linear release issue identifier, for example GEO-17")
    parser.add_argument("--version", help="Explicit release version. Defaults to the next patch after pyproject version.")
    parser.add_argument("--repo", default="georgy-agaev/yandex-direct-metrica-mcp", help="GitHub repository owner/name")
    parser.add_argument("--owner", default="georgy-agaev", help="Container registry owner for local Docker sync")
    parser.add_argument("--timeout-seconds", type=int, default=1800, help="Workflow polling timeout")
    parser.add_argument("--poll-interval", type=int, default=15, help="Workflow polling interval")
    parser.add_argument(
        "--skip-local-docker-sync",
        action="store_true",
        help="Skip the final local Docker latest-alias refresh step",
    )
    parser.add_argument(
        "--include-pro",
        action="store_true",
        help="Refresh the private PRO local Docker alias in addition to the public image",
    )
    return parser.parse_args()


def run(args: list[str], *, capture_output: bool = False, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=capture_output,
        input=input_text,
    )


def git_output(*args: str) -> str:
    return run(["git", *args], capture_output=True).stdout.strip()


def gh_output(*args: str) -> str:
    return run(["gh", *args], capture_output=True).stdout.strip()


def current_version() -> str:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]


def parse_semver(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value.strip())
    if not match:
        raise SystemExit(f"Unsupported version format: {value}")
    return tuple(int(part) for part in match.groups())


def next_patch_version(value: str) -> str:
    major, minor, patch = parse_semver(value)
    return f"{major}.{minor}.{patch + 1}"


def resolve_target_version(explicit: str | None) -> str:
    if explicit:
        parse_semver(explicit)
        return explicit
    return next_patch_version(current_version())


def remove_stale_artifacts() -> None:
    for name in STALE_ARTIFACTS:
        path = ROOT / name
        if path.exists():
            path.unlink()


def dirty_paths() -> list[str]:
    output = git_output("status", "--porcelain", "--untracked-files=all")
    paths: list[str] = []
    for raw_line in output.splitlines():
        if not raw_line:
            continue
        path = raw_line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path)
    return paths


def ensure_repo_ready_for_release() -> None:
    remove_stale_artifacts()
    dirty = dirty_paths()
    if not dirty:
        return
    unexpected = [path for path in dirty if not path.startswith(ALLOWED_DIRTY_PREFIXES)]
    if unexpected:
        raise SystemExit(
            "Release follow-up found unexpected dirty paths: " + ", ".join(unexpected)
        )


def replace_project_version(target_version: str) -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = VERSION_RE.search(text)
    if not match:
        raise SystemExit(f"Unable to locate project version in {PYPROJECT}")
    if match.group(1) == target_version:
        return
    PYPROJECT.write_text(VERSION_RE.sub(f'version = "{target_version}"', text, count=1), encoding="utf-8")


def split_changelog(text: str) -> tuple[str, str, str]:
    marker = "## Unreleased"
    start = text.find(marker)
    if start == -1:
        raise SystemExit("CHANGELOG.md is missing the `## Unreleased` section")
    body_start = start + len(marker)
    next_heading = text.find("\n## ", body_start)
    if next_heading == -1:
        next_heading = len(text)
    body = text[body_start:next_heading]
    return text[:start], body, text[next_heading:]


def extract_release_body_from_heading(text: str, version: str) -> str | None:
    heading = f"## {version} - "
    start = text.find(heading)
    if start == -1:
        return None
    body_start = text.find("\n", start)
    if body_start == -1:
        return None
    next_heading = text.find("\n## ", body_start + 1)
    if next_heading == -1:
        next_heading = len(text)
    body = text[body_start + 1 : next_heading].strip()
    return body or None


def normalize_release_body(body: str) -> str:
    normalized = body.strip()
    if not normalized:
        raise SystemExit("CHANGELOG `## Unreleased` section is empty; nothing to release.")
    return normalized


def update_changelog_for_release(target_version: str, release_date: str) -> str:
    text = CHANGELOG.read_text(encoding="utf-8")
    existing = extract_release_body_from_heading(text, target_version)
    if existing is not None:
        return existing
    prefix, unreleased_body, suffix = split_changelog(text)
    release_body = normalize_release_body(unreleased_body)
    updated = (
        f"{prefix}## Unreleased\n\n"
        f"## {target_version} - {release_date}\n\n"
        f"{release_body}\n"
        f"{suffix.lstrip()}"
    )
    CHANGELOG.write_text(updated, encoding="utf-8")
    return release_body


def write_release_notes(
    target_version: str,
    release_date: str,
    release_body: str,
    *,
    issue_identifier: str,
    source_issue: str,
    pr_url: str,
    validations: list[str] | None = None,
) -> Path:
    path = RELEASES_DIR / f"v{target_version}.md"
    if path.exists():
        return path
    lines = [
        f"# v{target_version}",
        "",
        "## Summary",
        "",
        f"- Release date: {release_date}",
        f"- Release issue: `{issue_identifier}`",
        f"- Source PR issue: `{source_issue}`",
        f"- Source PR: {pr_url}",
        "",
        "## Included",
        "",
        release_body,
        "",
    ]
    if validations:
        lines.extend(["## Validation", "", *[f"- `{item}`" for item in validations], ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def git_commit_if_needed(target_version: str, release_note: Path) -> str:
    if not dirty_paths():
        return git_output("rev-parse", "HEAD")
    run(["git", "add", "pyproject.toml", "CHANGELOG.md", str(release_note.relative_to(ROOT))])
    run(["git", "commit", "-m", f"Release v{target_version}"])
    return git_output("rev-parse", "HEAD")


def remote_tag_exists(tag: str) -> bool:
    result = subprocess.run(
        ["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode not in {0, 2}:
        raise SystemExit((result.stderr or result.stdout or f"git ls-remote failed for {tag}").strip())
    return bool(result.stdout.strip())


def ensure_local_tag(tag: str, commit_sha: str) -> None:
    result = subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"], cwd=ROOT, capture_output=True)
    if result.returncode == 0:
        return
    run(["git", "tag", tag, commit_sha])


def ensure_remote_tag(tag: str, commit_sha: str) -> None:
    ensure_local_tag(tag, commit_sha)
    if remote_tag_exists(tag):
        return
    run(["git", "push", "origin", tag])


def workflow_runs(workflow: str, *, branch: str | None = None, commit: str | None = None) -> list[WorkflowRun]:
    command = [
        "gh",
        "run",
        "list",
        "--workflow",
        workflow,
        "--event",
        "push",
        "--limit",
        "10",
        "--json",
        "workflowName,headBranch,headSha,status,conclusion,url,createdAt",
    ]
    if branch:
        command.extend(["--branch", branch])
    if commit:
        command.extend(["--commit", commit])
    data = json.loads(run(command, capture_output=True).stdout or "[]")
    return [
        WorkflowRun(
            workflow=item["workflowName"],
            head_branch=item.get("headBranch") or "",
            head_sha=item.get("headSha") or "",
            status=item["status"],
            conclusion=item.get("conclusion"),
            url=item["url"],
        )
        for item in data
    ]


def wait_for_workflow(
    workflow: str,
    *,
    branch: str | None = None,
    commit: str | None = None,
    timeout_seconds: int,
    poll_interval: int,
) -> WorkflowRun:
    deadline = time.time() + timeout_seconds
    last_seen: WorkflowRun | None = None
    while time.time() < deadline:
        runs = workflow_runs(workflow, branch=branch, commit=commit)
        if runs:
            last_seen = runs[0]
            if last_seen.status == "completed":
                if last_seen.conclusion == "success":
                    return last_seen
                raise SystemExit(f"Workflow failed: {workflow} -> {last_seen.conclusion} ({last_seen.url})")
        time.sleep(poll_interval)
    if last_seen:
        raise SystemExit(f"Workflow timed out: {workflow} status={last_seen.status} ({last_seen.url})")
    locator = f"branch={branch}" if branch else f"commit={commit}"
    raise SystemExit(f"Workflow did not appear: {workflow} ({locator})")


def ensure_github_release(tag: str, release_note: Path) -> str:
    view = subprocess.run(
        ["gh", "release", "view", tag, "--json", "url"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if view.returncode == 0:
        return json.loads(view.stdout)["url"]
    run(
        [
            "gh",
            "release",
            "create",
            tag,
            "--verify-tag",
            "--latest",
            "--title",
            tag,
            "--notes-file",
            str(release_note),
        ]
    )
    return json.loads(gh_output("release", "view", tag, "--json", "url"))["url"]


def ghcr_login(owner: str) -> None:
    token = gh_output("auth", "token")
    run(["docker", "login", "ghcr.io", "-u", owner, "--password-stdin"], input_text=token + "\n")


def write_success_artifacts(
    *,
    issue_id: str,
    issue_title: str,
    target_version: str,
    source_issue: str,
    pr_url: str,
    release_url: str,
    commit_sha: str,
    validations: list[str],
    workflows: dict[str, WorkflowRun],
    local_docker_sync: bool,
) -> None:
    summary_path = ROOT / "RELEASE_SUMMARY.json"
    summary = {
        "issue": issue_id,
        "source_issue": source_issue,
        "version": target_version,
        "release_url": release_url,
        "source_pr_url": pr_url,
        "commit": commit_sha,
        "tags": [f"v{target_version}", f"pro-v{target_version}"],
        "validations": validations,
        "workflows": {name: asdict(run_info) for name, run_info in workflows.items()},
        "local_docker_sync": local_docker_sync,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    work_result = ROOT / "SYMPHONY_WORK_RESULT.md"
    work_result.write_text(
        "\n".join(
            [
                f"# {issue_id} Work Result",
                "",
                "## Stage",
                "",
                "Release implementation.",
                "",
                "## Result",
                "",
                f"Published release `v{target_version}` for `{source_issue}` and refreshed the local Docker aliases.",
                "",
                "## Published Artifacts",
                "",
                f"- GitHub Release: {release_url}",
                f"- Public tag: `v{target_version}`",
                f"- Pro tag: `pro-v{target_version}`",
                f"- Release commit: `{commit_sha}`",
                f"- Source PR: {pr_url}",
                "",
                "## Validation",
                "",
                *[f"- `{item}`" for item in validations],
                "",
                "## Workflow Verification",
                "",
                *[
                    f"- {name}: {info.url} ({info.conclusion})"
                    for name, info in workflows.items()
                ],
                "",
                "## Local Docker",
                "",
                "- Refreshed `latest` aliases." if local_docker_sync else "- Skipped local Docker alias refresh.",
                "",
            ]
        ).rstrip()
        + "\n",
        encoding="utf-8",
    )

    handoff = {
        "schema_version": 1,
        "issue": {"identifier": issue_id, "title": issue_title},
        "stage": {"type": "release", "role": "implementation"},
        "transition": {"from_state": "In Progress", "to_state": "In Review", "status": "needs_review"},
        "cycle": {"iteration": 1, "max_iterations": 3},
        "summary": f"Published release v{target_version}, verified workflows, and refreshed local Docker aliases.",
        "artifacts": [
            "SYMPHONY_WORK_RESULT.md",
            "SYMPHONY_HANDOFF.json",
            "RELEASE_SUMMARY.json",
        ],
        "validation": {"passed": validations},
        "next_actor": "review",
        "blockers": [],
    }
    (ROOT / "SYMPHONY_HANDOFF.json").write_text(
        json.dumps(handoff, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        raise SystemExit("LINEAR_API_KEY is required")

    ensure_repo_ready_for_release()

    issue = linear_issue.get_issue(api_key, args.issue_id)
    if linear_issue.classify_issue_type(linear_issue.issue_label_names(issue)) != "release":
        raise SystemExit(f"Issue {args.issue_id} is not a release issue")

    preflight = followup_preflight.preflight(issue, "release")
    target_version = resolve_target_version(args.version)
    release_date = date.today().isoformat()
    source_issue = preflight["source_issue"]
    pr_url = preflight["pr_url"]

    replace_project_version(target_version)
    release_body = update_changelog_for_release(target_version, release_date)
    validations = [
        "python -m compileall -q src/mcp_yandex_ad",
        "pytest -q",
        "python scripts/agent_lint.py",
        "python scripts/live_validation.py --suite direct,metrica,wordstat,search",
        f"python scripts/release_guard.py --version {target_version} --require-release-notes",
    ]
    release_note = write_release_notes(
        target_version,
        release_date,
        release_body,
        issue_identifier=args.issue_id,
        source_issue=source_issue,
        pr_url=pr_url,
        validations=validations,
    )

    for command in (
        [sys.executable, "-m", "compileall", "-q", "src/mcp_yandex_ad"],
        [sys.executable, "scripts/agent_lint.py"],
        [sys.executable, "scripts/live_validation.py", "--suite", "direct,metrica,wordstat,search"],
        [sys.executable, "scripts/release_guard.py", "--version", target_version, "--require-release-notes"],
    ):
        run(command)
    run([sys.executable, "-m", "pytest", "-q"])

    commit_sha = git_commit_if_needed(target_version, release_note)
    if not remote_tag_exists(f"v{target_version}") or not remote_tag_exists(f"pro-v{target_version}"):
        run(["git", "push", "origin", "HEAD:main"])
    ensure_remote_tag(f"v{target_version}", commit_sha)
    ensure_remote_tag(f"pro-v{target_version}", commit_sha)

    workflows = {
        "CI": wait_for_workflow(
            "CI",
            commit=commit_sha,
            timeout_seconds=args.timeout_seconds,
            poll_interval=args.poll_interval,
        ),
        "Docker Publish (Public)": wait_for_workflow(
            "Docker Publish (Public)",
            branch=f"v{target_version}",
            timeout_seconds=args.timeout_seconds,
            poll_interval=args.poll_interval,
        ),
        "Docker Publish (Pro)": wait_for_workflow(
            "Docker Publish (Pro)",
            branch=f"pro-v{target_version}",
            timeout_seconds=args.timeout_seconds,
            poll_interval=args.poll_interval,
        ),
        "GitHub Release": wait_for_workflow(
            "GitHub Release",
            branch=f"v{target_version}",
            timeout_seconds=args.timeout_seconds,
            poll_interval=args.poll_interval,
        ),
    }

    release_url = ensure_github_release(f"v{target_version}", release_note)

    local_docker_sync = False
    if not args.skip_local_docker_sync:
        ghcr_login(args.owner)
        command = [
            sys.executable,
            "scripts/sync_local_docker_release.py",
            "--version",
            target_version,
            "--owner",
            args.owner,
        ]
        if args.include_pro:
            command.append("--include-pro")
        run(command)
        local_docker_sync = True

    write_success_artifacts(
        issue_id=args.issue_id,
        issue_title=issue["title"],
        target_version=target_version,
        source_issue=source_issue,
        pr_url=pr_url,
        release_url=release_url,
        commit_sha=commit_sha,
        validations=validations,
        workflows=workflows,
        local_docker_sync=local_docker_sync,
    )
    print(json.dumps({"ok": True, "version": target_version, "release_url": release_url}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
