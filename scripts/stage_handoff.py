"""Validate and apply Symphony stage handoff artifacts."""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path


COMMON_REQUIRED = (
    "SYMPHONY_WORK_RESULT.md",
    "SYMPHONY_HANDOFF.json",
)
FEATURE_REQUIRED = COMMON_REQUIRED + (
    "SYMPHONY_STAGE_HANDOFF.md",
    "SYMPHONY_STAGE_PATCH.diff",
)
PR_REQUIRED = COMMON_REQUIRED + ("SYMPHONY_STAGE_HANDOFF.md",)
SCHEMA_VERSION = 1
DEFAULT_MAX_ITERATIONS = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    feature_verify = subparsers.add_parser("feature-verify")
    feature_verify.add_argument("--workspace", type=Path, default=Path("."))
    feature_verify.add_argument("--repo", type=Path, default=Path("."))

    pr_verify = subparsers.add_parser("pr-verify")
    pr_verify.add_argument("--workspace", type=Path, default=Path("."))

    review_verify = subparsers.add_parser("review-verify")
    review_verify.add_argument("--workspace", type=Path, default=Path("."))
    review_verify.add_argument("--stage", choices=("feature", "pr", "release"), required=True)
    review_verify.add_argument("--outcome", choices=("approved", "needs_changes", "blocked"), required=True)

    apply_patch = subparsers.add_parser("apply-feature-patch")
    apply_patch.add_argument("--source-workspace", type=Path, required=True)
    apply_patch.add_argument("--repo", type=Path, default=Path("."))
    return parser.parse_args()


def ensure_files(workspace: Path, names: tuple[str, ...]) -> None:
    missing = [name for name in names if not (workspace / name).exists()]
    if missing:
        raise SystemExit(f"Missing handoff artifacts in {workspace}: {', '.join(missing)}")


def archive_head(repo: Path, target: Path) -> None:
    archive = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        tar.extractall(target, filter="data")


