"""Validate and apply Symphony stage handoff artifacts."""

from __future__ import annotations

import argparse
import io
import subprocess
import tarfile
import tempfile
from pathlib import Path


FEATURE_REQUIRED = (
    "SYMPHONY_WORK_RESULT.md",
    "SYMPHONY_STAGE_HANDOFF.md",
    "SYMPHONY_STAGE_PATCH.diff",
)
PR_REQUIRED = (
    "SYMPHONY_WORK_RESULT.md",
    "SYMPHONY_STAGE_HANDOFF.md",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    feature_verify = subparsers.add_parser("feature-verify")
    feature_verify.add_argument("--workspace", type=Path, default=Path("."))
    feature_verify.add_argument("--repo", type=Path, default=Path("."))

    pr_verify = subparsers.add_parser("pr-verify")
    pr_verify.add_argument("--workspace", type=Path, default=Path("."))

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


def verify_feature(workspace: Path, repo: Path) -> None:
    ensure_files(workspace, FEATURE_REQUIRED)
    patch_path = (workspace / "SYMPHONY_STAGE_PATCH.diff").resolve()
    handoff_text = (workspace / "SYMPHONY_STAGE_HANDOFF.md").read_text(encoding="utf-8")
    if "apply" not in handoff_text.lower():
        raise SystemExit("SYMPHONY_STAGE_HANDOFF.md must document how to apply the patch")
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
    handoff_text = (workspace / "SYMPHONY_STAGE_HANDOFF.md").read_text(encoding="utf-8").lower()
    required_fragments = ("branch", "commit", "pr url")
    missing = [fragment for fragment in required_fragments if fragment not in handoff_text]
    if missing:
        raise SystemExit(f"PR handoff is missing required metadata: {', '.join(missing)}")
    print("pr-handoff-ok")


def apply_feature_patch(source_workspace: Path, repo: Path) -> None:
    ensure_files(source_workspace, FEATURE_REQUIRED)
    patch_path = (source_workspace / "SYMPHONY_STAGE_PATCH.diff").resolve()
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
    if args.command == "apply-feature-patch":
        apply_feature_patch(args.source_workspace.resolve(), args.repo.resolve())
        return 0
    raise SystemExit(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
