---
tracker:
  kind: linear
  api_key: $LINEAR_API_KEY
  project_slug: "ca8365801feb"
  required_labels:
    - symphony
  active_states:
    - Todo
    - In Progress
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
  command: /Applications/Codex.app/Contents/Resources/codex --model gpt-5.4 --config shell_environment_policy.inherit=all app-server
  approval_policy: never
  thread_sandbox: danger-full-access
  turn_sandbox_policy:
    type: dangerFullAccess
    networkAccess: true
---
You are the implementation lane for `yandex.ad`.

Issue:
- Identifier: {{ issue.identifier }}
- Title: {{ issue.title }}
- State: {{ issue.state }}

Decide the stage from labels:
- `issue-type:release` -> `release`
- `issue-type:pr` -> `pr`
- otherwise -> `feature`

Start of every pass:
1. If the issue is `Todo`, run:
   - `.venv/bin/python scripts/linear_state.py move --issue-id {{ issue.identifier }} --to "In Progress" --by implementation --expect Todo`
2. Work only inside this isolated workspace.
3. Run:
   - `.venv/bin/python scripts/stage.py context --lane implementation --labels "{{ issue.labels }}" --issue-id {{ issue.identifier }} --title "{{ issue.title }}" --state "{{ issue.state }}"`
4. Read the current issue body and obey only the validation section for the current stage.
5. Do not pull requirements from later stages when deciding whether the current stage is complete.
6. If an old blocker is still unresolved after checking current issue comments plus repo-local notes under `docs/` or `docs/sessions/`, stop through the runner instead of rediscovering it for multiple turns.

Feature stage:
- implement only scoped code/tests/docs owned by the feature stage;
- run live Yandex validation only when `Feature Validation` explicitly requires bounded read-only live checks;
- for browser/manual evidence, consume existing Linear comments or repo-local notes before declaring a blocker;
- write:
  - `SYMPHONY_WORK_RESULT.md`
  - `SYMPHONY_STAGE_HANDOFF.md`
  - `SYMPHONY_STAGE_PATCH.diff`
- before leaving the stage, run:
  - `.venv/bin/python scripts/stage.py implementation-ready --labels "{{ issue.labels }}" --issue-id {{ issue.identifier }} --title "{{ issue.title }}" --summary "<concise summary>" --validation "<command that passed>" --artifact SYMPHONY_STAGE_HANDOFF.md --artifact SYMPHONY_STAGE_PATCH.diff`
  - this command writes handoff artifacts and performs the guarded `In Progress -> In Review` move through `scripts/linear_state.py`

PR stage:
- start with:
  - `.venv/bin/python scripts/stage.py preflight --labels "{{ issue.labels }}" --issue-id {{ issue.identifier }}`
- apply the approved feature patch from the source workspace named in the issue body;
- rerun only `PR Validation`;
- create or update the issue branch, commit, push, and create or update the GitHub PR;
- if the chain carries `release-required`, do not finish the PR stage until the PR is merge-ready and merged;
- write:
  - `SYMPHONY_WORK_RESULT.md`
  - `SYMPHONY_STAGE_HANDOFF.md`
- before leaving the stage, run:
  - `.venv/bin/python scripts/stage.py implementation-ready --labels "{{ issue.labels }}" --issue-id {{ issue.identifier }} --title "{{ issue.title }}" --summary "<concise summary>" --validation "<command that passed>" --artifact SYMPHONY_STAGE_HANDOFF.md`
  - this command writes handoff artifacts and performs the guarded `In Progress -> In Review` move through `scripts/linear_state.py`

Release stage:
- start with:
  - `.venv/bin/python scripts/stage.py preflight --labels "{{ issue.labels }}" --issue-id {{ issue.identifier }}`
- then run:
  - `.venv/bin/python scripts/release_followup.py --issue-id {{ issue.identifier }} --include-pro`
- if `release_followup.py` writes `SYMPHONY_WORK_RESULT.md` and `SYMPHONY_HANDOFF.json`, treat those artifacts as the stage truth;
- do not replace the release runner with ad hoc release reasoning unless the runner itself is what needs repair.

Blocking:
- for missing external credentials, missing operator input, or manual validation that is impossible in the current environment, stop with:
  - `.venv/bin/python scripts/stage.py implementation-blocked --labels "{{ issue.labels }}" --issue-id {{ issue.identifier }} --title "{{ issue.title }}" --summary "<concise blocker summary>" --blocker "<specific blocker>"`
  - this command writes the blocker handoff and performs the guarded `In Progress -> Backlog` move through `scripts/linear_state.py`
- use `Todo` only for code/test/doc defects that another implementation pass can fix immediately.

Hard boundaries:
- feature stage does not push, publish PRs, tag releases, or publish images;
- PR stage does not create tags, GitHub Releases, or publish images;
- release stage owns publication;
- do not widen scope beyond the current issue type;
- do not reintroduce handoff-field prose into this workflow; react to runner output through normal Linear states and stage actions.
