"""Manage the two-lane Symphony runtime for yandex.ad.

This launcher keeps secrets in the external state directory and starts only the
current implementation/review lanes. Deprecated PR/release lane processes are
stopped if their pid files are present.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from dotenv import dotenv_values


DEFAULT_SYMPHONY_ROOT = Path("/Users/georgyagaev/Projects/Symphony_yaad")
DEFAULT_STATE_ENV = Path("/Users/georgyagaev/mcp/state/yandex.ad/.env")
DEFAULT_CODEX_HOME = Path.home() / ".codex-symphony"
LANES: dict[str, dict[str, object]] = {
    "implementation": {
        "workflow": "WORKFLOW.yandexad.implementation.md",
        "pid_file": "symphony-yandexad-implementation.pid",
        "script_log": "symphony-yandexad-implementation.script.log",
        "stdout_log": "implementation.out",
        "port": 3321,
    },
    "review": {
        "workflow": "WORKFLOW.yandexad.review.md",
        "pid_file": "symphony-yandexad-review.pid",
        "script_log": "symphony-yandexad-review.script.log",
        "stdout_log": "review.out",
        "port": 3322,
    },
}
DEPRECATED_PID_FILES = (
    "symphony-yandexad-pr.pid",
    "symphony-yandexad-release.pid",
    "symphony-yandexad.pid",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "stop", "restart", "status", "render"))
    parser.add_argument(
        "--lanes",
        default="implementation,review",
        help="Comma-separated lane names; default: implementation,review",
    )
    parser.add_argument("--symphony-root", type=Path, default=DEFAULT_SYMPHONY_ROOT)
    parser.add_argument("--state-env", type=Path, default=DEFAULT_STATE_ENV)
    parser.add_argument("--codex-home", type=Path, default=DEFAULT_CODEX_HOME)
    parser.add_argument("--keep-deprecated", action="store_true")
    return parser.parse_args()


def lane_names(raw: str) -> list[str]:
    names = [item.strip() for item in raw.split(",") if item.strip()]
    invalid = [name for name in names if name not in LANES]
    if invalid:
        raise SystemExit(f"Unknown lane(s): {', '.join(invalid)}")
    return names


def pid_path(log_root: Path, pid_file: str) -> Path:
    return log_root / pid_file


def read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except FileNotFoundError:
        return None
    except ValueError:
        return None


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def stop_pid(path: Path) -> bool:
    pid = read_pid(path)
    if not pid:
        return False
    if process_alive(pid):
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not process_alive(pid):
                break
            time.sleep(0.25)
        if process_alive(pid):
            os.kill(pid, signal.SIGKILL)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return True


def build_env(symphony_root: Path, state_env: Path, codex_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    root_env = symphony_root / ".env"
    for source in (root_env, state_env):
        if source.exists():
            for key, value in dotenv_values(source).items():
                if value is not None:
                    env[key] = value
    env["SYMPHONY_ROOT"] = str(symphony_root)
    env["SYMPHONY_WORKSPACE_ROOT"] = str(symphony_root / "workspaces")
    env["CODEX_HOME"] = str(codex_home.expanduser())
    return env


def render_workflows(repo_root: Path, symphony_root: Path) -> None:
    subprocess.run(
        [sys.executable, "scripts/render_symphony_workflows.py", "--symphony-root", str(symphony_root)],
        cwd=repo_root,
        check=True,
    )


def start_lane(repo_root: Path, symphony_root: Path, env: dict[str, str], lane: str) -> int:
    config = LANES[lane]
    log_root = symphony_root / "logs"
    workflow = symphony_root / "workflows" / str(config["workflow"])
    script_log = log_root / str(config["script_log"])
    stdout_log = log_root / str(config["stdout_log"])
    pid_file = log_root / str(config["pid_file"])
    log_root.mkdir(parents=True, exist_ok=True)
    (symphony_root / "workspaces").mkdir(parents=True, exist_ok=True)
    with stdout_log.open("ab") as stdout_handle, script_log.open("ab") as stderr_handle:
        process = subprocess.Popen(
            [
                "/opt/homebrew/bin/mise",
                "exec",
                "--",
                "./bin/symphony",
                str(workflow),
                "--logs-root",
                str(log_root),
                "--port",
                str(config["port"]),
                "--i-understand-that-this-will-be-running-without-the-usual-guardrails",
            ],
            cwd=symphony_root / "symphony" / "elixir",
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
            start_new_session=True,
        )
    pid_file.write_text(f"{process.pid}\n", encoding="utf-8")
    return process.pid


def status(log_root: Path, lanes: list[str], keep_deprecated: bool) -> int:
    shown = False
    for lane in lanes:
        path = pid_path(log_root, str(LANES[lane]["pid_file"]))
        pid = read_pid(path)
        alive = bool(pid and process_alive(pid))
        print(f"{lane}: {'running' if alive else 'stopped'}" + (f" pid={pid}" if pid else ""))
        shown = True
    if not keep_deprecated:
        for name in DEPRECATED_PID_FILES:
            path = log_root / name
            pid = read_pid(path)
            alive = bool(pid and process_alive(pid))
            print(f"deprecated:{name}: {'running' if alive else 'stopped'}" + (f" pid={pid}" if pid else ""))
            shown = True
    return 0 if shown else 1


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    symphony_root = args.symphony_root.expanduser().resolve()
    state_env = args.state_env.expanduser().resolve()
    codex_home = args.codex_home.expanduser().resolve()
    log_root = symphony_root / "logs"
    lanes = lane_names(args.lanes)

    if args.command == "render":
        render_workflows(repo_root, symphony_root)
        return 0

    if args.command in {"stop", "restart"}:
        for lane in lanes:
            stop_pid(pid_path(log_root, str(LANES[lane]["pid_file"])))
        if not args.keep_deprecated:
            for name in DEPRECATED_PID_FILES:
                stop_pid(log_root / name)
        if args.command == "stop":
            return 0

    if args.command == "status":
        return status(log_root, lanes, args.keep_deprecated)

    render_workflows(repo_root, symphony_root)
    env = build_env(symphony_root, state_env, codex_home)
    for lane in lanes:
        pid = start_lane(repo_root, symphony_root, env, lane)
        print(f"{lane} pid={pid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
