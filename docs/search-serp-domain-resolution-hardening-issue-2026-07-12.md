# Harden `search_serp` Ad Domain Resolution Against Confident-Wrong Domains

Suggested labels:

- `symphony`
- `issue-type:feature`
- `bug`
- `search-api`

## Execution Profile

- Issue Class: bug
- Risk: medium
- Retry Budget: 3
- Handoff Required: yes

## Ownership Boundary

- Owned by: `yandex.ad`
- Out of scope without a separate issue:
  - `Marketing2025`
  - client-side aggregation or filtering logic
  - Symphony automation hardening

## Required Capabilities

- browser: none
- live-api: no for mandatory validation
- manual-check: no
- operator step required: no

## Background

Post-release validation against real SERP queries found that the latest `search_serp` implementation
closed only part of the previous defect set:

- `native` ad type is now confirmed;
- `product_gallery` still exposes one arbitrary merchant domain instead of `null`;
- `yabs` residuals are reduced but still present on some queries;
- a new, more dangerous bug appeared: one ad resolved to `domain="dr.head"` even though the visible host
  in the snippet was `doctorhead.ru`.

This new failure mode is worse than an unresolved redirect:

- `yabs.yandex.ru` can be filtered as unresolved;
- `product_gallery` can be ignored by `type`;
- `dr.head` looks like a plausible domain and can leak into downstream competitor sets as false data.

## Root Cause

Current HTML ad normalization in `src/mcp_yandex_ad/search_client.py` has two structural weaknesses:

1. **Wrong precedence**  
   The resolver currently prefers:
   - `_domain_from_visible_text(block.text)`
   - then `_domain_from_url(landing_url)`
   - then `_domain_from_url(href)`

   This means a brand-like token from snippet text can win over a real parsed landing host.

2. **Weak visible-text validation**  
   `_domain_from_visible_text()` accepts the first `x.y`-looking token that:
   - is not numeric-only after the dot;
   - is not a Yandex ad host.

   It does **not** validate that the suffix is a real public suffix / registrable domain, so strings like
   `Dr.Head` become `dr.head`.

## Goal

Make ad domain resolution conservative and deterministic:

- prefer structured URL-derived hosts over free-text scraping;
- never emit a confident-wrong domain when the extracted token is not a valid registrable host;
- return `null` / unresolved instead of fabricated domains.

## Scope

1. Change HTML ad domain precedence to:
   - parsed visible display host, if structurally present;
   - resolved landing URL host from redirect;
   - direct `href` host, if it is not a Yandex ad redirect host;
   - visible-text scraping only as a last resort.

2. Harden visible-text scraping:
   - validate candidate domains against a real public suffix / registrable-domain rule;
   - reject fake suffixes such as `dr.head`;
   - reject brand-like dotted tokens that are not valid hosts.

3. Make unresolved behavior explicit:
   - if no validated domain can be derived, do not fall back to a plausible-looking but unvalidated token;
   - choose and implement one explicit contract-safe behavior for unresolved ads:
     - either allow `domain = null` and update the `search_serp` output contract accordingly;
     - or keep unresolved ads out of `ad_competitors`-relevant output without emitting a fabricated domain string.

4. Tighten `product_gallery` handling:
   - stop emitting one arbitrary merchant domain from gallery cards as the ad domain;
   - if the chosen unresolved contract is `null`, use `domain = null`;
   - otherwise use the same explicit unresolved behavior selected in scope item 3.

5. Add regression fixtures and tests covering:
   - `doctorhead.ru` visible in snippet with branded `Dr.Head` text nearby;
   - residual Yandex redirect cases that must remain unresolved rather than leak `yabs.yandex.ru`;
   - `product_gallery` with merchant cards;
   - a valid `native` example.

## Non-goals

- redesigning all SERP normalization;
- changing downstream `Marketing2025` filters;
- implementing new search modes;
- live API validation in CI.

## Acceptance Criteria

1. A fixture reproduces the `doctorhead.ru` / `Dr.Head` pattern and the normalized ad domain is
   `doctorhead.ru`, never `dr.head`.

2. No visible-text candidate that fails registrable-domain validation is emitted as `domain`.

3. Residual Yandex redirect hosts (`yabs.yandex.ru`, `an.yandex.ru`) are never emitted as resolved ad
   domains when the real advertiser domain cannot be validated.

4. `product_gallery` rows no longer emit one arbitrary merchant domain as the ad domain; they follow the
   explicit unresolved-domain contract chosen in scope item 3 unless a validated advertiser domain is
   available.

5. `native` ad typing remains intact.

6. The output contract is internally consistent:
   - if unresolved ads now use `domain = null`, the `search_serp` output schema and server-side validation
     are updated accordingly;
   - if unresolved ads remain string-only, the implementation still prevents `dr.head`-style fabricated
     domains from being emitted.

7. Validation is fixture-based and deterministic; it does not depend on live SERP drift.

## Validation

- `.venv/bin/python -m pytest -q tests/test_search_serp.py`
- add focused fixture assertions for:
  - `doctorhead.ru` vs `dr.head`
  - unresolved `yabs`
  - `product_gallery` -> `null`
  - `native` preserved

## Handoff

- update release notes / session note to state that:
  - confident-wrong dotted brand tokens are blocked;
  - unresolved redirect counts may remain non-zero, but false competitor domains are no longer emitted.
