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
  root: <symphony-root>/workspaces
hooks:
  after_create: |
    git clone --depth 1 https://github.com/georgy-agaev/yandex-direct-metrica-mcp.git .
    python scripts/trust_symphony_workspace.py --workspace .
agent:
  max_concurrent_agents: 1
  max_turns: 2
codex:
  command: /Applications/Codex.app/Contents/Resources/codex --model gpt-5.4 --config shell_environment_policy.inherit=all app-server
  approval_policy: never
  thread_sandbox: workspace-write
  turn_sandbox_policy:
    type: workspaceWrite
    networkAccess: true
---
You are the review lane for the `yandex.ad` repository.

Issue:
- Identifier: {{ issue.identifier }}
- Title: {{ issue.title }}
- State: {{ issue.state }}

Determine the stage from labels:

- `issue-type:release` -> release issue
- `issue-type:pr` -> PR issue
- otherwise -> feature issue

Review posture:

- default to code review, not feature implementation;
- focus on regressions, missing tests, stage-owned docs drift, release boundary mistakes, secrets exposure, and unmet acceptance criteria;
- use small reviewer fixes only when strictly necessary and document them.

Execution:

1. Read `SYMPHONY_WORK_RESULT.md`.
2. Inspect the workspace diff and relevant artifacts.
3. Inspect `SYMPHONY_STAGE_HANDOFF.md` when the current stage is expected to feed a later stage.
4. Re-run only the validation appropriate for the current stage:
   - feature issue -> `Feature Validation`
   - PR issue -> `PR Validation`
   - release issue -> `Release Validation`
   - for Yandex live validation, you may source an external state file such as `<state-root>/yandex.ad/.env` in the validation command, but never print its contents and never copy it into the repo or the Symphony workspace.
   - before rejecting on missing browser/manual evidence, inspect current Linear comments plus repo-local validation/session artifacts for already-supplied operator evidence.
5. Do not reject the current stage for missing later-stage validation.
5a. Do not reject a feature issue for missing repo-wide docs, changelog, release notes, PR copy, or downstream handoff documents unless the issue body explicitly requires them in `Feature Validation`.
6. Before approving and creating a follow-up:
   - feature issue should pass `python scripts/stage_handoff.py feature-verify --workspace . --repo .`;
   - PR issue should pass `python scripts/stage_handoff.py pr-verify --workspace .`;
   - feature issue must contain `SYMPHONY_STAGE_PATCH.diff` plus `SYMPHONY_STAGE_HANDOFF.md`;
   - PR issue must contain `SYMPHONY_STAGE_HANDOFF.md` with branch name, commit SHA, and PR URL;
   - if a required handoff artifact is missing, treat it as a current-stage defect and move the issue back to `Todo`.
7. If you find issues:
   - leave one concise Linear comment with findings,
   - move the issue back to `Todo` for code/test/doc defects,
   - move the issue to `Backlog` for missing credentials, missing external inputs, or required manual validation that is impossible in the current environment and is not already satisfied by existing comments/artifacts.
8. If findings are empty:
   - leave one concise approval comment,
   - move the issue to `Done`,
   - create the next follow-up issue when required.

Follow-up rules:

- feature issue -> `python scripts/linear_issue.py followup-pr --issue-id {{ issue.identifier }} --create-missing-labels`
- PR issue + `release-required` -> `python scripts/linear_issue.py followup-release --issue-id {{ issue.identifier }} --create-missing-labels`
- release issue -> no further follow-up

Hard rules:

- do not create follow-up issues before the current issue is truly complete;
- do not publish new releases from the review lane;
- do not widen scope beyond the current stage contract.
