"""Run deterministic preflight checks for Symphony PR/release follow-up issues."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import linear_issue, linear_state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue-id", required=True, help="Linear issue identifier, for example GEO-15")
    parser.add_argument("--stage", choices=("pr", "release"), help="Expected issue stage; defaults to label-derived stage")
    return parser.parse_args()


def parse_github_pr_url(url: str) -> dict[str, str]:
    match = re.fullmatch(r"https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)", url.strip())
    if not match:
        raise SystemExit(f"Unsupported GitHub PR URL: {url}")
    return match.groupdict()


def github_pr_state(pr_url: str) -> dict[str, Any]:
    parsed = parse_github_pr_url(pr_url)
    command = [
        "gh",
        "pr",
        "view",
        parsed["number"],
        "--repo",
        f"{parsed['owner']}/{parsed['repo']}",
        "--json",
        "state,mergedAt,mergeCommit,url",
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or str(exc)).strip()
        raise SystemExit(f"GitHub PR lookup failed: {details}") from None
    return json.loads(result.stdout)


def issue_stage(issue: dict[str, Any]) -> str:
    return linear_issue.classify_issue_type(linear_issue.issue_label_names(issue))


def require_metadata(description: str) -> dict[str, str]:
    metadata = linear_issue.parse_followup_metadata(description)
    required = ("source_issue",)
    missing = [key for key in required if not metadata.get(key)]
    if missing:
        raise SystemExit("Follow-up issue is missing preflight metadata: " + ", ".join(missing))
    return metadata


def require_release_environment() -> dict[str, str]:
    token = os.environ.get("GHCR_READ_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "Release preflight requires GHCR_READ_TOKEN for private PRO image sync. "
            "Set it in the external yandex.ad state env before starting the release stage."
        )
    return {"ghcr_auth": "env:GHCR_READ_TOKEN"}


def ensure_source_issue_done(api_key: str, source_issue_identifier: str) -> dict[str, Any]:
    source_issue = linear_issue.get_issue(api_key, source_issue_identifier)
    current_state = source_issue["state"]["name"]
    if current_state == "Done":
        return {"status": "already_done", "state": current_state}

    if current_state != "In Review":
        raise SystemExit(
            f"Source issue {source_issue_identifier} must be `Done` before follow-up preflight; "
            f"current state is `{current_state}`."
        )

    move = linear_state.move_issue(
        source_issue_identifier,
        to_state="Done",
        by="followup",
        expect="In Review",
        client=linear_state.RepoLinearClient(api_key),
    )
    if not move["ok"]:
        raise SystemExit(
            f"Source issue {source_issue_identifier} could not be repaired to `Done`: {move['reason']}"
        )
    return {
        "status": "repaired",
        "from_state": current_state,
        "state": move["updated_state"],
    }


def preflight(issue: dict[str, Any], stage: str, *, api_key: str | None = None) -> dict[str, Any]:
    metadata = require_metadata(issue.get("description") or "")
    source_issue_identifier = metadata["source_issue"]
    repair = None
    if api_key:
        repair = ensure_source_issue_done(api_key, source_issue_identifier)
    result: dict[str, Any] = {
        "ok": True,
        "issue": issue["identifier"],
        "stage": stage,
        "source_issue": source_issue_identifier,
        "declared_source_workspace": metadata.get("source_workspace"),
        "source_stage": metadata.get("source_stage"),
        "required_review_outcome": metadata.get("required_review_outcome", "approved"),
    }
    if repair:
        result["source_issue_state"] = repair["state"]
        result["source_issue_repair"] = repair

    if stage == "release":
        result.update(require_release_environment())
        pr_url = metadata.get("pr_url")
        if not pr_url:
            raise SystemExit("Release preflight requires `pr_url` in follow-up metadata")
        if metadata.get("merge_status") != "merged":
            raise SystemExit("Release preflight requires `merge_status: merged` in follow-up metadata")
        merge_commit = metadata.get("merge_commit")
        if not merge_commit:
            raise SystemExit("Release preflight requires `merge_commit` in follow-up metadata")
        github_state = github_pr_state(pr_url)
        if github_state.get("state") != "MERGED" or not github_state.get("mergedAt"):
            raise SystemExit(f"Release preflight requires a merged PR; got state={github_state.get('state')}")
        result["pr_url"] = pr_url
        result["merge_status"] = metadata.get("merge_status")
        result["merge_commit"] = merge_commit
        result["github_pr_state"] = github_state["state"]
        result["github_merged_at"] = github_state.get("mergedAt")
    else:
        resolved_source_workspace = linear_issue.verify_followup_source_workspace(
            stage,
            {"identifier": source_issue_identifier},
        )
        result["resolved_source_workspace"] = str(resolved_source_workspace)
    return result


def load_issue(api_key: str, issue_id: str) -> dict[str, Any]:
    return linear_issue.get_issue(api_key, issue_id)


def main() -> int:
    args = parse_args()
    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        raise SystemExit("LINEAR_API_KEY is required")

    try:
        issue = load_issue(api_key, args.issue_id)
        stage = issue_stage(issue)
        if stage not in {"pr", "release"}:
            raise SystemExit(f"Unsupported issue stage for follow-up preflight: {stage}")
        if args.stage and args.stage != stage:
            raise SystemExit(f"Issue {issue['identifier']} stage mismatch: expected {args.stage}, got {stage}")
        payload = preflight(issue, stage, api_key=api_key)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except SystemExit as exc:
        message = str(exc)
        print(
            json.dumps(
                {
                    "ok": False,
                    "issue": args.issue_id,
                    "stage": args.stage,
                    "blocker": message,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
