# Symphony Pipeline

Date: 2026-06-27

This repository uses:

- `Linear` as the visible work queue;
- `Symphony` as the execution harness;
- `Codex` as the implementation and review agent inside each Symphony lane.

The pipeline now uses **two active lanes** and **follow-up issues**.

We do not depend on custom Linear states such as `Approved` or `Releasing`.

## Active Lanes

1. `implementation`
2. `review`

Both lanes watch the normal Linear state loop:

- `Todo`
- `In Progress`
- `In Review`
- `Done`

State transitions must not be performed ad hoc from lane prose. The active workflows now route state changes through repo-local guarded helpers:

- `scripts/linear_state.py` for explicit lane-owned state moves
- `scripts/stage.py` for stage exit commands that both write handoff artifacts and invoke the guarded state mover

## Issue Types

Every Symphony-managed issue should carry one of these labels:

- `issue-type:feature`
- `issue-type:pr`
- `issue-type:release`

Common labels:

- `symphony`
- domain labels such as `search-api`, `wordstat`, `dashboard`

Optional routing labels:

- `release-required`
- `generated-followup`

If an old issue has no `issue-type:*` label, treat it as `issue-type:feature`.

## Validation Model

Every Symphony-managed issue should define validation per stage:

- `Feature Validation`
- `PR Validation`
- `Release Validation`

Rule:

- implementation executes only the current stage validation;
- review verifies only the current stage validation;
- later-stage validation must not be used to reject an earlier stage.

Also define:

- `Issue Class`
- `Risk`

These fields explain how strong the current stage validation should be.

## Blocked Input Policy

If a stage cannot complete because of missing external credentials, missing operator input, or required manual validation that is impossible in the current environment:

- do not keep the issue in the active `Todo` / `In Progress` loop;
- leave one concise blocker comment;
- move the issue to `Backlog`;
- resume only after the missing input is restored and the operator moves the issue back to `Todo`.

## End-to-End Flow

### 1. Feature issue

Path:

- `Backlog` -> `Todo` -> `In Progress` -> `In Review` -> `Done`

Behavior:

- implementation lane performs the code change, tests, docs, and handoff;
- implementation moves `Todo -> In Progress` through `scripts/linear_state.py`, and stage exits flow through `scripts/stage.py` plus the same guarded state mover;
- review lane verifies the work;
- when review passes, the review lane moves the feature issue to `Done` and auto-creates a PR follow-up issue in `Todo`.

### 2. PR issue

Path:

- `Todo` -> `In Progress` -> `In Review` -> `Done`

Behavior:

- implementation lane re-runs non-live gates, commits, pushes, and creates or updates the GitHub PR;
- implementation still reaches `In Progress` and `In Review` only through the guarded state path;
- if the PR issue carries `release-required`, the PR stage is not complete until the PR is publishable and merged;
- PR and release follow-up issues should start with a deterministic preflight command that validates source metadata before broader agent work;
- review lane verifies the PR stage artifacts;
- when review passes:
  - if the source chain does not need release publication, the PR issue ends at `Done`;
  - if the chain carries `release-required`, the review lane moves the PR issue to `Done` and auto-creates a release follow-up issue in `Todo`.

### 3. Release issue

Path:

- `Todo` -> `In Progress` -> `In Review` -> `Done`

Behavior:

- implementation lane performs the release stage: full gates, live validation, tags, GitHub Release, Docker publish verification, local Docker alias refresh;
- release-stage state moves still flow through the same guarded state path;
- release preflight must fail closed unless the environment already provides `GHCR_READ_TOKEN` with `read:packages` for the private PRO image pull;
- review lane verifies the release artifacts and closes the issue.

## Why this model

This model fits the current Linear team workflow because the available states are:

- `Backlog`
- `Todo`
- `In Progress`
- `In Review`
- `Done`
- `Canceled`
- `Duplicate`

It also keeps each issue single-purpose:

- feature implementation
- PR publication
- release publication

## Follow-up Issue Creation

The harness command is:

```bash
python scripts/linear_issue.py followup-pr --issue-id GEO-7 --create-missing-labels
python scripts/linear_issue.py followup-release --issue-id GEO-8 --create-missing-labels
```

Behavior:

- `followup-pr` creates a PR issue in the same team and project as the source issue;
- `followup-release` creates a release issue in the same team and project as the source issue;
- `followup-release` must fail closed unless the source PR-stage handoff explicitly records `merge status: merged` and a merge commit SHA;
- before a follow-up is created or resynced, the source workspace must pass the stage handoff verifier for its stage;
- if a generated follow-up for the same source issue and stage already exists, Symphony must fully resync its title, description, labels, and state from the current source-stage contract instead of partially reusing stale content;
- if the source handoff is invalid, Symphony must stop and fix the source stage instead of creating or refreshing a broken follow-up;
- the new issue inherits context labels, replaces the old `issue-type:*` label, and adds:
  - `generated-followup`
  - `issue-type:pr` or `issue-type:release`
- the source issue gets an automatic Linear comment with the created follow-up link.

## Release Required

`release-required` means:

- the feature is not operationally complete for the client until a published image exists;
- the feature issue still ends at `Done`;
- the PR follow-up still happens first;
- the release follow-up is created only after the PR issue passes review.

It does **not** mean “keep the same issue open until release”.

## Stage Responsibilities

### Implementation lane

- `issue-type:feature`
  - code, tests, docs, handoff
  - no push, no tags, no release
- `issue-type:pr`
  - non-live gates
  - commit, push, PR creation/update
  - no tags, no release
- `issue-type:release`
  - full gates
  - live validation
  - release tags
  - GitHub Release
  - Docker verification
  - local Docker alias refresh

### Review lane

- verify the stage result for the current issue type;
- return to `Todo` on findings;
- move to `Done` on approval;
- create the next follow-up issue when the current stage requires it.

## What the user does

1. Create or refine the initial feature issue in Codex.
2. Keep it in `Backlog` until ready.
3. Move it to `Todo`.
4. Keep the two Symphony lanes running.
5. Watch Linear:
   - feature issue
   - PR follow-up
   - release follow-up when needed

The user does not need to manually create PR and release issues if the harness is working.
