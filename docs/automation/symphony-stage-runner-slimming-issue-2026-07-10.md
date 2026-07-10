# Add Deterministic Stage Runner and Slim Symphony Workflows

Suggested labels:

- `symphony`
- `issue-type:feature`
- `automation`

## Execution Profile

- Issue Class: feature
- Risk: medium
- Retry Budget: 3
- Handoff Required: yes

## Ownership Boundary

- Owned by: `yandex.ad`
- Out of scope without a separate issue:
  - `Marketing2025`
  - changes to Linear product behavior itself
  - non-`yandex.ad` Symphony installations
  - follow-up issue drift / self-healing policy beyond what is required to keep the new runner backward-compatible

## Required Capabilities

- browser: none
- live-api: no
- manual-check: no
- operator step required: no

## External Inputs / Secrets

- required env:
  - none for feature-stage validation
  - `LINEAR_API_KEY` only if optional local checks touch live Linear issue bodies
- source of truth:
  - repo-local workflow files under `docs/automation/workflows/`
  - current automation scripts under `scripts/`
  - review findings in `docs/automation/symphony-autonomy-review-2026-07-09.md`
- available to Symphony parent process: not required for feature-stage validation

## Blocked Input Policy

- move to `Backlog` if:
  - a required source handoff artifact from prior automation work is missing and cannot be reconstructed from repo history
  - live Linear metadata required for a validation step cannot be read because `LINEAR_API_KEY` is unavailable
- return to `Todo` only for:
  - implementation defects in repo-local scripts, tests, workflow markdown, or handoff validation logic

## Background

The release-auth blocker was already fixed separately:

- early `GHCR_READ_TOKEN` release preflight;
- GHCR-aware local Docker sync diagnostics;
- non-shallow lane clones with tag fetch.

The next instability is prompt overload. `WORKFLOW.yandexad.implementation.md` still carries too much deterministic state-transition logic in prose. That makes the harness expensive and brittle because the lane must remember handoff mechanics, retry rules, and verifier invocation from prompt text instead of repo-local code.

This issue addresses only that layer:

- add a deterministic stage runner;
- slim the workflow prompts so they delegate to code;
- keep the cutover backward-compatible so the running harness does not break mid-migration.

## Goal

Move stage-critical mechanics out of prose and into a deterministic repo-local runner, while keeping the current handoff and verifier contracts backward-compatible during the cutover.

## Scope

1. Add a repo-local stage runner entry point, for example:
   - `python scripts/stage.py feature --issue-id GEO-X`
   - `python scripts/stage.py pr --issue-id GEO-X`
   - `python scripts/stage.py release --issue-id GEO-X`

2. Make the runner own deterministic mechanics that the prompt currently describes in prose:
   - read existing `SYMPHONY_HANDOFF.json` if present;
   - validate `cycle.iteration` / `cycle.max_iterations`;
   - dispatch the correct stage preflight;
   - write standard work-result and handoff artifacts;
   - run the right `stage_handoff.py *-verify` command before state exit;
   - print a compact machine-readable outcome for the lane to act on.

3. Reduce prompt responsibility in:
   - `docs/automation/workflows/WORKFLOW.yandexad.implementation.md`
   - `docs/automation/workflows/WORKFLOW.yandexad.review.md`

   The workflow files should call repo-local code for stage mechanics instead of manually restating handoff JSON rules, retry arithmetic, and verifier routing.
   When they react to the runner outcome, they should do so through normal Linear state names and stage actions rather than reintroducing handoff-field prose such as `next_actor` or `transition.to_state`.

4. Keep the cutover backward-compatible:
   - the new runner must be additive first;
   - existing `stage_handoff.py`, `followup_preflight.py`, `prepare_pr.py`, and `release_followup.py` contracts must keep working;
   - workflow markdown must not depend on half-migrated behavior.

5. Add or extend tests for:
   - stage runner routing;
   - handoff schema persistence across retries;
   - review-loop exhaustion behavior;
   - backward-compatible invocation of existing verifier helpers.

## Non-goals

- redesigning Symphony itself;
- changing release packaging or Docker distribution policy beyond the already-fixed auth path;
- introducing new Linear states;
- changing `search_serp` or any business feature behavior;
- adding browser-based automation to the harness;
- solving stale follow-up issue drift / regeneration policy in full detail;
- deleting or rewriting the existing follow-up helpers beyond what is necessary for backward-compatible runner adoption.

## Acceptance Criteria

1. A deterministic repo-local runner exists at `scripts/stage.py`.

