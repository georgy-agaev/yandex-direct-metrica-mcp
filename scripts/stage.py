"""Deterministic stage runner helpers for Symphony lanes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import stage_handoff


DEFAULT_MAX_ITERATIONS = 3
DEFAULT_WORK_RESULT = Path("SYMPHONY_WORK_RESULT.md")
DEFAULT_HANDOFF = Path("SYMPHONY_HANDOFF.json")


def parse_labels(raw: str) -> list[str]:
    return [label.strip() for label in raw.split(",") if label.strip()]


def detect_stage(labels: list[str]) -> str:
    normalized = {label.strip().lower() for label in labels}
    if "issue-type:release" in normalized:
        return "release"
    if "issue-type:pr" in normalized:
        return "pr"
    return "feature"


def validation_section(stage: str) -> str:
    return {
        "feature": "Feature Validation",
        "pr": "PR Validation",
        "release": "Release Validation",
    }[stage]


def stage_verify_hint(stage: str, lane: str) -> str | None:
    if lane == "implementation":
        return {
            "feature": "python scripts/stage_handoff.py feature-verify --workspace . --repo .",
            "pr": "python scripts/stage_handoff.py pr-verify --workspace .",
            "release": None,
        }[stage]
    return {
        "feature": "python scripts/stage_handoff.py review-verify --workspace . --stage feature --outcome <approved|needs_changes|blocked>",
        "pr": "python scripts/stage_handoff.py review-verify --workspace . --stage pr --outcome <approved|needs_changes|blocked>",
        "release": "python scripts/stage_handoff.py review-verify --workspace . --stage release --outcome <approved|needs_changes|blocked>",
    }[stage]


def add_stage_arguments(parser: argparse.ArgumentParser, *, required: bool) -> None:
    parser.add_argument("--stage", choices=("feature", "pr", "release"), required=required)
    parser.add_argument("--labels", default="")


def resolve_stage(args: argparse.Namespace) -> str:
    return getattr(args, "stage", None) or detect_stage(parse_labels(getattr(args, "labels", "")))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    context = sub.add_parser("context")
    context.add_argument("--lane", choices=("implementation", "review"), required=True)
    context.add_argument("--issue-id", required=True)
    context.add_argument("--title", required=True)
    context.add_argument("--state", required=True)
    add_stage_arguments(context, required=False)
    context.add_argument("--workspace", type=Path, default=Path("."))

    preflight = sub.add_parser("preflight")
    add_stage_arguments(preflight, required=False)
    preflight.add_argument("--issue-id", required=True)

    ready = sub.add_parser("implementation-ready")
    add_stage_arguments(ready, required=False)
    ready.add_argument("--issue-id", required=True)
    ready.add_argument("--title", required=True)
    ready.add_argument("--summary", required=True)
    ready.add_argument("--workspace", type=Path, default=Path("."))
    ready.add_argument("--repo", type=Path, default=Path("."))
    ready.add_argument("--from-state", default="In Progress")
    ready.add_argument("--validation", action="append", default=[])
    ready.add_argument("--artifact", action="append", default=[])
    ready.add_argument("--details-file", type=Path)

    blocked = sub.add_parser("implementation-blocked")
    add_stage_arguments(blocked, required=False)
    blocked.add_argument("--issue-id", required=True)
    blocked.add_argument("--title", required=True)
    blocked.add_argument("--summary", required=True)
    blocked.add_argument("--blocker", required=True)
    blocked.add_argument("--workspace", type=Path, default=Path("."))
    blocked.add_argument("--from-state", default="In Progress")
    blocked.add_argument("--next-actor", choices=("operator", "implementation"), default="operator")
    blocked.add_argument("--validation", action="append", default=[])
    blocked.add_argument("--details-file", type=Path)

    review = sub.add_parser("review-finish")
    add_stage_arguments(review, required=False)
    review.add_argument("--issue-id", required=True)
    review.add_argument("--title", required=True)
    review.add_argument("--outcome", choices=("approved", "needs_changes", "blocked"), required=True)
    review.add_argument("--summary", required=True)
    review.add_argument("--workspace", type=Path, default=Path("."))
    review.add_argument("--validation", action="append", default=[])
    review.add_argument("--artifact", action="append", default=[])
    review.add_argument("--blocker", action="append", default=[])
    review.add_argument("--details-file", type=Path)
    review.add_argument("--next-actor")
    review.add_argument("--release-required", action="store_true")
    review.add_argument("--from-state", default="In Review")
    return parser.parse_args()


def read_existing_handoff(workspace: Path) -> dict[str, Any] | None:
    path = workspace / DEFAULT_HANDOFF
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def current_cycle(workspace: Path) -> dict[str, int]:
    handoff = read_existing_handoff(workspace)
    if not handoff:
        return {"iteration": 1, "max_iterations": DEFAULT_MAX_ITERATIONS}
    cycle = handoff.get("cycle") or {}
    iteration = int(cycle.get("iteration", 1))
    max_iterations = int(cycle.get("max_iterations", DEFAULT_MAX_ITERATIONS))
    return {"iteration": iteration, "max_iterations": max_iterations}


def ensure_cycle_valid(cycle: dict[str, int]) -> None:
    if cycle["iteration"] < 1:
        raise SystemExit("cycle.iteration must be >= 1")
    if cycle["max_iterations"] < 1:
        raise SystemExit("cycle.max_iterations must be >= 1")
    if cycle["iteration"] > cycle["max_iterations"]:
        raise SystemExit("cycle.iteration must not exceed cycle.max_iterations")


def render_work_result(
    *,
    issue_id: str,
    title: str,
    stage: str,
    lane: str,
    summary: str,
    validations: list[str],
    details_file: Path | None,
    blockers: list[str] | None = None,
) -> str:
    lines = [
        f"# {issue_id} Work Result",
        "",
        "## Stage",
        "",
        f"- lane: {lane}",
        f"- stage: {stage}",
        "",
        "## Summary",
        "",
        f"- {title}",
        f"- {summary}",
        "",
    ]
    if details_file and details_file.exists():
        lines.extend(["## Details", "", details_file.read_text(encoding="utf-8").strip(), ""])
    if validations:
        lines.extend(["## Validation", "", *[f"- `{item}`" for item in validations], ""])
    if blockers:
        lines.extend(["## Blockers", "", *[f"- {item}" for item in blockers], ""])
    return "\n".join(lines).rstrip() + "\n"


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def write_handoff(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def context_payload(args: argparse.Namespace) -> dict[str, Any]:
    stage = resolve_stage(args)
    cycle = current_cycle(args.workspace.resolve())
    ensure_cycle_valid(cycle)
    return {
        "ok": True,
        "lane": args.lane,
        "issue": {"identifier": args.issue_id, "title": args.title, "state": args.state},
        "stage": stage,
        "validation_section": validation_section(stage),
        "cycle": cycle,
        "handoff_exists": (args.workspace.resolve() / DEFAULT_HANDOFF).exists(),
        "verify_hint": stage_verify_hint(stage, args.lane),
    }


def run_preflight(stage: str, issue_id: str) -> dict[str, Any]:
    if stage == "feature":
        return {"ok": True, "stage": stage, "issue": issue_id, "preflight": "not_required"}
    from scripts import followup_preflight

    import os

    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        raise SystemExit("LINEAR_API_KEY is required")
    issue = followup_preflight.load_issue(api_key, issue_id)
    return followup_preflight.preflight(issue, stage)


def base_artifacts(extra: list[str]) -> list[str]:
    return list(dict.fromkeys([DEFAULT_WORK_RESULT.name, DEFAULT_HANDOFF.name, *extra]))


def verify_stage_exit(stage: str, workspace: Path, repo: Path) -> None:
    if stage == "feature":
        stage_handoff.verify_feature(workspace, repo)
    elif stage == "pr":
        stage_handoff.verify_pr(workspace)


def implementation_ready(args: argparse.Namespace) -> dict[str, Any]:
    stage = resolve_stage(args)
    workspace = args.workspace.resolve()
    repo = args.repo.resolve()
    cycle = current_cycle(workspace)
    ensure_cycle_valid(cycle)
    validations = list(dict.fromkeys(args.validation))
    artifacts = base_artifacts(args.artifact)
    work_result = render_work_result(
        issue_id=args.issue_id,
        title=args.title,
        stage=stage,
        lane="implementation",
        summary=args.summary,
        validations=validations,
        details_file=args.details_file,
    )
    write_text(workspace / DEFAULT_WORK_RESULT, work_result)
    handoff = {
        "schema_version": 1,
        "issue": {"identifier": args.issue_id, "title": args.title},
        "stage": {"type": stage, "role": "implementation"},
        "transition": {"from_state": args.from_state, "to_state": "In Review", "status": "needs_review"},
        "cycle": cycle,
        "summary": args.summary,
        "artifacts": artifacts,
        "validation": {"passed": validations or ["runner:no-validation-recorded"]},
        "next_actor": "review",
        "blockers": [],
    }
    write_handoff(workspace / DEFAULT_HANDOFF, handoff)
    verify_stage_exit(stage, workspace, repo)
    return {"ok": True, "stage": stage, "to_state": "In Review", "status": "needs_review"}


def implementation_blocked(args: argparse.Namespace) -> dict[str, Any]:
    stage = resolve_stage(args)
    workspace = args.workspace.resolve()
    cycle = current_cycle(workspace)
    ensure_cycle_valid(cycle)
    validations = list(dict.fromkeys(args.validation))
    blockers = [args.blocker]
    work_result = render_work_result(
        issue_id=args.issue_id,
        title=args.title,
        stage=stage,
        lane="implementation",
        summary=args.summary,
        validations=validations,
        details_file=args.details_file,
        blockers=blockers,
    )
    write_text(workspace / DEFAULT_WORK_RESULT, work_result)
    handoff = {
        "schema_version": 1,
        "issue": {"identifier": args.issue_id, "title": args.title},
        "stage": {"type": stage, "role": "implementation"},
        "transition": {"from_state": args.from_state, "to_state": "Backlog", "status": "blocked"},
        "cycle": cycle,
        "summary": args.summary,
        "artifacts": [DEFAULT_WORK_RESULT.name, DEFAULT_HANDOFF.name],
        "validation": {"passed": validations or ["runner:blocked-before-validation"]},
        "next_actor": args.next_actor,
        "blockers": blockers,
    }
    write_handoff(workspace / DEFAULT_HANDOFF, handoff)
    return {"ok": True, "stage": stage, "to_state": "Backlog", "status": "blocked"}


def default_review_next_actor(stage: str, outcome: str, *, release_required: bool = False) -> str:
    if outcome == "approved":
        if stage == "feature":
            return "followup-pr"
        if stage == "pr":
            return "followup-release" if release_required else "none"
        return "none"
    if outcome == "needs_changes":
        return "implementation"
    return "operator"


def review_finish(args: argparse.Namespace) -> dict[str, Any]:
    stage = resolve_stage(args)
    workspace = args.workspace.resolve()
    cycle = current_cycle(workspace)
    ensure_cycle_valid(cycle)
    if args.outcome == "needs_changes":
        if cycle["iteration"] >= cycle["max_iterations"]:
            raise SystemExit("Review cannot emit needs_changes at cycle.max_iterations; use blocked instead")
        cycle = {"iteration": cycle["iteration"] + 1, "max_iterations": cycle["max_iterations"]}
    validations = list(dict.fromkeys(args.validation))
    blockers = list(dict.fromkeys(args.blocker))
    to_state = {"approved": "Done", "needs_changes": "Todo", "blocked": "Backlog"}[args.outcome]
    next_actor = args.next_actor or default_review_next_actor(
        stage,
        args.outcome,
        release_required=args.release_required,
    )
    artifacts = base_artifacts(args.artifact)
    work_result = render_work_result(
        issue_id=args.issue_id,
        title=args.title,
        stage=stage,
        lane="review",
        summary=args.summary,
        validations=validations,
        details_file=args.details_file,
        blockers=blockers or None,
    )
    write_text(workspace / DEFAULT_WORK_RESULT, work_result)
    handoff = {
        "schema_version": 1,
        "issue": {"identifier": args.issue_id, "title": args.title},
        "stage": {"type": stage, "role": "review"},
        "transition": {"from_state": args.from_state, "to_state": to_state, "status": args.outcome},
        "cycle": cycle,
        "summary": args.summary,
        "artifacts": artifacts,
        "validation": {"passed": validations or ["runner:no-validation-recorded"]},
        "next_actor": next_actor,
        "blockers": blockers,
    }
    write_handoff(workspace / DEFAULT_HANDOFF, handoff)
    stage_handoff.verify_review(workspace, stage, args.outcome)
    return {"ok": True, "stage": stage, "to_state": to_state, "status": args.outcome}


def main() -> int:
    args = parse_args()
    if args.command == "context":
        print(json.dumps(context_payload(args), ensure_ascii=False, indent=2))
        return 0
    if args.command == "preflight":
        print(json.dumps(run_preflight(resolve_stage(args), args.issue_id), ensure_ascii=False, indent=2))
        return 0
    if args.command == "implementation-ready":
        print(json.dumps(implementation_ready(args), ensure_ascii=False, indent=2))
        return 0
    if args.command == "implementation-blocked":
        print(json.dumps(implementation_blocked(args), ensure_ascii=False, indent=2))
        return 0
    if args.command == "review-finish":
        print(json.dumps(review_finish(args), ensure_ascii=False, indent=2))
        return 0
    raise SystemExit(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
