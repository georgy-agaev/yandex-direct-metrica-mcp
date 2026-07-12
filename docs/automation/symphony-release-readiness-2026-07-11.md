# Symphony Release Readiness

Date: 2026-07-11

This document defines when the `yandex.ad` Symphony pipeline is ready for:

1. real non-release work;
2. real `release-required` work.

It exists because one green happy-path release smoke is not enough to claim that the full release chain is production-ready.

## Current Position

As of 2026-07-12 after the `GEO-38 -> GEO-39 -> GEO-40` smoke chain:

- `feature -> PR -> review` is considered usable for real bounded tasks;
- the happy-path `release-required` chain is now proven once, end to end;
- `release-required` is still under active validation because failure routing and repeatability are not yet proven;
- release readiness must be proven by evidence, not inferred from one successful pass.

Observed happy-path evidence for `v2.0.15`:

- feature issue `GEO-38`: completed and handed off to PR;
- PR issue `GEO-39`: merged as GitHub PR `#16`;
- release issue `GEO-40`: completed;
- GitHub Release published: `v2.0.15`;
- Docker publish verified:
  - public workflow success;
  - pro workflow success;
- local Docker aliases refreshed:
  - `yandex-direct-metrica-mcp:latest`
  - `yandex-direct-metrica-mcp-pro:latest`

## Validation Concurrency Profile

All readiness evidence below is scoped to a stated concurrency profile and is invalidated if that profile changes:

- number of Symphony lanes (currently two: implementation + review);
- `agent.max_concurrent_agents` per lane (currently `1`);
- number of `symphony`-labelled issues eligible at the same time during the smoke.

The original source-reopen bug was a concurrency artifact, so evidence gathered under strictly sequential, single-issue conditions does NOT cover parallel-issue operation. Record the profile used for each level. If the profile is later widened (more parallel issues, higher concurrency), the reopen evidence must be regathered.

## Readiness Levels

### Level A: Real non-release issues allowed

Minimum evidence:

1. feature issue completes;
2. PR follow-up is generated automatically;
3. PR issue publishes a real branch and GitHub PR;
4. review closes the PR issue cleanly;
5. no manual copy/paste or manual follow-up issue creation is required.

Decision:

- real non-release feature work: allowed
- real `release-required` work: not yet allowed

### Level B: Happy-path release chain proven

Minimum evidence:

1. feature issue marked `release-required` completes;
2. PR follow-up is generated automatically;
3. PR issue merges successfully;
4. release follow-up is generated automatically;
5. release issue completes:
   - version bump
   - `CHANGELOG.md`
   - release notes at the path the release runner actually writes (confirm it; do not assume `docs/releases/vX.Y.Z.md`)
   - GitHub Release
   - Docker publish verification
   - local Docker alias refresh

Note:

- during the validation phase, decide consciously whether smoke PRs auto-merge or require a human merge; auto-merging a real PR to `main` unattended is an outward-facing action.

Decision:

- proves the green path only
- does not yet prove failure handling or retry safety

Status on 2026-07-12:

- satisfied once under the current concurrency profile (`implementation + review`, `max_concurrent_agents=1`, one release-required chain in flight)
- evidence chain: `GEO-38 -> GEO-39 -> GEO-40 -> v2.0.15`

### Level C: Release failure path proven

GEO-17 showed release failures cluster at different late steps that route differently under the Blocked Input Policy. One injected failure only proves one routing branch. Level C therefore requires at least TWO injections covering both branches:

- **gate / validation failure** (e.g. forced `release_guard` or test failure) -> must route to `Todo`/`Backlog` as a code-defect per the issue contract;
- **infra / credential failure** (e.g. missing `GHCR_READ_TOKEN` or bounded publish-verification failure) -> must route to an operator blocker in `Backlog`.

Minimum evidence, for EACH of the two injections:

1. intentionally trigger the bounded failure;
2. the release issue stops through the expected guarded path;
3. the issue ends in the **correct** target state for that failure class (not merely "stopped");
4. blocker/handoff is explicit and actionable;
5. source feature/PR issues do not reopen;
6. no uncontrolled loop or duplicate follow-up issue is created.

Decision:

- release chain now has evidence that both distinct failure branches route correctly, not just that a single failure halts

### Level D: Repeatability proven

Minimum evidence:

1. two or three consecutive chains complete without source reopen, under the recorded concurrency profile;
2. at least one check runs with two eligible issues queued at the same time (not only strictly sequential), since the reopen bug was a concurrency artifact;
3. stale follow-up reuse: either the follow-up-drift hardening issue is implemented, OR it is explicitly recorded here as untested with the risk accepted (Level D cannot be silently green without this decision);
4. token usage remains within an acceptable range for the same class of task;
5. retry/resume behavior is understood:
   - either proven idempotent by smoke,
   - or explicitly documented as still unsupported (see Operational Rule for the constraint this imposes).

Decision:

- real `release-required` work can be treated as operationally ready, but only within the recorded concurrency profile

## Mandatory Release Readiness Checklist

Before declaring the release chain ready for real `release-required` issues, all items below must be true:

- [ ] concurrency profile for this validation is recorded (lanes, `max_concurrent_agents`, parallel-issue count)
- [ ] one happy-path `release-required` smoke completed end to end
- [ ] two intentional release failure-path injections completed, one per routing branch (gate-failure and credential/infra-failure), each ending in the correct target state
- [ ] no source reopen on 2-3 consecutive chains
- [ ] at least one reopen check run with two issues eligible at the same time
- [ ] release follow-up auto-creation is proven after merged PR review
- [ ] publish artifacts are verified:
  - [ ] GitHub Release
  - [ ] public Docker
  - [ ] pro Docker
  - [ ] local Docker `latest` aliases
- [ ] stale follow-up drift is either hardened or explicitly recorded as untested with risk accepted
- [ ] retry/resume behavior is either proven idempotent or explicitly marked not yet guaranteed
- [ ] token profile is measured and accepted

## Operational Rule

Do not promote Symphony to “release-ready” for real `release-required` issues until the checklist above is fully green.

Use the narrower truth instead:

- “non-release work is ready”
- “release work is still under validation”

### Constraint while retry/resume is unproven

If retry/resume is marked "not yet guaranteed", real `release-required` issues run **one at a time, under observation, with no unattended retries** until idempotency is proven. Otherwise a mid-chain failure can re-run full validation and thrash, exactly the GEO-17 failure mode.

### Circuit breaker

If, during real operation, any of the following is observed, immediately revert Symphony to "release work under validation" and stop the lanes:

- a source issue reopens after approval;
- an uncontrolled retry loop;
- a duplicate follow-up issue.

## Next Recommended Steps

1. run the dedicated release failure-path smoke with two injections (gate-failure and credential/infra-failure);
2. repeat two or three full chains to check for reopen regression, including one with two issues eligible at once;
3. decide whether the additional `source-state-consistency` hardening issue is still required after the repeatability evidence is in;
4. only then treat real `release-required` work as operationally ready.
