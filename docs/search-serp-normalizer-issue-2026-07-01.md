# Issue Draft: Normalize `search_serp` ad domains and SERP ad block types

## Execution Profile

- Issue Class: bug
- Risk: high

## Title

Normalize `search_serp` advertiser domains, classify ad block types, and expose top/bottom ad placement signals

## Type

Bug fix / contract hardening / release-required integration

## Release Required

yes

## Suggested Labels

- `symphony`
- `issue-type:feature`
- `release-required`
- `search-api`
- `web-search`
- `marketing2025`
- `bug`
- `next-release`

## Ownership Boundary

Owned by: `yandex.ad`

Out of scope without a separate issue:

- `Marketing2025`
- downstream client prompt/script/workflow edits
- changing consumer-side artifact formats in-place

Allowed:

- MCP runtime changes in this repo
- parser/normalizer changes in this repo
- tests, snapshots, stage handoff artifacts, docs, release notes, and handoff docs in this repo
- bounded live validation proving the MCP output now matches the consumer need

Compatibility task:

- keep the current client-side output expectations feasible where possible;
- if the MCP response shape changes, document the delta in a handoff/release-note style document in this repo;
- do not edit `Marketing2025` files in this issue.

## Required Capabilities

- browser: `none`
- live-api: yes
- manual-check: no
- operator step required: no

Evidence channels accepted for this issue:

- agent-owned live API evidence
- repo-local validation note under `docs/` or `docs/sessions/`

## External Inputs / Secrets

- required env:
  - `YANDEX_SEARCH_API_FOLDER_ID`
  - `YANDEX_SEARCH_API_API_KEY` or `YANDEX_SEARCH_API_IAM_TOKEN`
- source of truth:
  - external state file, for example `<state-root>/yandex.ad/.env`
- expected in the parent Symphony process before the issue moves to `Todo`: yes

## Blocked Input Policy

- move to `Backlog` if:
  - Search API credentials are unavailable in the parent Symphony process and cannot be sourced from the approved external state file
  - bounded live validation against the three control queries cannot run
- return to `Todo` only for:
  - code defects
  - failing tests
  - parser/contract/docs drift
  - missing repo-local artifacts that the agent can generate in this repo

## Background

`search_serp` shipped in `v2.0.13` and is already good enough for:

- basic ad bucket extraction
- organic result extraction
- captcha detection
- region/device control

But `Marketing2025` validated the released tool on three live RU desktop queries and found that the ad normalizer still does not provide a usable advertiser domain contract.

Current defect:

- `ads[].domain` is often the Yandex redirect host such as `yabs.yandex.ru`, not the real advertiser domain

This blocks two downstream metrics:

- `ad_competitors`
- `our_ad_present`

Secondary issues:

- product galleries and native ad blocks are mixed into `ads[]` without type information
- top/bottom ad placement is not fully represented beyond `ads_count_top`

The consumer already provided concrete live examples and expected advertiser domains. This issue should use that evidence and make the MCP response deterministic enough for the downstream migration.

## Goal

Fix the `search_serp` HTML normalizer so that:

1. `ads[].domain` contains the advertiser domain, not the Yandex redirect host;
2. `ads[]` exposes block type classification;
3. the response exposes enough top/bottom placement information for downstream slot metrics;
4. tests and runtime contracts describe the updated contract;
5. the result ships in a published release.

## Scope

### 1. Resolve advertiser domains in `ads[].domain`

Current behavior derives `ads[].domain` from the click URL, which is often a Yandex redirect such as `yabs.yandex.ru`.

Implement:

- resolve the advertiser domain from the visible display URL in the ad block when available;
- keep a separate redirect field, preferably `click_url`, for the Yandex redirect target;
- normalize advertiser domains to lowercase and remove `www.`;
- keep `url` behavior explicit in docs:
  - either preserve `url` as the effective landing URL if available, or
  - document that `click_url` is the redirect and `domain` is the resolved advertiser host

Preferred extraction order:

1. visible display URL / visible advertiser host in the HTML block
2. fallback extraction from the redirect target if the display URL is absent

### 2. Classify ad block type

Add `ads[].type` with values:

- `text`
- `product_gallery`
- `native`

Required classification behavior:

- ordinary Direct text ads -> `text`
- “Популярные товары …” / product carousel blocks -> `product_gallery`
- `an.yandex.ru` / “Может заинтересовать” style native blocks -> `native`

