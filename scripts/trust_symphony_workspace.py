"""Trust a Symphony workspace in the active Codex profile."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("."))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = args.workspace.expanduser().resolve()
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()
    config_path = codex_home / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text("", encoding="utf-8")

    entry = f'\n[projects."{workspace}"]\ntrust_level = "trusted"\n'
    text = config_path.read_text(encoding="utf-8")
    if entry.strip() not in text:
        config_path.write_text(text.rstrip() + entry + "\n", encoding="utf-8")
    print(workspace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
