# Search SERP And Release Follow-up Hardening

Date: 2026-07-12

## Completed

- Added an automation hardening issue draft for release follow-up creation:
  - `docs/automation/symphony-release-followup-hardening-issue-2026-07-12.md`
- Added a product hardening issue draft for `search_serp` ad-domain normalization:
  - `docs/search-serp-domain-resolution-hardening-issue-2026-07-12.md`
- Updated `docs/automation/symphony-pipeline.md` with a stricter rule for parser / normalizer work:
  - fixture-based validation is mandatory;
  - adversarial acceptance is mandatory for plausible-but-wrong outputs;
  - unresolved output is preferred over fabricated confident-looking data.
- Refined the `search_serp` hardening draft to account for the current contract:
  - `domain` is currently a required string in the output schema;
  - the future fix must either update the schema to allow `null` or choose another explicit unresolved-domain behavior.

## To Do

- Move the `search_serp` domain-resolution hardening draft into Linear as the next product issue.
- Move the release follow-up hardening draft into Linear as the next automation issue after the current release evidence work.
- For the `search_serp` fix, decide explicitly whether unresolved ads should:
  - allow `domain = null` with a schema update;
  - or stay string-only while preventing fabricated domains from being emitted.
