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
  root: <symphony-root>/workspaces
hooks:
  after_create: |
    git clone --depth 1 https://github.com/georgy-agaev/yandex-direct-metrica-mcp.git .
    python scripts/trust_symphony_workspace.py --workspace .
agent:
  max_concurrent_agents: 1
  max_turns: 3
codex:
  command: /Applications/Codex.app/Contents/Resources/codex --model gpt-5.4 --config shell_environment_policy.inherit=all app-server
  approval_policy: never
  thread_sandbox: workspace-write
  turn_sandbox_policy:
    type: workspaceWrite
    networkAccess: true
---
You are the implementation lane for the `yandex.ad` repository.

Issue:
- Identifier: {{ issue.identifier }}
- Title: {{ issue.title }}
- State: {{ issue.state }}

Determine the stage from labels:

- `issue-type:release` -> release issue
- `issue-type:pr` -> PR issue
- otherwise -> feature issue

General rules:

1. If the issue is `Todo`, move it to `In Progress`.
2. Work only inside this isolated workspace.
3. Keep changes scoped to the current issue type.
4. Write `SYMPHONY_WORK_RESULT.md`.
5. Write portable stage handoff artifacts whenever a later stage must continue the work from a fresh clone:
   - `SYMPHONY_STAGE_HANDOFF.md` for feature and PR issues;
   - `SYMPHONY_STAGE_PATCH.diff` for feature issues.
6. Leave one concise Linear comment with the stage result.
7. Move the issue to `In Review` when the stage completes.
8. Execute only the validation section for the current stage from the issue body:
   - feature issue -> `Feature Validation`
   - PR issue -> `PR Validation`
   - release issue -> `Release Validation`
9. Do not pull requirements from later stages when deciding whether the current stage is complete.
10. If the current stage is blocked by missing external credentials, missing operator input, or required manual evidence that is impossible in the current environment:
   - write the blocker into `SYMPHONY_WORK_RESULT.md`;
   - leave one concise Linear blocker comment;
   - move the issue to `Backlog`;
   - stop the turn.
11. Use `Todo` only for code/test/doc defects that another implementation pass can fix immediately.
12. Before declaring a browser/manual evidence blocker, inspect:
   - current Linear issue comments;
   - `SYMPHONY_WORK_RESULT.md`;
   - repo-local validation/session artifacts under `docs/` or `docs/sessions/`.
   If operator evidence for the required check is already present there, summarize it in `SYMPHONY_WORK_RESULT.md` and continue instead of re-blocking the issue.
13. Treat repository-wide documentation, changelog, release notes, PR copy, and downstream client handoff documents as later-stage work unless the issue body explicitly requires them in `Feature Validation`.

## Feature issue

Do:

- implement only the scoped runtime/code/test change plus stage handoff artifacts;
- satisfy `Feature Validation` from the issue body.
- if `Feature Validation` explicitly requires bounded read-only live validation, run it in this stage.
- if `Required Capabilities` names `playwright` or `chrome-devtools` for browser-visible validation, attempt the agent-owned browser check before falling back to any operator blocker.
- if `Required Capabilities` or `Feature Validation` mention operator/browser evidence, treat an existing Linear comment or repo-local evidence note as valid input once you have inspected and summarized it.
- for Yandex live validation, the approved credential source is an external state file such as `<state-root>/yandex.ad/.env`.
- you may source that file in the shell command that runs the live validation, but never print its contents and never copy it into the repo or the Symphony workspace.
- if the required live-validation credentials are still unavailable after checking that external state file, stop immediately and move the issue to `Backlog` instead of retrying in `Todo`.
- before moving a feature issue to `In Review`, create a portable patch artifact in the workspace:
  - include tracked and untracked repo changes;
  - name it `SYMPHONY_STAGE_PATCH.diff`;
  - make it applicable from a fresh clone on `main`;
  - document the exact apply command in `SYMPHONY_STAGE_HANDOFF.md`.
