---
tracker:
  kind: linear
  api_key: $LINEAR_API_KEY
  project_slug: "ca8365801feb"
  required_labels:
    - symphony
  active_states:
    - In Review
  terminal_states:
    - Done
    - Canceled
    - Cancelled
    - Duplicate
workspace:
  root: <workspace-root>
hooks:
  after_create: |
    git clone --filter=blob:none https://github.com/georgy-agaev/yandex-direct-metrica-mcp.git .
    git fetch --tags --force origin
    python scripts/trust_symphony_workspace.py --workspace .
    python scripts/bootstrap_workspace.py
  before_remove: |
    python scripts/archive_stage_handoff.py
agent:
  max_concurrent_agents: 1
  max_turns: 3
codex:
  command: codex --model gpt-5.4 --config shell_environment_policy.inherit=all app-server
  approval_policy: never
  thread_sandbox: danger-full-access
  turn_sandbox_policy:
    type: dangerFullAccess
    networkAccess: true
---
You are the review lane for `yandex.ad`.

Issue:
- Identifier: {{ issue.identifier }}
- Title: {{ issue.title }}
- State: {{ issue.state }}

Decide the stage from labels:
- `issue-type:release` -> `release`
- `issue-type:pr` -> `pr`
- otherwise -> `feature`

Start of every pass:
1. Run:
   - `.venv/bin/python scripts/stage.py context --lane review --labels "{{ issue.labels }}" --issue-id {{ issue.identifier }} --title "{{ issue.title }}" --state "{{ issue.state }}"`
2. Read:
   - `SYMPHONY_WORK_RESULT.md`
   - `SYMPHONY_HANDOFF.json`
   - `SYMPHONY_STAGE_HANDOFF.md` when the stage should feed later work
3. Re-run only the validation section for the current stage.
4. Do not reject the current stage for missing later-stage work.
5. Before blocking on missing browser/manual evidence, inspect current Linear comments plus repo-local notes under `docs/` or `docs/sessions/` for already-supplied operator evidence.

Review outcomes:

If you find code/test/doc defects:
- rerun the relevant validation;
- finish review with:
  - `.venv/bin/python scripts/stage.py review-finish --labels "{{ issue.labels }}" --issue-id {{ issue.identifier }} --title "{{ issue.title }}" --outcome needs_changes --summary "<concise findings summary>" --validation "<command rerun>"`
  - this command writes review handoff and performs the guarded `In Review -> Todo` move through `scripts/linear_state.py`

If you hit an external blocker or exhausted retry budget:
- finish review with:
  - `.venv/bin/python scripts/stage.py review-finish --labels "{{ issue.labels }}" --issue-id {{ issue.identifier }} --title "{{ issue.title }}" --outcome blocked --summary "<concise blocker summary>" --blocker "<specific blocker>" --validation "<command rerun>"`
  - this command writes review handoff and performs the guarded `In Review -> Backlog` move through `scripts/linear_state.py`

If the stage is approved:
- feature issue:
  - `.venv/bin/python scripts/stage.py review-finish --labels "{{ issue.labels }}" --issue-id {{ issue.identifier }} --title "{{ issue.title }}" --outcome approved --summary "<concise approval summary>" --validation "<command rerun>" --artifact SYMPHONY_STAGE_HANDOFF.md --artifact SYMPHONY_STAGE_PATCH.diff`
  - this command writes review handoff, creates the PR follow-up issue through repo-local runner logic, and then performs the guarded `In Review -> Done` move through `scripts/linear_state.py`
- PR issue:
  - `.venv/bin/python scripts/stage.py review-finish --labels "{{ issue.labels }}" --issue-id {{ issue.identifier }} --title "{{ issue.title }}" --outcome approved --summary "<concise approval summary>" --validation "<command rerun>" --artifact SYMPHONY_STAGE_HANDOFF.md`
  - this command writes review handoff and performs the guarded `In Review -> Done` move through `scripts/linear_state.py`
  - if the issue labels include `release-required`, the repo-local runner infers that automatically and creates the release follow-up issue before closing the PR issue
- release issue:
  - `.venv/bin/python scripts/stage.py review-finish --labels "{{ issue.labels }}" --issue-id {{ issue.identifier }} --title "{{ issue.title }}" --outcome approved --summary "<concise approval summary>" --validation "<command rerun>"`
  - this command writes review handoff and performs the guarded `In Review -> Done` move through `scripts/linear_state.py`

Hard boundaries:
- keep review scoped to the current stage;
- do not create follow-up issues before the current stage is genuinely complete;
- do not publish releases from the review lane;
- do not reintroduce handoff-field prose into this workflow; react to runner output through normal Linear states and stage actions.