These blocks may remain in `ads[]`, but they must no longer be indistinguishable from a normal text ad.

### 3. Expose top/bottom placement

Add:

- `ads[].block ∈ {top, bottom}` for ad items where the block can be determined
- `ads_count_bottom`

`ads_count_top` and `ads_count_bottom` must count only `type = text`.

### 4. Keep organic results unchanged

Do not regress `organic[]`.

Organic domain/title/url extraction is already acceptable and should remain stable.

### 5. Update tests and runtime contracts in the feature stage

Update:

- parser tests
- tool contract snapshots
- public tool/runtime snapshots needed to prove the feature-stage contract

The later PR/release stages must explicitly mention:

- `domain` is now the advertiser domain for ads
- `click_url` contains the redirect when retained
- `type` must be used to filter non-text blocks
- `block` / `ads_count_bottom` can be used for slot analysis

## Non-goals

- no edits in `Marketing2025`
- no new browser-based client workflow work
- no XML ad parsing expansion
- no unrelated Search API tools
- no broad Search API product redesign outside this normalizer contract

## Acceptance Criteria

- For the three control queries below, text ads no longer expose `yabs.yandex.ru`, `an.yandex.ru`, or bare `yandex.ru` in `ads[].domain` unless the advertiser is genuinely a Yandex property such as `direct.yandex.ru`.
- Query 1 `гарнитура для колл центра купить` includes text-ad domains such as `pult.ru`, `beeline.ru`, `doctorhead.ru`, and `srv-trade.ru`.
- Query 2 `спикерфон для переговорной купить` includes `voicexpert.ru` in `ads[].domain` for `type = text`.
- Query 3 `муфта термоусаживаемая 10 кв купить` includes text-ad domains such as `vseinstrumenti.ru`, `tdteplolit.ru`, and `mufta.ru`.
- Every `ads[]` item has `type ∈ {text, product_gallery, native}`.
- Product gallery blocks are marked `product_gallery`.
- Native recommendation blocks are marked `native`.
- True text ads are marked `text`.
- The response exposes top/bottom separation through `ads[].block` and `ads_count_bottom`.
- `ads_count_top` counts only `type = text`.
- Domains are normalized to lowercase and without `www.`.
- The runtime payload, tool contract schema, snapshots, and targeted tests all describe the same shape.

## Feature Validation

- `python -m compileall -q src/mcp_yandex_ad`
- `pytest -q tests/test_search_serp.py`
- `python scripts/agent_lint.py`
- update/add targeted parser and contract tests for:
  - advertiser-domain resolution
  - `type`
  - `block`
  - `ads_count_top` / `ads_count_bottom`
- bounded live validation on these three queries with:
  - `region=213`
  - `device=desktop`
  - `format=html`
  - `n_results=10`
- write one repo-local validation note under `docs/sessions/` summarizing:
  - actual text-ad domains found for each query
  - whether `voicexpert.ru` is present on query 2
  - one product gallery example
  - one native-block example if present
- confirm `organic[]` remains materially unchanged for the same queries
- write feature-stage handoff artifacts:
  - `SYMPHONY_WORK_RESULT.md`
  - `SYMPHONY_STAGE_HANDOFF.md`
  - `SYMPHONY_STAGE_PATCH.diff`

## PR Validation

- `python -m compileall -q src/mcp_yandex_ad`
- `pytest -q`
- `python scripts/agent_lint.py`
- update repo-facing docs for the new `search_serp` contract where needed:
  - `README.md`
  - EN/RU Search API docs
  - client-facing handoff note in this repo
  - `CHANGELOG.md`
- PR branch, commit, and GitHub PR can be created from the approved feature result
- PR description accurately summarizes the contract change and downstream handoff impact

## Release Validation

- `python -m compileall -q src/mcp_yandex_ad`
- `pytest -q`
- `python scripts/agent_lint.py`
- `python scripts/live_validation.py --suite search`
- re-run the three control queries from the feature validation note against the release candidate and preserve the note in release artifacts
- `python scripts/release_guard.py --version X.Y.Z --require-release-notes`
- GitHub Release exists
- Docker publish succeeds for the new release

## Handoff

At the end of the PR stage, write a client-facing handoff/update note in this repo that states:

- what changed in the `search_serp` ad contract
- which new fields are available
- what the consumer should use for:
  - advertiser detection
  - own-domain presence detection
  - filtering out `product_gallery` and `native`
  - top vs bottom ad slot analysis
