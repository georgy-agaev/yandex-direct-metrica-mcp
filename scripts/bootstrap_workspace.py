"""Create or refresh the local Symphony workspace virtualenv."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
VENV_PYTHON = VENV / "bin" / "python"


def run(*args: str) -> None:
    subprocess.run(list(args), cwd=ROOT, check=True)


def healthy(python_bin: Path) -> bool:
    if not python_bin.exists():
        return False
    check = subprocess.run(
        [
            str(python_bin),
            "-c",
            "import pytest, tapi_yandex_direct, tapi_yandex_metrika, mcp_yandex_ad",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return check.returncode == 0


def main() -> int:
    if not VENV_PYTHON.exists():
        run(sys.executable, "-m", "venv", str(VENV))
    if not healthy(VENV_PYTHON):
        run(str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip")
        run(str(VENV_PYTHON), "-m", "pip", "install", "-e", ".[dev]")
    print(VENV_PYTHON)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
