# Guard Symphony Source-Issue State Transitions Against Concurrent Reopen

Suggested labels:

- `symphony`
- `issue-type:feature`
- `automation`
- `bug`

## Execution Profile

- Issue Class: bug
- Risk: high
- Retry Budget: 3
- Handoff Required: yes

## Ownership Boundary

- Owned by: `yandex.ad`
- Out of scope without a separate issue:
  - `Marketing2025`
  - changes to Linear product behavior itself
  - non-`yandex.ad` Symphony installations
  - stale follow-up content drift / resync policy (that is the separate follow-up-drift issue)

## Required Capabilities

- browser: none
- live-api: no
- manual-check: no
- operator step required: no

## External Inputs / Secrets

- required env:
  - none for required feature-stage validation (tests are mock-based)
  - `LINEAR_API_KEY` only for optional live sanity against a real Linear issue
- source of truth:
  - repo-local automation scripts under `scripts/`
  - active workflow files under `docs/automation/workflows/`
  - incident evidence in `docs/automation/symphony-autonomy-review-2026-07-09.md` and this issue Background
- available to Symphony parent process: not required for mandatory feature-stage validation; optional only for live sanity

## Blocked Input Policy

- move to `Backlog` if:
  - a required source handoff artifact from prior automation work is missing and cannot be reconstructed from repo history
- return to `Todo` only for:
  - repo-local defects in the state-transition helper, its guard logic, or its tests

## Background

First observed on the GEO-18 smoke run (issue GEO-20):

- the feature chain ran correctly: `Todo -> In Progress -> In Review`, implementation wrote a valid handoff, review approved, and the follow-up PR issue GEO-21 was created;
- but after approval the source issue **reopened**: expected `Done`, actual final state `In Progress`.

Evidence from run logs:

- the orchestrator observed the correct terminal state: `GEO-20 state=Done; stopping active agent`;
- the final Linear state was nevertheless `In Progress`, so a mutation moved the issue **out of `Done` after approval**;
- state attribution points at the implementation lane: its stream carried GEO-20 as `In Progress`; the review stream carried GEO-20 as `In Review` and never as `In Progress`;
- GEO-20 accumulated far more orchestrator activity than GEO-21 (thrash), which also inflated token spend.

Root cause: Symphony lanes change Linear state **ad hoc from the agent**, with no single guarded chokepoint. A long-lived implementation session outlived the review approval and re-asserted `In Progress` on an issue that was already terminal. There is currently no role-scoped legality rule that prevents implementation from mutating a review-owned issue, no terminal lock, and no re-check of current state before a move.

## Goal

Make source-issue state transitions safe under concurrent lanes and lingering sessions: an approved/terminal issue can never be reopened by a stale or non-owning session, and all state moves flow through one guarded, testable path.

## Scope

1. Introduce a single repo-local state-transition chokepoint (either a new helper, e.g. `scripts/linear_state.py move`, or an extension of `scripts/stage.py`) that every lane must use to change Linear issue state.

2. The chokepoint enforces these guards before performing any move:
   - **role-scoped legal transitions only:** enforce who may move which state:
     - implementation may only do `Todo -> In Progress`, `In Progress -> In Review`, and `In Progress -> Backlog`;
     - review may only do `In Review -> Done|Todo|Backlog`;
     - implementation must never move an issue that is already in `In Review`;
     - reject anything else;
   - **terminal lock:** refuse to move an issue OUT of a terminal state (`Done`, `Canceled`, `Cancelled`, `Duplicate`); fail closed;
   - **fresh-state recheck:** re-fetch the issue's current Linear state immediately before the move, and abort if it is no longer in a state this transition is valid from.

3. Route the active workflow files through the chokepoint instead of instructing the agent to move state directly:
   - `docs/automation/workflows/WORKFLOW.yandexad.implementation.md`
   - `docs/automation/workflows/WORKFLOW.yandexad.review.md`
   - prefer wiring `scripts/stage.py` to call the guarded state mover itself for `implementation-ready`, `implementation-blocked`, and `review-finish`, so handoff intent and Linear mutation stay in one repo-local path rather than as two separate agent steps.

4. Ensure the implementation lane does not re-mutate an issue it has already handed off to review:
   - after `implementation-ready` moves an issue to `In Review`, any further implementation-side move for that issue must go through the chokepoint and be rejected by the guards above.

5. Add or extend tests (mock-based, no live Linear) for the guard behavior.

## Non-goals

