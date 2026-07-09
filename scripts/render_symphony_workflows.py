"""Render Symphony workflow templates with a concrete runtime root."""

from __future__ import annotations

import argparse
from pathlib import Path


TEMPLATE_FILES = (
    "WORKFLOW.yandexad.implementation.md",
    "WORKFLOW.yandexad.review.md",
)
SYMPHONY_ROOT_PLACEHOLDER = "<symphony-root>"
WORKSPACE_ROOT_PLACEHOLDER = "<workspace-root>"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symphony-root", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, default=Path("/private/tmp/symphony_yandexad_workspaces"))
    parser.add_argument(
        "--template-root",
        type=Path,
        default=Path("docs/automation/workflows"),
    )
    parser.add_argument("--output-root", type=Path)
    return parser.parse_args()


def render_file(template_path: Path, output_path: Path, symphony_root: Path, workspace_root: Path) -> None:
    rendered = template_path.read_text(encoding="utf-8")
    rendered = rendered.replace(SYMPHONY_ROOT_PLACEHOLDER, str(symphony_root))
    rendered = rendered.replace(WORKSPACE_ROOT_PLACEHOLDER, str(workspace_root))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")


def main() -> int:
    args = parse_args()
    symphony_root = args.symphony_root.expanduser().resolve()
    workspace_root = args.workspace_root.expanduser().resolve()
    output_root = (args.output_root or (symphony_root / "workflows")).expanduser().resolve()
    template_root = args.template_root.expanduser().resolve()
    for name in TEMPLATE_FILES:
        render_file(template_root / name, output_root / name, symphony_root, workspace_root)
        print(output_root / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
