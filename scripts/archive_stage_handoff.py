"""Persist Symphony handoff artifacts before a workspace is removed."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


ARCHIVE_CANDIDATES = (
    "SYMPHONY_WORK_RESULT.md",
    "SYMPHONY_HANDOFF.json",
    "SYMPHONY_STAGE_HANDOFF.md",
    "SYMPHONY_STAGE_PATCH.diff",
    "PR_BODY.md",
)


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


def main() -> int:
    workspace = Path.cwd().resolve()
    issue_identifier = load_issue_identifier(workspace)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
