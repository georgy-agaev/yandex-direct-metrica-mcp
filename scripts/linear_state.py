"""Guarded Linear state transitions for Symphony lanes."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import linear_issue

TERMINAL_STATES = {"Done", "Canceled", "Cancelled", "Duplicate"}
ALLOWED_TRANSITIONS = {
    ("implementation", "Todo"): {"In Progress"},
    ("implementation", "In Progress"): {"In Review", "Backlog"},
    ("review", "In Review"): {"Done", "Todo", "Backlog"},
}


@dataclass(frozen=True)
class TransitionDecision:
    ok: bool
    reason: str
    by: str
    from_state: str
    to_state: str

    def as_payload(self, issue_id: str) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issue_id": issue_id,
            "reason": self.reason,
            "by": self.by,
            "from_state": self.from_state,
            "to_state": self.to_state,
        }


class RepoLinearClient:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise SystemExit("LINEAR_API_KEY is required")
        self.api_key = api_key

    def get_issue(self, issue_id: str) -> dict[str, Any]:
        return linear_issue.get_issue(self.api_key, issue_id)

    def set_state(self, issue_id: str, team_id: str, to_state: str) -> dict[str, Any]:
        state_id = linear_issue.resolve_state_id(self.api_key, team_id, to_state)
        return linear_issue.update_issue_state(self.api_key, issue_id, state_id)


class FixtureLinearClient:
    def __init__(self, fixture: Path) -> None:
        self.fixture = fixture

    def _read(self) -> dict[str, Any]:
        return json.loads(self.fixture.read_text(encoding="utf-8"))

    def _write(self, payload: dict[str, Any]) -> None:
        self.fixture.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def get_issue(self, issue_id: str) -> dict[str, Any]:
        payload = self._read()
        issue = payload["issue"]
        if issue["identifier"] != issue_id:
            raise SystemExit(f"Fixture issue mismatch: expected {issue_id}, got {issue['identifier']}")
        return {
            "id": issue.get("id", issue_id),
            "identifier": issue["identifier"],
            "title": issue.get("title", issue_id),
            "state": {"name": issue["state"]},
            "team": {"id": issue.get("team_id", "fixture-team")},
        }

    def set_state(self, issue_id: str, team_id: str, to_state: str) -> dict[str, Any]:
        payload = self._read()
        issue = payload["issue"]
        if issue["identifier"] != issue_id:
            raise SystemExit(f"Fixture issue mismatch: expected {issue_id}, got {issue['identifier']}")
        issue["state"] = to_state
        issue["team_id"] = team_id
        self._write(payload)
        return {
            "id": issue.get("id", issue_id),
            "identifier": issue["identifier"],
            "title": issue.get("title", issue_id),
            "state": {"name": issue["state"]},
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    move = sub.add_parser("move")
    move.add_argument("--issue-id", required=True)
    move.add_argument("--to", dest="to_state", required=True)
    move.add_argument("--by", choices=("implementation", "review"), required=True)
    move.add_argument("--expect")
    move.add_argument("--fixture", type=Path)
    return parser.parse_args()


def plan_transition(by: str, from_state: str, to_state: str) -> TransitionDecision:
    if from_state in TERMINAL_STATES:
        return TransitionDecision(False, "terminal_locked", by, from_state, to_state)
    if to_state not in ALLOWED_TRANSITIONS.get((by, from_state), set()):
        return TransitionDecision(False, f"illegal_transition:{by}:{from_state}->{to_state}", by, from_state, to_state)
    return TransitionDecision(True, "allowed", by, from_state, to_state)


def build_client(*, fixture: Path | None = None, api_key: str | None = None) -> RepoLinearClient | FixtureLinearClient:
    if fixture is not None:
        return FixtureLinearClient(fixture)
    return RepoLinearClient(api_key or os.environ.get("LINEAR_API_KEY", ""))


def move_issue(
    issue_id: str,
    *,
    to_state: str,
    by: str,
    expect: str | None = None,
    client: RepoLinearClient | FixtureLinearClient | None = None,
) -> dict[str, Any]:
    active_client = client or build_client()
    issue = active_client.get_issue(issue_id)
    current_state = issue["state"]["name"]

    if current_state in TERMINAL_STATES:
        return TransitionDecision(False, "terminal_locked", by, current_state, to_state).as_payload(issue_id)

    if expect is not None and current_state != expect:
        return TransitionDecision(False, "precondition_changed", by, current_state, to_state).as_payload(issue_id)

    decision = plan_transition(by, current_state, to_state)
    if not decision.ok:
        return decision.as_payload(issue_id)

    updated = active_client.set_state(issue_id, issue["team"]["id"], to_state)
    payload = decision.as_payload(issue_id)
    payload["updated_state"] = updated["state"]["name"]
    return payload


def main() -> int:
    args = parse_args()
    if args.command != "move":
        raise SystemExit(f"Unsupported command: {args.command}")

    payload = move_issue(
        args.issue_id,
        to_state=args.to_state,
        by=args.by,
        expect=args.expect,
        client=build_client(fixture=args.fixture),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