2. `scripts/stage.py` supports explicit stage routing for `feature`, `pr`, and `release`.

3. A dedicated test file exists for the runner, for example `tests/test_stage_runner.py`, and covers at least:
   - stage routing;
   - existing-handoff loading;
   - cycle-bound enforcement;
   - machine-readable outcome emission.

4. Both active workflow files are measurably smaller after the change:
   - `docs/automation/workflows/WORKFLOW.yandexad.implementation.md` is at most 120 lines;
   - `docs/automation/workflows/WORKFLOW.yandexad.review.md` is at most 120 lines.

5. Both active workflow files explicitly invoke the runner.
   Concrete proxy:
   - `scripts/stage.py` must appear in:
     - `docs/automation/workflows/WORKFLOW.yandexad.implementation.md`
     - `docs/automation/workflows/WORKFLOW.yandexad.review.md`

6. Neither active workflow file contains a hand-written JSON field checklist for `SYMPHONY_HANDOFF.json`.
   Concrete proxy:
   - `schema_version`
   - `cycle.max_iterations`
   - `transition.to_state`
   - `next_actor`

   must not appear as prose instructions in those workflow files after the cutover.

7. The runner, not prompt prose, is the place that enforces:
   - handoff presence before stage exit;
   - verifier dispatch;
   - cycle-bound checking.

8. Existing verifier helpers remain usable after the cutover:
   - `scripts/stage_handoff.py`
   - `scripts/followup_preflight.py`
   - `scripts/prepare_pr.py`
   - `scripts/release_followup.py`

9. The migration is backward-compatible:
   - a partially updated workflow file must not require deleting or rewriting old handoff artifacts to keep the lane functional.

## Feature Validation

- `.venv/bin/python -m pytest -q tests/test_stage_handoff.py tests/test_followup_preflight.py tests/test_prepare_pr.py tests/test_release_followup.py tests/test_linear_issue_followups.py tests/test_stage_runner.py`
- `.venv/bin/python -m compileall -q scripts`
- `.venv/bin/python - <<'PY'
from pathlib import Path
for rel, limit in [
    ("docs/automation/workflows/WORKFLOW.yandexad.implementation.md", 120),
    ("docs/automation/workflows/WORKFLOW.yandexad.review.md", 120),
]:
    lines = Path(rel).read_text(encoding="utf-8").splitlines()
    assert len(lines) <= limit, (rel, len(lines), limit)
PY`
- `.venv/bin/python - <<'PY'
from pathlib import Path
for rel in [
    "docs/automation/workflows/WORKFLOW.yandexad.implementation.md",
    "docs/automation/workflows/WORKFLOW.yandexad.review.md",
]:
    text = Path(rel).read_text(encoding="utf-8")
    assert "scripts/stage.py" in text, rel
PY`
- `.venv/bin/python - <<'PY'
from pathlib import Path
needles = ["schema_version", "cycle.max_iterations", "transition.to_state", "next_actor"]
for rel in [
    "docs/automation/workflows/WORKFLOW.yandexad.implementation.md",
    "docs/automation/workflows/WORKFLOW.yandexad.review.md",
]:
    text = Path(rel).read_text(encoding="utf-8")
    for needle in needles:
        assert needle not in text, (rel, needle)
PY`

## PR Validation

- rerun the full feature validation commands;
- inspect the workflow diff and confirm the active workflow files call the new runner instead of repeating stage mechanics directly;
- verify that the new runner remains additive and does not require deleting legacy handoff helpers.

## Release Validation

- not required for this issue by default;
- if this automation change is intentionally shipped in a tagged release later, handle that in a separate release issue.

Feature-stage repo docs required: yes

## Handoff

- update operator-facing docs if launch or retry behavior changes:
  - `docs/automation/symphony-launch.md`
  - `docs/automation/symphony-pipeline.md`
- after merging this issue, rerender the external Symphony workflow copies before the next live lane run:
  - `python scripts/render_symphony_workflows.py --symphony-root "$SYMPHONY_ROOT" --workspace-root "$SYMPHONY_WORKSPACE_ROOT"`
- write a short session note under `docs/sessions/` summarizing:
  - what moved from prompt text into code;
  - what remained backward-compatible;
  - what operator-visible behavior changed.

## Notes

- Release Required: no
- client handoff required: no
- Compatibility task
- Primary reference: `docs/automation/symphony-autonomy-review-2026-07-09.md`
- Bootstrap guard: do not switch the workflow files to rely exclusively on the new runner until the runner path is test-covered and can coexist with the current helper scripts.