- redesigning Symphony itself or its concurrency model;
- introducing new Linear states;
- solving stale follow-up content drift / regeneration (separate issue);
- changing `search_serp` or any business feature behavior;
- reducing the token profile of a lane (tracked separately; re-measure after this fix);
- adding browser-based automation.

## Acceptance Criteria

1. A single repo-local state-transition chokepoint exists and is the only path the active workflows use to change Linear issue state.
   Note:
   - workflow grep checks are only a proxy for routing, not proof of exclusivity;
   - final exclusivity should be enforced architecturally by removing direct agent-owned Linear write access outside the chokepoint path.

2. Neither active workflow file instructs the agent to change Linear state directly without going through the chokepoint.
   Concrete proxy:
   - the active workflow files reference the chokepoint entry point (for example `scripts/linear_state.py` or `scripts/stage.py ... move`) wherever a state change is described.

3. The chokepoint refuses, fail-closed, to move an issue out of any terminal state.

4. The chokepoint refuses illegal role/state transitions even when the source state is non-terminal:
   - implementation-side `In Review -> *` is rejected;
   - review-side `Todo -> *` is rejected;
   - only the documented role-scoped transitions are allowed.

5. The chokepoint re-fetches current state before moving and aborts if the source state is not a legal precondition for the requested transition.
   The test must prove not merely that a fetch occurred, but that a stale precondition causes the move to be denied.

6. A simulated stale implementation session cannot reopen an approved issue:
   - given an issue already moved to `Done`, an implementation-side attempt to set `In Progress` is rejected.

7. The behavior above is covered by named, mock-based tests that fail if the guard regresses:
   - `test_reject_transition_out_of_terminal_state`
   - `test_reject_illegal_role_scoped_transition`
   - `test_recheck_current_state_before_move`
   - `test_stale_impl_session_cannot_reopen_approved_issue`
   - `test_legal_transition_allowed`
   - `test_move_via_cli_rejects_terminal_state`

## Feature Validation

- `.venv/bin/python -m pytest -q tests/test_linear_state.py`
- `.venv/bin/python -m compileall -q scripts`
- subprocess/integration smoke for the real workflow entry path:
  - `.venv/bin/python -m pytest -q tests/test_linear_state.py -k cli`
- positive proxy that workflows route state through the chokepoint:
  - `.venv/bin/python - <<'PY'
from pathlib import Path
needle = "linear_state.py"  # adjust if the chokepoint lives under stage.py
for rel in [
    "docs/automation/workflows/WORKFLOW.yandexad.implementation.md",
    "docs/automation/workflows/WORKFLOW.yandexad.review.md",
]:
  assert needle in Path(rel).read_text(encoding="utf-8"), rel
PY`
- if the new chokepoint is executable as a file, cover the same runtime path the workflow uses:
  - add the same `sys.path` bootstrap protection that `scripts/stage.py` now carries;
  - include at least one subprocess test that invokes the file, not only imported functions.
- optional live sanity only, not a required gate:
  - a single read-only current-state fetch for one real issue via the chokepoint

## PR Validation

- rerun the full feature validation commands;
- inspect the diff and confirm all state moves in the active workflows route through the guarded chokepoint;
- confirm the terminal-lock and fresh-state-recheck guards are the enforced path, not prose.

## Release Validation

- not required for this issue by default;
- if shipped in a tagged release later, handle that in a separate release issue.

Feature-stage repo docs required: yes

## Handoff

- update operator-facing docs if launch or retry behavior changes:
  - `docs/automation/symphony-launch.md`
  - `docs/automation/symphony-pipeline.md`
- after merge, rerender external Symphony workflow copies before the next live lane run;
- write a short session note under `docs/sessions/` summarizing the guard rules and the routed state-transition path.

## Notes

- Release Required: no
- client handoff required: no
- Compatibility task
- Primary reference: `docs/automation/symphony-autonomy-review-2026-07-09.md`
- Priority: fix this BEFORE the follow-up-drift issue and before running real tasks; it blocks safe live runs.
- Bootstrap guard: introduce the chokepoint additively; do not switch workflows to rely on it exclusively until it is test-covered and can coexist with current helpers. Run the first cutover under observation.
- Practical cutover order:
  1. add the chokepoint and tests;
  2. merge it to `main`;
  3. rerender external Symphony workflow copies from that `main`;
  4. only then run the next live smoke.
- Related but distinct from the follow-up-drift issue: this is about source-issue state ownership under concurrency, not follow-up content staleness.