def load_handoff(workspace: Path) -> dict:
    try:
        handoff = json.loads((workspace / "SYMPHONY_HANDOFF.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Missing handoff artifacts in {workspace}: SYMPHONY_HANDOFF.json") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid SYMPHONY_HANDOFF.json in {workspace}: {exc}") from exc
    return handoff


def require_dict(payload: dict, key: str) -> dict:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise SystemExit(f"SYMPHONY_HANDOFF.json must contain object `{key}`")
    return value


def require_string(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"SYMPHONY_HANDOFF.json must contain non-empty string `{key}`")
    return value.strip()


def require_list(payload: dict, key: str) -> list:
    value = payload.get(key)
    if not isinstance(value, list):
        raise SystemExit(f"SYMPHONY_HANDOFF.json must contain array `{key}`")
    return value


def require_int(payload: dict, key: str, *, minimum: int) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or value < minimum:
        raise SystemExit(f"SYMPHONY_HANDOFF.json must contain integer `{key}` >= {minimum}")
    return value


def verify_common_handoff(
    workspace: Path,
    *,
    stage: str,
    role: str,
    to_state: str,
    statuses: set[str],
    next_actors: set[str],
) -> dict:
    handoff = load_handoff(workspace)
    if handoff.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit(f"SYMPHONY_HANDOFF.json schema_version must be {SCHEMA_VERSION}")

    issue = require_dict(handoff, "issue")
    require_string(issue, "identifier")
    require_string(issue, "title")

    stage_payload = require_dict(handoff, "stage")
    actual_stage = require_string(stage_payload, "type")
    actual_role = require_string(stage_payload, "role")
    if actual_stage != stage:
        raise SystemExit(f"SYMPHONY_HANDOFF.json stage.type must be `{stage}`, got `{actual_stage}`")
    if actual_role != role:
        raise SystemExit(f"SYMPHONY_HANDOFF.json stage.role must be `{role}`, got `{actual_role}`")

    transition = require_dict(handoff, "transition")
    require_string(transition, "from_state")
    actual_to_state = require_string(transition, "to_state")
    actual_status = require_string(transition, "status")
    if actual_to_state != to_state:
        raise SystemExit(f"SYMPHONY_HANDOFF.json transition.to_state must be `{to_state}`, got `{actual_to_state}`")
    if actual_status not in statuses:
        wanted = ", ".join(sorted(statuses))
        raise SystemExit(
            f"SYMPHONY_HANDOFF.json transition.status must be one of `{wanted}`, got `{actual_status}`"
        )

    cycle = require_dict(handoff, "cycle")
    iteration = require_int(cycle, "iteration", minimum=1)
    max_iterations = require_int(cycle, "max_iterations", minimum=1)
    if iteration > max_iterations:
        raise SystemExit("SYMPHONY_HANDOFF.json cycle.iteration must not exceed cycle.max_iterations")

    require_string(handoff, "summary")
    artifacts = require_list(handoff, "artifacts")
    if not artifacts:
        raise SystemExit("SYMPHONY_HANDOFF.json artifacts must not be empty")

    validation = require_dict(handoff, "validation")
    passed = validation.get("passed")
    if not isinstance(passed, list) or not passed:
        raise SystemExit("SYMPHONY_HANDOFF.json validation.passed must be a non-empty array")

    next_actor = require_string(handoff, "next_actor")
    if next_actor not in next_actors:
        wanted = ", ".join(sorted(next_actors))
        raise SystemExit(f"SYMPHONY_HANDOFF.json next_actor must be one of `{wanted}`, got `{next_actor}`")

    blockers = handoff.get("blockers", [])
    if not isinstance(blockers, list):
        raise SystemExit("SYMPHONY_HANDOFF.json blockers must be an array")
    if actual_status == "blocked" and not blockers:
        raise SystemExit("Blocked handoff must include at least one blocker")
    if role == "review" and actual_status == "needs_changes" and iteration >= max_iterations:
        raise SystemExit("Review handoff reached cycle.max_iterations; use blocked/operator instead of needs_changes")

    for artifact in artifacts:
        if not isinstance(artifact, str) or not artifact.strip():
            raise SystemExit("SYMPHONY_HANDOFF.json artifacts entries must be non-empty strings")
        if not (workspace / artifact).exists():
            raise SystemExit(f"SYMPHONY_HANDOFF.json references missing artifact: {artifact}")

    return handoff


def verify_feature(workspace: Path, repo: Path) -> None:
    ensure_files(workspace, FEATURE_REQUIRED)
    handoff = verify_common_handoff(
        workspace,
        stage="feature",
        role="implementation",
        to_state="In Review",
        statuses={"needs_review"},
        next_actors={"review"},
    )
    patch_path = (workspace / "SYMPHONY_STAGE_PATCH.diff").resolve()
    handoff_text = (workspace / "SYMPHONY_STAGE_HANDOFF.md").read_text(encoding="utf-8")
    if "apply" not in handoff_text.lower():
        raise SystemExit("SYMPHONY_STAGE_HANDOFF.md must document how to apply the patch")
    if "SYMPHONY_STAGE_PATCH.diff" not in handoff.get("artifacts", []):
        raise SystemExit("Feature handoff must list SYMPHONY_STAGE_PATCH.diff in artifacts")
    with tempfile.TemporaryDirectory(prefix="symphony-stage-check-") as tmp:
        archive_head(repo.resolve(), Path(tmp))
        subprocess.run(
            ["git", "apply", "--check", str(patch_path)],
            cwd=tmp,
            check=True,
        )
    print("feature-handoff-ok")


def verify_pr(workspace: Path) -> None:
    ensure_files(workspace, PR_REQUIRED)
    handoff = verify_common_handoff(
        workspace,
        stage="pr",
        role="implementation",
        to_state="In Review",
        statuses={"needs_review"},
        next_actors={"review"},
    )
    handoff_text = (workspace / "SYMPHONY_STAGE_HANDOFF.md").read_text(encoding="utf-8").lower()
    required_fragments = ("branch", "commit", "pr url")
    missing = [fragment for fragment in required_fragments if fragment not in handoff_text]
    if missing:
        raise SystemExit(f"PR handoff is missing required metadata: {', '.join(missing)}")
    if "SYMPHONY_STAGE_HANDOFF.md" not in handoff.get("artifacts", []):
        raise SystemExit("PR handoff must list SYMPHONY_STAGE_HANDOFF.md in artifacts")
    print("pr-handoff-ok")


def verify_review(workspace: Path, stage: str, outcome: str) -> None:
    if outcome == "approved":
        if stage == "feature":
            ensure_files(workspace, FEATURE_REQUIRED)
        elif stage == "pr":
            ensure_files(workspace, PR_REQUIRED)
        else:
            ensure_files(workspace, COMMON_REQUIRED)
    else:
        ensure_files(workspace, COMMON_REQUIRED)
    to_state = {
        "approved": "Done",
        "needs_changes": "Todo",
        "blocked": "Backlog",
    }[outcome]
    next_actors = {
        "approved": {
            "feature": {"followup-pr", "none"},
            "pr": {"followup-release", "none"},
            "release": {"none"},
        },
        "needs_changes": {
            "feature": {"implementation"},
            "pr": {"implementation"},
            "release": {"implementation"},
        },
        "blocked": {
            "feature": {"implementation", "operator"},
            "pr": {"implementation", "operator"},
            "release": {"implementation", "operator"},
        },
    }[outcome][stage]
    verify_common_handoff(
        workspace,
        stage=stage,
        role="review",
        to_state=to_state,
        statuses={outcome},
        next_actors=next_actors,
    )
    if stage == "feature" and outcome == "approved":
        ensure_files(workspace, FEATURE_REQUIRED)
    if stage == "pr" and outcome == "approved":
        ensure_files(workspace, PR_REQUIRED)
        handoff_text = (workspace / "SYMPHONY_STAGE_HANDOFF.md").read_text(encoding="utf-8").lower()
        required_fragments = ("branch", "commit", "pr url")
        missing = [fragment for fragment in required_fragments if fragment not in handoff_text]
        if missing:
            raise SystemExit(f"PR handoff is missing required metadata: {', '.join(missing)}")
    print("review-handoff-ok")


def resolve_source_workspace(source_workspace: Path) -> Path:
    source_workspace = source_workspace.expanduser()
    if source_workspace.exists():
        return source_workspace.resolve()

    parent = source_workspace.parent
    pattern = f"{source_workspace.name}*"
    candidates = sorted(parent.glob(pattern))
    candidates = [candidate for candidate in candidates if candidate.is_dir()]
    if not candidates:
        raise SystemExit(f"Source workspace not found: {source_workspace}")
    return candidates[-1].resolve()


def apply_feature_patch(source_workspace: Path, repo: Path) -> None:
    resolved_workspace = resolve_source_workspace(source_workspace)
    ensure_files(resolved_workspace, FEATURE_REQUIRED)
    patch_path = (resolved_workspace / "SYMPHONY_STAGE_PATCH.diff").resolve()
    subprocess.run(
        ["git", "apply", str(patch_path)],
        cwd=repo.resolve(),
        check=True,
    )
    print("feature-patch-applied")


def main() -> int:
    args = parse_args()
    if args.command == "feature-verify":
        verify_feature(args.workspace.resolve(), args.repo.resolve())
        return 0
    if args.command == "pr-verify":
        verify_pr(args.workspace.resolve())
        return 0
    if args.command == "review-verify":
        verify_review(args.workspace.resolve(), args.stage, args.outcome)
        return 0
    if args.command == "apply-feature-patch":
        apply_feature_patch(args.source_workspace, args.repo.resolve())
        return 0
    raise SystemExit(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
