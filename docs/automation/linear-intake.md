# Linear Intake Harness

This repo uses Linear as the work queue for Symphony-driven agent tasks. The intake harness lets Codex turn a local draft or prompt into a structured Linear issue without manual copy/paste.

## Safety Model

- `LINEAR_API_KEY` is read from the environment only.
- The default target state is `Backlog`, so Symphony will not run the task until a human moves it to `Todo`.
- The default dispatch label is `symphony`.
- New feature issues should also carry `issue-type:feature`.
- The script never reads Yandex credentials.
- Use `--dry-run` before `create` when shaping a new task.
- Validation must be written per stage:
  - `Feature Validation`
  - `PR Validation`
  - `Release Validation`

## Local Config

Keep local Linear routing outside this repo:

```json
{
  "teamId": "3460d8b7-42f7-498a-8917-784237f318ff",
  "projectId": "aadd4324-b828-4dd8-a0ca-eebd65b16683",
  "defaultState": "Backlog",
  "defaultLabels": ["symphony", "issue-type:feature"]
}
```

Recommended path:

```bash
/path/to/Symphony_yaad/linear.yandexad.json
```

## Available Drafts

- generic feature: `docs/automation/templates/linear-feature.md`
- generic bug: `docs/automation/templates/linear-bug.md`
- generic investigation: `docs/automation/templates/linear-investigation.md`
- generic release: `docs/automation/templates/linear-release.md`
- Marketing2025 workflow: `docs/automation/templates/linear-marketing2025-workflow.md`
- universal handoff shape: `docs/automation/templates/SYMPHONY_HANDOFF.template.json`

## Required Intake Fields

Every Symphony-managed issue should explicitly define:

- `Issue Class`
- `Risk`
- `Ownership Boundary`
- `Required Capabilities`
- `External Inputs / Secrets`
- `Blocked Input Policy`
- `Acceptance Criteria`
- `Feature Validation`
- `PR Validation`
- `Release Validation`
- `Cycle Policy`

Rule:

- implementation lane executes only the current stage validation;
- review lane verifies only the current stage validation;
- later-stage validation must not be used to reject an earlier stage.
- if a required capability or external input is missing, the issue must move to `Backlog`, not loop in `Todo`.
- unless explicitly required in `Feature Validation`, repo-wide docs, changelog, PR copy, release notes, and downstream handoff documents belong to PR/release follow-up stages rather than the feature stage.
- every cross-agent transition must emit `SYMPHONY_HANDOFF.json` using the repo template shape.
- `Cycle Policy` should define the retry budget, or the workflow default of `max_iterations = 3` will apply.
- once `cycle.max_iterations` is exhausted, review must stop the loop and move the issue to `Backlog` with an explicit blocker handoff.

`Required Capabilities` should explicitly answer:

- browser: `none` / `playwright` / `chrome-devtools` / `operator-browser`
- live-api: `yes/no`
- manual-check: `yes/no`
- operator step required: `yes/no`

Default browser guidance:

- use `chrome-devtools` when the agent should inspect a human-visible Chrome session;
- use `playwright` for deterministic agent-owned browser runs;
- use `operator-browser` only when a human evidence step is intentionally accepted.

`External Inputs / Secrets` should explicitly answer:

- which env vars are required
- where they are sourced from
- whether they are expected in the parent Symphony process before the issue moves to `Todo`

If manual/operator evidence is allowed, also state whether an existing Linear comment or repo-local evidence note can satisfy that requirement on a later retry.

## Create From A Draft

```bash
set -a
. /path/to/Symphony_yaad/.env
set +a

python scripts/linear_issue.py preview \
  --config /path/to/Symphony_yaad/linear.yandexad.json \
  --from docs/wordstat-search-api-hardening-issue-2026-06-19.md \
  --title "Harden Wordstat Search API regions and associations handling" \
  --labels symphony,wordstat

python scripts/linear_issue.py create \
  --config /path/to/Symphony_yaad/linear.yandexad.json \
  --from docs/wordstat-search-api-hardening-issue-2026-06-19.md \
  --title "Harden Wordstat Search API regions and associations handling" \
  --labels symphony,issue-type:feature,wordstat
```

Move the issue to `Todo` only when it is approved for Symphony execution.

## Update An Existing Issue

```bash
set -a
. /path/to/Symphony_yaad/.env
set +a

python scripts/linear_issue.py update \
  --config /path/to/Symphony_yaad/linear.yandexad.json \
  --issue-id GEO-7 \
  --from docs/yandex-search-api-web-tools-issue-2026-06-20.md \
  --title "Add search_serp MCP tool and migrate gap-overlay-report SERP flow off Playwright"
```

Use the shorthand issue identifier, for example `GEO-7`, when replacing the title and description of an existing task.

## Create Follow-up Issues

Use follow-up issue creation after the previous stage is genuinely complete.

PR follow-up from a feature issue:

```bash
set -a
. /path/to/Symphony_yaad/.env
set +a

python scripts/linear_issue.py followup-pr \
  --config /path/to/Symphony_yaad/linear.yandexad.json \
  --issue-id GEO-7 \
  --create-missing-labels
```

Release follow-up from a PR issue:

```bash
set -a
. /path/to/Symphony_yaad/.env
set +a

python scripts/linear_issue.py followup-release \
  --config /path/to/Symphony_yaad/linear.yandexad.json \
  --issue-id GEO-8 \
  --create-missing-labels
```

Both commands:

- create the next-stage issue in the same team and project;
- inherit context labels;
- replace the previous `issue-type:*` label with the new stage label;
- include the deterministic source workspace path for the previous stage;
- include a machine-readable `Symphony Preflight Metadata` block so the follow-up stage can fail fast without reparsing the whole issue body;
- require portable handoff artifacts from the previous stage:
  - feature -> PR: `SYMPHONY_WORK_RESULT.md`, `SYMPHONY_STAGE_HANDOFF.md`, `SYMPHONY_STAGE_PATCH.diff`
  - PR -> release: `SYMPHONY_WORK_RESULT.md`, `SYMPHONY_STAGE_HANDOFF.md`
- fail closed for PR -> release unless the PR-stage handoff explicitly records `merge status: merged` and a merge commit SHA
- comment the created follow-up link back onto the source issue.

Do not create a follow-up issue until those artifacts exist in the source workspace.

## Comment On An Issue

```bash
set -a
. /path/to/Symphony_yaad/.env
set +a

python scripts/linear_issue.py comment \
  --config /path/to/Symphony_yaad/linear.yandexad.json \
  --issue-id GEO-7 \
  --body "Review findings: returning to Todo."
```

## Move An Issue Between States

```bash
set -a
. /path/to/Symphony_yaad/.env
set +a

python scripts/linear_issue.py state \
  --config /path/to/Symphony_yaad/linear.yandexad.json \
  --issue-id GEO-7 \
  --state Todo
```
