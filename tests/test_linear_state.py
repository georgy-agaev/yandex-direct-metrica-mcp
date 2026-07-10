from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts import linear_state


class FakeClient:
    def __init__(self, state: str) -> None:
        self.issue = {
            "id": "issue-1",
            "identifier": "GEO-22",
            "title": "Guard state transitions",
            "state": {"name": state},
            "team": {"id": "team-1"},
        }
        self.updates: list[tuple[str, str, str]] = []

    def get_issue(self, issue_id: str) -> dict:
        assert issue_id == self.issue["identifier"]
        return self.issue

    def set_state(self, issue_id: str, team_id: str, to_state: str) -> dict:
        self.updates.append((issue_id, team_id, to_state))
        self.issue["state"]["name"] = to_state
        return self.issue


def write_fixture(path: Path, *, state: str) -> None:
    path.write_text(
        json.dumps(
            {
                "issue": {
                    "identifier": "GEO-22",
                    "title": "Guard state transitions",
                    "state": state,
                    "team_id": "team-1",
                }
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_reject_transition_out_of_terminal_state() -> None:
    client = FakeClient("Done")

    payload = linear_state.move_issue("GEO-22", to_state="In Progress", by="implementation", client=client)

    assert payload["ok"] is False
    assert payload["reason"] == "terminal_locked"
    assert client.updates == []


def test_reject_illegal_role_scoped_transition() -> None:
    client = FakeClient("In Review")

    payload = linear_state.move_issue("GEO-22", to_state="In Progress", by="implementation", client=client)

    assert payload["ok"] is False
    assert payload["reason"] == "illegal_transition:implementation:In Review->In Progress"
    assert client.updates == []


def test_recheck_current_state_before_move() -> None:
    client = FakeClient("In Review")

    payload = linear_state.move_issue(
        "GEO-22",
        to_state="Done",
        by="review",
        expect="In Progress",
        client=client,
    )

    assert payload["ok"] is False
    assert payload["reason"] == "precondition_changed"
    assert client.updates == []


def test_stale_impl_session_cannot_reopen_approved_issue() -> None:
    client = FakeClient("Done")

    payload = linear_state.move_issue(
        "GEO-22",
        to_state="In Progress",
        by="implementation",
        expect="Todo",
        client=client,
    )

    assert payload["ok"] is False
    assert payload["reason"] == "terminal_locked"
    assert client.updates == []


def test_legal_transition_allowed() -> None:
    client = FakeClient("In Review")

    payload = linear_state.move_issue("GEO-22", to_state="Done", by="review", client=client)

    assert payload["ok"] is True
    assert payload["updated_state"] == "Done"
    assert client.updates == [("GEO-22", "team-1", "Done")]


def test_move_via_cli_rejects_terminal_state(tmp_path: Path) -> None:
    fixture = tmp_path / "linear-fixture.json"
    write_fixture(fixture, state="Done")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/linear_state.py",
            "move",
            "--issue-id",
            "GEO-22",
            "--to",
            "In Progress",
            "--by",
            "implementation",
            "--fixture",
            str(fixture),
        ],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["reason"] == "terminal_locked"
