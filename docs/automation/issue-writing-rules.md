# Issue Writing Rules

These rules exist to keep agent work bounded and to avoid accidental cross-repo scope creep.

## 1. State the ownership boundary

Every issue must say which repository owns the work.

Required wording pattern:

- `Owned by: <repo>`
- `Out of scope without a separate issue: <other repos / systems>`

If the issue belongs to `yandex.ad`, do not imply that agents should edit `Marketing2025` unless that is explicitly approved.

## 2. Separate producer work from consumer adoption

When one repo produces a capability for another repo:

- producer issue: implement the capability, validate the exposed contract, write handoff;
- consumer issue: adopt the capability in the client workflow.

Do not combine both by default.

## 3. Make client handoff explicit

If a downstream client depends on the result, the issue must say whether completion requires:

- direct client-repo edits, or
- a handoff/release-note style document only.

If the latter, make the handoff a required deliverable.

## 4. Distinguish compatibility from migration

Use one of these exact phrases:

- `Compatibility task`: keep the current client format if feasible; document differences if not.
- `Migration task`: update the client workflow itself.

If neither phrase appears, the task is underspecified.

## 5. Acceptance criteria must match the repo boundary

Do not put cross-repo file edits into acceptance criteria unless the issue explicitly owns that second repo too.

Good:

- `client handoff document written in this repo`
- `server output covers required client fields`

Bad:

- `update client prompt/script` in a server-only issue

## 6. Validation must be executable by the owning repo

Validation should be written per stage:

- `Feature Validation`
- `PR Validation`
- `Release Validation`

Do not put one mixed validation list into a multi-stage issue chain.

The current stage should only be judged against its own validation section.

Validation should default to what the owning repo can prove directly:

- tests;
- contract checks;
- live bounded API validation;
- fixture or manual comparison;
- handoff doc review.

Cross-repo end-to-end runs should be separate unless explicitly in scope.

## 6a. Add issue class and risk explicitly

Every Symphony-managed issue should declare:

- `Issue Class`: `bug` / `feature` / `investigation` / `release`
- `Risk`: `low` / `medium` / `high`

These fields determine how strong the current stage validation should be.

Examples:

- `bug` + `low` -> targeted tests are often enough
- `feature` + `medium` -> targeted/full tests plus schema/docs alignment
- `feature` + `high` -> bounded live smoke may be required if the feature integrates with a real provider
- `release` + `high` -> full release validation is mandatory

## 6b. Declare required capabilities and secret dependencies

Every Symphony-managed issue should declare:

- `Required Capabilities`
- `External Inputs / Secrets`
- `Blocked Input Policy`

`Required Capabilities` must explicitly answer:

- browser: `none` / `playwright` / `chrome-devtools` / `operator-browser`
- live-api: `yes/no`
- manual-check: `yes/no`
- operator step required: `yes/no`

`External Inputs / Secrets` must explicitly answer:

- required env vars
- source of truth
- whether the Symphony parent process must already export them before the issue moves to `Todo`

`Blocked Input Policy` must explicitly answer:

- which missing inputs should move the issue to `Backlog`
- which failures should return the issue to `Todo`

This prevents hidden assumptions about browser access, live provider access, and manual operator evidence.

## 6c. Make stage handoff mandatory

Every Symphony-managed issue must be able to move between stages only through a standard handoff artifact set.

Required rule:

- no state transition without a valid `SYMPHONY_HANDOFF.json`

When the stage produces code or metadata that a later stage must continue from a fresh clone, the issue must also require:

- feature stage: `SYMPHONY_STAGE_HANDOFF.md` and `SYMPHONY_STAGE_PATCH.diff`
- PR stage: `SYMPHONY_STAGE_HANDOFF.md`
- release stage: stage-complete `SYMPHONY_HANDOFF.json`
- follow-up issues generated from a previous stage should include a machine-readable `Symphony Preflight Metadata` block in the issue body

The issue body should make the cycle contract explicit:

- `Retry Budget`: default `3` unless stated otherwise
- `Handoff Required`: `yes`

This prevents silent state flips, missing review context, and infinite loops after partial work.

If a feature issue is reopened after a PR or release follow-up was already generated, those generated follow-up issues must be deleted before the next implementation cycle starts. Do not reuse stale follow-up issues across feature-stage retries.

If browser-visible or operator evidence is allowed, the issue should also state which evidence channels are acceptable:

- agent-owned browser artifact
- repo-local validation note
- Linear issue comment with explicit validation summary

## 7. Runtime payload and published schema must match

If an issue adds or changes a tool response:

- runtime payload;
- tool contract schema;
- snapshots;
- docs

must describe the same shape.

## 7a. Keep stage-owned docs explicit

By default:

- feature stage owns runtime code, tests, and stage handoff artifacts;
- PR stage owns repo-facing docs alignment needed for merge review;
- release stage owns release notes, versioning, tags, and published artifact notes.

Do not require `README.md`, `CHANGELOG.md`, cross-language docs, or client-facing handoff files in `Feature Validation` unless the feature is specifically about documentation or the runtime contract would be unverifiable without that exact file update.

## 8. Release is not the default end state for feature issues

By default:

- feature issue -> PR readiness / PR publication;
- release issue -> version/tag/GitHub Release/Docker publish.

Do not require image publication in a normal feature issue unless it is explicitly a release task.

## 8a. Release-required feature issues must say so explicitly

If a feature is not useful until the client can pull a published image, mark it as a release-required feature.

Required machine-readable signal:

- Linear label: `release-required`

Required wording in the issue:

- `Release Required: yes`

Process:

- implementation
- review
- PR publication
- release follow-up issue
- GitHub Release and Docker publish

Do not rely on implied release expectations.

If `Feature Validation` requires live provider validation, the operator must ensure the Symphony parent process already exports the required credentials from the external state store before moving the issue to `Todo`.

If `Feature Validation` requires browser-visible comparison, the issue must also state which browser mode is allowed and whether the agent or the operator owns that step.

For browser-visible checks, prefer `chrome-devtools` or `playwright` when the intent is autonomous agent execution. Use `operator-browser` only when the team explicitly accepts a human evidence step.

## 9. Use these required sections in issue drafts

Every agent-facing issue should include:

- `Execution Profile`
- `Ownership Boundary`
- `Required Capabilities`
- `External Inputs / Secrets`
- `Blocked Input Policy`
- `Goal`
- `Scope`
- `Non-goals`
- `Acceptance Criteria`
- `Feature Validation`
- `PR Validation`
- `Release Validation`
- `Handoff` or `Notes`

## 11. Add machine-readable routing labels

For new Symphony-managed issues, set:

- `symphony`
- `issue-type:feature`

Add these only when needed:

- `release-required`
- domain labels such as `search-api`, `wordstat`, `dashboard`

PR and release issues are follow-up issues generated by the harness and should carry:

- `issue-type:pr`
- `issue-type:release`
- `generated-followup`

They should also depend on stage handoff artifacts generated by the previous stage:

- feature stage must end with `SYMPHONY_WORK_RESULT.md`, `SYMPHONY_STAGE_HANDOFF.md`, and `SYMPHONY_STAGE_PATCH.diff`
- PR stage must end with `SYMPHONY_WORK_RESULT.md` and `SYMPHONY_STAGE_HANDOFF.md` that records branch, commit SHA, and PR URL

## 10. When scope is ambiguous, prefer a smaller issue

If the task can be read in two ways:

- server capability only;
- server capability plus client adoption;

default to the smaller producer-side issue and add a follow-up consumer issue if needed.