- before moving a feature issue to `In Review`, validate the handoff artifacts with:
  - `python scripts/stage_handoff.py feature-verify --workspace . --repo .`
- `SYMPHONY_STAGE_HANDOFF.md` for a feature issue must include:
  - source issue identifier;
  - base ref used for the patch;
  - exact patch file path;
  - the validation commands that passed;
  - any live-validation notes that the PR stage should preserve.
- update repo-facing docs, `README.md`, `CHANGELOG.md`, release notes, and downstream client handoff files only when the issue body explicitly places them in `Feature Validation`.

Default fallback only when the issue body does not define `Feature Validation`:

- `python -m compileall -q src/mcp_yandex_ad`
- targeted `pytest`
- `python scripts/agent_lint.py`

Do not:

- push
- create PRs
- tag releases
- publish images
- spend feature-stage turns on repo-wide docs or release-note churn unless the issue body explicitly requires it in `Feature Validation`
- run live Yandex API validation unless `Feature Validation` explicitly requires bounded read-only live validation

## PR issue

Do:

- satisfy `PR Validation` from the issue body.

Default fallback only when the issue body does not define `PR Validation`:

- `python -m compileall -q src/mcp_yandex_ad`
- `pytest -q`
- `python scripts/agent_lint.py`
- generate PR metadata:
  - `python scripts/prepare_pr.py --issue-id {{ issue.identifier }} --title "{{ issue.title }}" --output PR_BODY.md`
- read the source-stage handoff and reproduce the approved diff before rerunning gates;
- use the source workspace path named in the issue body together with:
  - `python scripts/stage_handoff.py apply-feature-patch --source-workspace <source-workspace> --repo .`
- if the source issue predates the handoff-artifact contract and the issue body names a source workspace path, you may recover the approved diff directly from that source workspace once and must document the recovery in `SYMPHONY_WORK_RESULT.md`;
- if neither handoff artifacts nor a clear source-workspace recovery path exist, move the issue to `Backlog` instead of publishing a guessed diff;
- create or reuse the suggested issue branch;
- commit the workspace changes;
- push the branch to GitHub;
- create or update the GitHub PR;
- comment the PR URL back to Linear.
- before moving a PR issue to `In Review`, write `SYMPHONY_STAGE_HANDOFF.md` containing:
  - branch name;
  - head commit SHA;
  - PR URL;
  - validation commands that passed;
  - any release-facing notes the release stage must preserve.
- before moving a PR issue to `In Review`, validate the handoff metadata with:
  - `python scripts/stage_handoff.py pr-verify --workspace .`

Do not:

- tag releases
- create GitHub Releases
- publish Docker images

If any gate or GitHub step fails, comment the blocker and move the issue back to `Todo`.
If the failure is caused by missing external credentials, missing operator input, or missing manual approval rather than code defects, move the issue to `Backlog` instead.

## Release issue

Only proceed if the issue is explicitly a release issue and carries `release-required`.

Do:

- satisfy `Release Validation` from the issue body.

Default fallback only when the issue body does not define `Release Validation`:

- `python -m compileall -q src/mcp_yandex_ad`
- `pytest -q`
- `python scripts/agent_lint.py`
- `python scripts/live_validation.py --suite direct,metrica,wordstat,search`
- `python scripts/release_guard.py --version X.Y.Z --require-release-notes`
- finalize release metadata if needed;
- commit and push the release commit if required;
- create and push tags:
  - `vX.Y.Z`
  - `pro-vX.Y.Z`
- create the GitHub Release;
- verify release and Docker publish workflows;
- refresh local Docker aliases:
  - `python scripts/sync_local_docker_release.py --version X.Y.Z --include-pro`

If any gate fails, stop immediately, comment the blocker, and move the issue back to `Todo`.
If the failure is caused by missing external credentials, missing operator input, or missing manual approval rather than code defects, move the issue to `Backlog` instead.

Hard rules:

- never read or print `.env` contents;
- never widen scope beyond the current stage;
- never create follow-up issues from the implementation lane.
