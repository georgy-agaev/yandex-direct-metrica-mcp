# Harden Release Follow-up Creation Against Ephemeral Workspace and Prose-Dependent Merge Metadata

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
  - source-state-consistency chokepoint work (separate issue)
  - stale follow-up content drift / resync policy (separate issue)

## Required Capabilities

- browser: none
- live-api: no (tests are mock-based)
- manual-check: no
- operator step required: no

## External Inputs / Secrets

- required env:
  - none for required feature-stage validation (mock-based tests)
  - `LINEAR_API_KEY` only for optional live sanity
- source of truth:
  - `scripts/stage.py`, `scripts/linear_issue.py`
  - active workflow files under `docs/automation/workflows/`
  - `docs/automation/symphony-release-readiness-2026-07-11.md`
- available to Symphony parent process: not required for mandatory feature-stage validation

## Blocked Input Policy

- move to `Backlog` if:
  - required source handoff artifacts cannot be reconstructed from repo history
- return to `Todo` only for:
  - repo-local defects in the follow-up creation, metadata, or resolution logic and their tests

## Background

The `release-required` chain now reaches the release stage on the happy path (proven once by
`GEO-38 -> GEO-39 -> GEO-40 -> v2.0.15`). But the release follow-up is created inline
(`stage.py:review_finish -> create_followup_for_review -> linear_issue.ensure_followup_issue`) on top of
two fragile dependencies. The history of 7+ "harden follow-up recovery" commits reflects this fragility.

**F1 — filesystem-dependent source-workspace resolution.**
`linear_issue.candidate_source_workspaces()` finds the source PR workspace by globbing `"{name}*"` across
several workspace roots (including archived `.stale-*` / `.handoff-*` dirs) and picking the most-recent by
`st_mtime`. This depends on the workspace still being on disk and on the mtime heuristic selecting the
correct directory. Durable sources (Linear issue + git merge commit) are not the basis.

**F2 — prose-dependent merge-metadata gate.**
`linear_issue.verify_release_source_metadata()` reads the agent-authored `SYMPHONY_STAGE_HANDOFF.md` and
requires literal substrings (`"pr url"`, `"merge status: merged"`, `"merge commit:"`). Whether the release
follow-up is created therefore depends on the PR-stage agent writing three exact phrases. This is the same
"mechanics depend on model-authored prose" anti-pattern the stage runner removed elsewhere; it simply moved
into the handoff artifact.

On fast smokes both hold by luck (workspace still present, trivial issue -> predictable prose). On real
tasks with cleaned/rotated workspaces or differently-phrased handoffs, either dependency can silently
fail-close the release follow-up, reproducing "PR merged, no release created".

## Goal

Make release follow-up creation deterministic and independent of ephemeral workspace state and agent prose:
gate on structured data, derive from durable sources, and fail-closed with an explicit blocker when data is
genuinely missing.

## Scope

1. **F2 — structured merge metadata.**
   - `stage.py` (PR stage) writes merge metadata as structured fields in `SYMPHONY_HANDOFF.json`, e.g.
     `pr.url`, `pr.merge_status`, `pr.merge_commit`;
   - `verify_release_source_metadata` (and any follow-up gate) reads those structured JSON fields, not
     markdown substrings;
   - `SYMPHONY_STAGE_HANDOFF.md` may still carry the same facts for humans, but must not be the gate.

2. **F1 — durable metadata, deterministic resolution.**
   - carry the PR metadata the release stage needs (PR URL, merge commit) into the release follow-up issue
     body / Linear at creation time, so the release stage does not need to re-find the PR workspace on disk;
   - replace the most-recent-`st_mtime` glob heuristic with deterministic resolution (exact workspace key,
     or derivation from Linear + git merge commit);
   - if a workspace lookup is still required and the workspace is absent, fail-closed with an explicit
     blocker comment rather than silently skipping follow-up creation.

3. Add or extend mock-based tests for both.

## Non-goals

- redesigning Symphony itself;
- changing `search_serp` or any business feature behavior;
- reducing token profile;
- implementing the source-state-consistency chokepoint or drift policy;
- introducing browser automation.

## Acceptance Criteria

1. The PR-stage handoff records merge metadata as structured fields in `SYMPHONY_HANDOFF.json`
   (`pr.url`, `pr.merge_status`, `pr.merge_commit`), written by `stage.py`, not only as markdown prose.

2. Release follow-up creation gates on the structured fields, not on `SYMPHONY_STAGE_HANDOFF.md` substrings.
   Proof: with the structured fields present, follow-up creation succeeds even when the markdown wording is
   changed.

3. Release follow-up creation succeeds when the source PR workspace directory is absent, using durable
   metadata (Linear + structured handoff), not a live `/tmp` workspace.

4. When the required merge metadata is genuinely missing, the system fails closed with an explicit blocker
   comment; it never silently skips release follow-up creation.

5. Workspace resolution, where still used, is deterministic (exact key), not a most-recent-`st_mtime` guess.

6. The behavior above is covered by named, mock-based tests that fail on regression:
   - `test_pr_handoff_records_structured_merge_fields`
   - `test_release_followup_gates_on_structured_fields_not_prose`
   - `test_release_followup_created_when_source_workspace_absent`
   - `test_release_followup_fail_closed_with_blocker_when_metadata_missing`

## Feature Validation

- `.venv/bin/python -m pytest -q tests/test_stage_runner.py tests/test_linear_issue_followups.py`
- add and run a dedicated test file if new behavior needs it:
  - `.venv/bin/python -m pytest -q tests/test_release_followup_hardening.py`
- `.venv/bin/python -m compileall -q scripts`

## PR Validation

- rerun the full feature validation commands;
- inspect the diff and confirm the release follow-up gate reads structured fields and durable metadata, not
  ephemeral workspace state or markdown prose.

## Release Validation

- not required by default;
- validate as part of the next repeatability (Level D) smoke that forces a cleaned source workspace.

Feature-stage repo docs required: yes

## Handoff

- update `docs/automation/symphony-release-readiness-2026-07-11.md` Level D to require a cleaned-workspace
  and varied-handoff release follow-up check;
- write a short session note under `docs/sessions/` describing the structured metadata contract.

## Notes

- Release Required: no
- client handoff required: no
- Compatibility task
- Primary reference: `docs/automation/symphony-release-readiness-2026-07-11.md`
- Priority: blocks a trustworthy Level D; happy-path Level B currently passes only because smokes keep the
  source workspace present and the handoff prose predictable.
- Bootstrap guard: introduce structured fields additively; keep reading legacy markdown as a fallback until
  the structured path is test-covered, then make structured the gate.
