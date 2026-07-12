# Changelog

All notable changes to this MCP project will be documented in this file.

## Unreleased

- Docs: recorded Symphony Level B happy-path release evidence for `GEO-38 -> GEO-39 -> GEO-40 -> v2.0.15` and added a session note for the first fully published `feature -> PR -> release` smoke chain.

## 2.0.15 - 2026-07-12

- Automation: hardened `archive_stage_handoff.py` so interrupted merged PR stages can recover `SYMPHONY_STAGE_HANDOFF.md` and `SYMPHONY_WORK_RESULT.md` from local git plus GitHub PR metadata during workspace cleanup, allowing release follow-up creation to continue instead of silently stalling.
- Automation: added archive-name issue detection plus `--reconcile-only` recovery mode, and taught PR-stage recovery to fall back to GitHub issue-title lookup when `gh pr merge --delete-branch` has already switched away from the PR branch.
## 2.0.14 - 2026-07-09

- Search API: hardened `search_serp` ad normalization so HTML ads expose advertiser domains, redirect `click_url`, ad `type`, top/bottom `block`, and `ads_count_bottom` while keeping organic extraction stable.
## 2.0.13 - 2026-07-01

- Search API: restored and shipped the bounded `search_serp` MCP tool with normalized ads plus organic results, HTML/XML parsing, region/device controls, and public contract snapshots/tests.
- Client handoff: added `Marketing2025` release guidance for the Yandex Search API SERP migration and refreshed Search API Web Search docs/tool coverage.
- Live validation: hardened the Wordstat monthly smoke to retry a buffered closed month when the provider has not published the freshest month yet around month boundaries.
- Automation: required portable stage handoff artifacts between Symphony stages so feature review must preserve `SYMPHONY_STAGE_PATCH.diff` plus `SYMPHONY_STAGE_HANDOFF.md`, and PR/release follow-up issues now embed the source workspace path and artifact expectations.
- Automation: switched Symphony `yandex.ad` lanes to the app-bundled Codex runtime, documented browser-capable validation preference, and allowed existing Linear/repo evidence to satisfy operator/browser validation requirements on retries.
- Automation: added an explicit issue capability contract and browser/live-api/manual-check matrix so Symphony tasks must declare required capabilities, secret sources, and blocker routing before execution.
- Automation: documented external secret sourcing for Symphony from an external state `.env` file so live validation can run without copying credentials into the repo or Symphony workspace.
- Automation: changed the Symphony blocker policy so missing credentials or other missing external inputs move an issue to `Backlog` instead of re-entering the active `Todo` loop.
- Automation: split Symphony validation into stage-specific `Feature Validation`, `PR Validation`, and `Release Validation` sections to stop feature issues from bouncing between implementation and review over later-stage gates.
- Automation: updated follow-up issue generation so PR/release Linear issues carry explicit execution profile metadata and stage-scoped validation contracts.
- Automation: replaced the broken state-based `Approved` / `Releasing` Symphony model with a two-lane `implementation + review` pipeline driven by `issue-type:*` labels and follow-up Linear issues.
- Automation: extended `scripts/linear_issue.py` with `followup-pr` and `followup-release` commands that create next-stage issues in the same Linear team/project, inherit context labels, and backlink the created issue to the source issue.
- Automation: added focused follow-up harness tests in `tests/test_linear_issue_followups.py`.
- Docs: rewrote the Symphony pipeline, launch, release-gates, workflow, and intake guidance to match the new `feature -> PR -> release` issue chain.
- Skills: added a repo-local `linear-symphony-intake` skill for shaping new Symphony-ready Linear issues with explicit ownership, handoff, and release-routing decisions.

## 2.0.12 - 2026-06-19
- Wordstat: hardened Yandex Search API integration by fixing `wordstat.regions` to send `region: REGION_*`, adding `associations` to HF/dashboard keyword candidates, validating `dynamics` date constraints, making `wordstat.user_info` a live `getRegionsTree` access check, and improving Search API setup/error hints.
- Automation: added a Linear intake harness (`scripts/linear_issue.py`, templates, and docs) for creating Symphony-ready Linear issues from Markdown drafts without manual copy/paste.
- Automation: added Symphony pipeline docs plus explicit release gates, changed-line lint, live validation helpers, a manual live-validation workflow, and a GitHub Release workflow for tag-driven publishing.
- Docs: added English/Russian GitHub issue-style handoff drafts for the next Wordstat Search API hardening implementation.
- Docs: added English/Russian next-release recommendations for hardening Yandex Search API Wordstat integration, including `regions` payload mapping, `associations` handling, `dynamics` date constraints, access-check semantics, and setup docs gaps.
- Docs: added short English/Russian operator notes for Yandex Search API Web Search async requests, polling, Base64 decoding, and XML fields to parse.
- Dashboard PRO HTML: added `dashboard.generate_pro_html`, a PRO-only Option 1-derived dashboard generator that enriches the existing HTML design with search-term diagnostics, keyword quality signals, campaign watchlist rows, bid snapshots, tracking-gap findings, and actionable recommendations.
- Dashboard PRO HTML: added `scripts/generate_dashboard_pro_html.py`, focused regression coverage, and a live-demo generation path for evaluating the new dashboard against real Direct + Metrica data without a separate BI database.

## 2.0.11 - 2026-06-18
- Wordstat: migrated runtime calls from the retired `api.wordstat.yandex.net/v1` OAuth endpoint to Yandex Search API Wordstat (`searchapi.api.cloud.yandex.net/v2/wordstat`) using `YANDEX_SEARCH_API_FOLDER_ID` plus API key/IAM token credentials.
- Auth/docs: removed legacy Wordstat from `auth.*` helper wording and refreshed older documentation to use Yandex Search API credentials.

## 2.0.10 - 2026-05-08
- Docs: added a post-release handoff for `Marketing2025` in English and Russian, capturing `v2.0.10` ship status, local `:dev` image alignment, and the remaining joint replay step.
- Contracts: corrected `dashboard.generate_option1` annotations so it is no longer marked read-only when `output_dir` writes local HTML/JSON artifacts.
- Docs: added detailed handoff documents for `Marketing2025` pipeline fixes and `yandex.ad` MCP follow-up work, plus session notes linking the execution tracks and release-prep follow-up.
- Docs: added a focused contract update note for `Marketing2025` consumers covering special-campaign diagnostics, Metrica truncation warnings, Wordstat batch fallback behavior, `direct.report` / `direct.hf.report_keywords` compatibility notes, and read-only Direct login override semantics.
- MCP review fixes (2026-05-07): made generated Direct report names unique across HF/low-level helpers, fixed `direct.hf.report_keywords` to use a valid `CUSTOM_REPORT` field set, added actionable `CUSTOM_REPORT` validation for `Keyword` vs `Criterion`, auto-paginated `metrica.hf.report_*` stats responses by default, added Wordstat batch fallback for `wordstat.top_requests`, surfaced special no-structure campaign warnings in `direct.hf.get_campaign_summary`, allowed read-only Direct agency login overrides, and paginated/filter-corrected HF discovery helpers (`find_ads` states, large counts over 1000 rows).
- Path D: added an internal app-safe payload helper seam plus RFC-0003 and tests, without introducing MCP Apps runtime or changing the current MCP surface.
- Path C: added an internal static bundle manifest module and tests for `marketing2025.analyst_pipeline` without expanding the public/runtime MCP tool surface.
- Path A: surfaced top-level canonical warnings/messages for `join.hf.direct_vs_metrica_by_yclid` pending/fallback branches, added `metrica.hf.counter_summary` warnings for best-effort goals failures, and fixed explicit `max_wait_seconds=0` handling for immediate pending returns.
- Docs: added a Google Ads MCP deep-research brief and a session note to preserve the plan for a self-hosted → SaaS-ready Google Ads MCP project.
- Docs: drafted proposals for a backend operator CLI and a separate Dream Team Orchestrator repo (self-hosted → SaaS-ready).
- Docs: added a NotebookLM-derived MCP ecosystem roadmap note for `yandex.ad` plus a session note with three options and a recommended path.
- Docs: added a research note on Progressive tool discovery and MCP Apps for `yandex.ad`, plus a session note mapping official MCP guidance to current project constraints.
- Docs: clarified that discovery/UI recommendations for `yandex.ad` must remain portable across multiple model vendors and MCP-capable clients.
- Docs: added balanced development options for `yandex.ad` focused on the real needs of `Marketing2025` as the primary user.
- Docs: added an English + Russian collaboration proposal for `Marketing2025` and `yandex.ad`, plus a session note that formalizes the backend/orchestrator split for stakeholder review.
- Docs: added a formal reply to the `Marketing2025` collaboration response, a concrete `A -> C -> D` backend backlog, and an initial cross-repo RFC space with drafts for the HF envelope and role/bundle manifests.
- Docs: incorporated `Marketing2025` review feedback into `RFC-0001` by adding structured errors, envelope versioning, explicit `choices[]` / `warnings[]` element shapes, and a required-field matrix by status.
- Path A: added canonical HF envelope metadata/validation plus initial `outputSchema` and read-only annotations for the prioritized read-only tool set.
- Path A: added a focused public contract snapshot for prioritized tools and surfaced `direct.hf.pressure_report` fallback warnings at the top-level HF envelope.

## 2.0.9 - 2026-02-18
- CI: fixed public Docker publish workflow validation (avoids using `secrets.*` in `if:`; uses job `env` instead).

## 2.0.8 - 2026-02-18
- CI: fixed public Docker publish workflow parsing (keeps optional Docker Hub mirror on tags via `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN`).

## 2.0.7 - 2026-02-18
- CI: Docker publish workflow update (superseded by 2.0.8).

## 2.0.6 - 2026-02-18
- BI Option 2: removed datasets/sync implementation from the OSS core and added a PRO plugin hook (BI tools are now provided via a private plug-in).
- Public mode hardening: server now rejects tool calls that are not present in `tools/list` for the current build/config (prevents calling hidden tools by name).
- Docs: added PRO plug-in loading guide and clarified BI Option 2 is delivered via a private plug-in.

## 2.0.5 - 2026-02-17
- Dashboard Option 1: stacked campaign modal blocks (funnel above daily dynamics) to give the chart and funnel more horizontal space.
- Dashboard Option 1: added `direct.campaign_summaries` (current/prev totals + deltas) for LLM-friendly per-campaign recommendations.
- Dashboard Option 1: added `cost_rub` alias to `direct.campaign_data[*].daily` rows (keeps existing `cost` key for UI compatibility).

## 2.0.4 - 2026-02-06
- Dashboard Option 1: made Direct report `ReportName` unique per account/client login to prevent multi-account collisions (fixes empty datasets in `all_accounts` mode).
## 2.0.3 - 2026-02-05
- Direct: `direct.report` now provides safe defaults for `DateRangeType`/`Format`/`IncludeVAT`/`IncludeDiscount` (reduces UX friction).
- Audience: removed `audience.lookalikes.*` from the public read-only surface (it returned HTTP 404); server now returns a clear `NotSupported` error when called.

## 2.0.2 - 2026-02-05
- Direct: fixed `direct.list_clients` to avoid sending unsupported `SelectionCriteria` (was causing `YandexDirectClientError` code `8000`).
- Schema: relaxed `direct_client_login` hints (no hard enum restriction; agency logins are accepted).

## 2.0.1 - 2026-02-04
- Docker: bumped base image to `python:3.13-slim` to pick up newer security fixes.

## 2.0.0 - 2026-02-04
- Pro-only tools: added `auth.start` and `auth.exchange_code` (gated by `MCP_AUTH_TOOLS_ENABLED=true`; returns secrets; no storage).
- Pro-only write safety: added two-phase writes with `write.confirm` (gated by `MCP_TWO_PHASE_WRITES=true`; TTL via `MCP_CONFIRM_TTL_SECONDS`).
- CLI `auth`: added `--flow hybrid|manual|local` and loopback callback support (hybrid C3 UX); optional `--output-env` to write env block to a file.
- Added next-release session notes and tool proposal docs for Auth UX + PRO confirm.

## 1.0.0 - 2026-02-03
- BI Option 2 (PRO): expanded datasets to Variant B (Direct/Metrica/Wordstat/Join) and upgraded sync cursor/NDJSON to include `account_id`.
- PRO write: added Metrica goals CRUD (raw + HF apply-guarded) and Direct plan/apply (`direct.hf.plan_changes` / `direct.hf.apply_plan`).
- Public mode: removed BI Option 2 tools from the public surface and refreshed the public tools snapshot contract.
- Added BI Option 2 (PRO) datasets+sync proposal doc.
- `direct.hf.report_search_phrases`: implemented a Direct search query report preset.
- Added Yandex Audience support (raw + HF + pro activation) plus BI Option 2 datasets/sync tools.
- `dashboard.generate_option1`: added optional Audience blocks (`include_audience=true`) rendered in the Option 1 HTML template.
- Drafted a competitors analysis + read-only market pressure tools proposal (A+D: server-fetch + Direct/Metrica pressure).
- Added an LLM-oriented usage guide for the public read-only toolset (Direct + Metrica + Wordstat + joins + dashboard).
- Drafted a Yandex Audience tool proposal (raw + HF + dashboard integration) for the minimal contour.
- Bumped version to `0.1.1` and fixed CI install by adding `project.optional-dependencies.dev` (so `pip install -e ".[dev]"` works).
- Docker publish workflow: removed optional Docker Hub image target from metadata generation to avoid failures when Docker Hub secrets are not configured.
- Docker hardening: moved to `python:3.12-slim`, added OS package upgrades, upgraded `wheel`, and switched the runtime to a non-root user (fixes common Scout findings and reduces fixable CVEs).
- Refreshed user-facing docs: rewrote `README.md`, added `docs/quickstart.md`, `docs/public-vs-pro.md`, `docs/dashboard-option1.md`, a simple landing page `docs/index.html`, and prompt examples in `examples/claude-code-prompts.md`.
- `README.md`: added a tools/layers overview (raw vs human-friendly), added a CLI commands list, and moved legal/compliance sections to the end.
- Added Apache-2.0 `LICENSE` and an explicit affiliation/trademark disclaimer + “Compliance / Terms” section in `README.md`.
- Moved internal session logs out of the published docs folder (`docs/_sessions_local/`) and excluded from git via `.gitignore`.
- Renamed distribution/image to `yandex-direct-metrica-mcp` (legacy CLI alias kept: `mcp-yandex-ad`).
- Added public read-only mode: `MCP_PUBLIC_READONLY=true` hides write/escape-hatch tools and blocks writes at runtime.
- Added GitHub Actions CI and multi-arch Docker publish workflows (GHCR by default; Docker Hub optional).
- Option 1 dashboard: added a “Требует внимания” alerts block with KPI warning flags for common anomalies (CPL, CTR, bounce, spend vs leads, leads drop).
- Option 1 dashboard: added CPL dynamics to the daily chart (current vs previous period).
- Option 1 dashboard: added per-campaign Leads + CPL columns (best effort via UTMCampaign → CampaignId; only enabled when UTMCampaign report is Direct-only).
- Option 1 dashboard: highlighted the bottleneck step in both funnels (site and Direct) based on the weakest conversion rate in the current period.
- Option 1 dashboard: exposed `metrica.direct_by_campaign` payload for campaign-level leads derived from UTMCampaign (best effort).
- Added beta-ready launch checklist doc for Claude Code + multi-account dashboard runs.
- `dashboard.generate_option1`: added multi-account mode (`all_accounts` / `account_ids`) to generate one dashboard with a top-right account switcher.
- Option 1 dashboard toolbar: reorganized **Период / Сравнение / Кампании / Тема** layout and added a styled account selector when multi-account data is present.
- Option 1 dashboard: split the funnel into two separate blocks — **Site (all sources)** and **Direct (Metrica-attributed)** — to avoid confusing mixed displays like “X → Y (of Z)” and reduce misinterpretation of conversion rates.
- Option 1 dashboard (Option C): enabled **Поиск/РСЯ** split for Direct-attributed Metrica visits/leads via `UTMCampaign` → Direct campaign type mapping, with explicit coverage/missing notes when UTMs are not classifiable.
- Option 1 dashboard (Option C): improved debugability by including unclassified UTMCampaign leads/visits in `metrica.direct_split.meta.top_unclassified_utm` and isolating Direct-attributed UTMCampaign rows via `lastsignDirectClickOrder` (Direct campaign id) allowlist. Falls back to `lastsignSourceEngine` only when safe; avoids unfiltered fallback for shared Metrica counters to prevent cross-account lead pollution.
- Option 1 dashboard UI: added `Не классифицировано` to the campaign filter to show the remainder of Direct-attributed Metrica visits/leads that could not be mapped to Search/RSYA via UTMCampaign (CPL is intentionally not calculated there).
- Option 1 dashboard goals: added previous-period overlay for the goals chart and enabled the Direct/All sources toggle (best effort) by providing a capped per-goal breakdown for Direct traffic while keeping “All goals” in Direct scope based on `sumGoalReachesAny`.
- Option 1 dashboard sources: switched to a more distinct color palette and assigned fixed colors for key sources (Search / Direct / Other) to avoid visually ambiguous “same-ish” series colors on one chart.
- Option 1 dashboard campaigns filter: the `Все / Поиск / РСЯ` toggle now refreshes the whole dashboard for Direct metrics (charts/table). Direct-attributed steps use Option C mapping; if UTMs are not classifiable, the UI shows partial coverage/missing.
- Option 1 dashboard layout: moved **Рекомендации** under **Динамика по дням** and made both sections full-width; added an explicit note explaining UTMCampaign coverage/missing for the Direct funnel under `Поиск/РСЯ`.
- Fixed `dashboard.generate_option1` and `scripts/generate_dashboard_option1.py` to treat Direct report `Cost` as RUB (and derive `cost_micros`), fixing near-zero cost displays in generated dashboards.
- Fixed a blank-screen issue in the Option 1 BI dashboard template caused by calling `updateDashboard()` during initial theme setup (JS TDZ error).
- `dashboard.generate_option1` now supports `return_data` (defaults to `false` when `output_dir` is set) to avoid token-limit failures in chat clients while still writing HTML/JSON files.
- Fixed compact `summary` extraction for `return_data=false` (totals are taken from `direct.current.totals` / `metrica.current.totals`).
- Added Metrica “sources” breakdown (lastSignTrafficSource + lastSignSourceEngine) to Option 1 dashboard to mirror Direct Pro-style source detail (search/direct/ad engines + other remainder).
- Added Metrica “goals” breakdown to Option 1 dashboard (per-goal reaches series and a goals chart/table when `goal_ids` is provided).
- When `goal_ids` is omitted, Option 1 dashboard now tries to include “all goals” (best effort) via `ym:s:date,ym:s:goal` + `ym:s:sumGoalReachesAny`.
- Fixed funnel conversion/CPA logic to use Direct-attributed visits/leads (instead of all-site visits), preventing misleading “cost per lead” when non-ad traffic dominates.
- Expanded dashboard data to include derived Direct KPIs (CTR/CPC/CPM) and additional Metrica metrics (users, bounce rate, depth, avg visit duration seconds) for richer dashboards.
- Reworked `dashboard.generate_option1` HTML to include previous-period comparison, a funnel block, and a richer campaigns table; added optional `goal_ids` to compute leads from Metrica goals (best effort).
- `dashboard.generate_option1` now auto-excludes the current day by shifting `date_to` to yesterday when `date_to` is today or in the future.
- Clarified that the BI dashboard is generated by a local script (not an MCP tool) and documented SSE prerequisite in `docs/claude-code-setup-2026-01-27.md`.
- Added MCP utility tool `dashboard.generate_option1` to generate the BI dashboard (Option 1) directly via MCP.
- Fixed Direct report param builder to put `DateFrom`/`DateTo` into `SelectionCriteria` (required by `/json/v501/reports`).
- Added tool coverage snapshot doc (`docs/tool-coverage-2026-01-27.md`).
- Documented `accounts.json` registry format and usage (`docs/accounts-registry-2026-01-27.md`).
- Added usage examples for `account_id` and `join.hf.*` (`docs/usage-examples-2026-01-16.md`).
- Upgraded `join.hf.direct_vs_metrica_by_utm` to return a joined daily series (Direct performance + Metrica visits) using UTMCampaign filter.
- Implemented `join.hf.direct_vs_metrica_by_yclid` best-effort join: Logs API export/download + Direct click id report join, with bounds and resumable `request_id`.
- Added unit tests for join HF tools.
- Escaped UTMCampaign filter values for Metrica joins and documented yclid join limitations.
- Added dashboard generator (Option 1) script + HTML template.
- Improved `join.hf.direct_vs_metrica_by_yclid` to fall back to extracting `yclid` from `ym:s:startURL` when `ym:s:yclid` is not available in Logs API.
- Added a practical fallback for `join.hf.direct_vs_metrica_by_yclid`: join via `ym:s:lastDirectClickBanner` → Direct `ads.get` (ad id → campaign id) when Direct click-id report fields are unsupported.
- Added Claude Code setup guide for this MCP (`docs/claude-code-setup-2026-01-27.md`).
- Added multi-account registry via `MCP_ACCOUNTS_FILE` (`account_id` -> Direct `Client-Login` + optional default Metrica counter ids).
- Added `account_id` argument to `direct.*`, `metrica.*`, and `join.hf.*` tool schemas and runtime resolution in the server.
- Added `accounts.*` tools (`accounts.list`, `accounts.reload`, `accounts.upsert`, `accounts.delete`) to manage project profiles via MCP; writes are guarded by `MCP_ACCOUNTS_WRITE_ENABLED`.
- Updated `docker-compose.yml` to mount external state (for example: `/path/to/your/state`) so secrets/config aren’t baked into the image.
- Added unit tests for accounts registry loading and schema injection.
- Added `scripts/check_direct_access.py` for a minimal Direct credentials/access check.
- Made `scripts/validate_env.py`, `scripts/health_check.py`, and `scripts/smoke_test.py` load `.env` by default.
- Added per-call Direct `Client-Login` override via `direct_client_login` argument for `direct.*` and `join.hf.*` tools (multi-project support).
- Added `YANDEX_DIRECT_CLIENT_LOGINS` (CSV) to store multiple Direct client logins for UI selection.
- Added Direct API `v501` support via `YANDEX_DIRECT_API_VERSION` (Unified campaigns).
- Fixed SSE transport for `mcp` v1.25 (Starlette + `SseServerTransport`).
- Normalized callout handling for `ads.add` vs `ads.update` (`TextAd.AdExtensions` vs `TextAd.CalloutSetting`).
- Added write guard enforcement for `direct.raw_call` non-GET methods.
- Fixed Direct `sitelinks.get` / `vcards.get` behavior for `v501` (Ids required).
- Added seed/attach scripts for a full draft flow (`scripts/mcp_seed_test_energy.py`, `scripts/mcp_attach_assets_test_energy.py`).
- Added `.dockerignore` to reduce Docker build context.
- Added Direct management recipes and scripts (bids, negative keywords) using `direct.raw_call` + existing tools.
- Added management scripts for budget/strategy patching, bid modifiers, autotargeting bid, and UTM templates applied to ad URLs.
- Initial documentation structure and research artifacts.
- Added Python MCP skeleton and roadmap.
- Added write guardrails (MCP_WRITE_ENABLED, MCP_WRITE_SANDBOX_ONLY).
- Added health check script and Docker Compose config.
- Added config/write guard unit tests.
- Added normalized error payloads for Direct/Metrica failures.
- Added unit tests for error normalization.
- Added required-parameter validation for dictionaries/changes/metrica reports.
- Added unit tests for parameter validation.
- Added required-parameter validation for Direct reports.
- Normalized errors for missing client configuration.
- Added required-parameter validation for Metrica metrics.
- Added required-parameter validation for Logs API date range.
- Added required-parameter validation for Logs API fields/source.
- Added normalized error response example and clarified Logs API validation notes.
- Added required fields to MCP tool schemas for reports and logs.
- Added required-field notes to usage examples.
- Added required field to Direct raw_call tool schema.
- Added usage examples for dictionaries, changes, and raw calls.
- Added usage examples for additional Direct tools (ad groups, keywords, bids, etc).
- Added Metrica report examples for landing pages and UTM campaigns.
- Added validation checklist entries for landing pages and UTM reports.
- Added unit tests for logs/raw-call parameter validation.
- Added Direct report presets document.
- Added JSON examples to Direct report presets.
- Added summary table to Direct report presets.
- Added env validation warning for missing Direct client login.
- Added auth troubleshooting notes to setup guide.
- Added common error hints to setup guide.
- Added Direct error response example to usage docs.
- Added retry/backoff guidance to setup guide.
- Added client-side retry pseudo-code example.
- Added Direct report retry note to usage docs.
- Added Direct pagination example to usage docs.
- Added paging note to Metrica report usage example.
- Added sampling/accuracy note to Metrica report usage example.
- Added metrics glossary for commonly used fields.
- Expanded metrics glossary with conversion and bounce metrics.
- Added cost per conversion to metrics glossary.
- Added revenue and ROI to metrics glossary.
- Clarified prerequisites for conversion and revenue metrics.
- Added goals/ecommerce prerequisites to setup guide.
- Added UTM mapping strategy note to setup guide.
- Added yclid-based join notes for Logs API.
- Added Logs API yclid join example to usage docs.
- Added Logs API workflow example to usage docs.
- Added Logs API clean/cancel examples to usage docs.
- Added Logs API status and multi-part download notes.
- Added Logs API cleanup note to usage docs.
- Added sampling/accuracy guidance to setup guide.
- Added Metrica metrics vs dimensions cheat sheet.
- Expanded Metrica glossary with UTM, device, and geo dimensions.
- Added Metrica report examples for UTM source/medium, device, and city.
- Added combined Direct + Metrica workflow example.
- Added yclid-based join workflow example using Logs API.
- Added click identifier validation note for yclid joins.
- Added field mapping checklist for Direct + Metrica joins.
- Added timezone note to field mapping checklist.
- Added URL normalization note to field mapping checklist.
- Added UTM normalization note to field mapping checklist.
- Added data normalization tips doc.
- Added Direct cost unit conversion note to data normalization tips.
- Added currency and timezone alignment notes to data normalization tips.
- Clarified multi-counter and agency login notes in setup and validation.
- Added guidance for single Direct login per server instance.
- Added Docker example for running multiple instances.
- Added transport notes for stdio vs SSE in setup guide.
- Added env file and logging tips to setup guide.
- Added logging safety note to setup guide.
- Added Direct create/update tools for campaigns, ad groups, ads, and keywords.
- Added write support to tool schemas and server handlers.
- Added write validation examples and checklist updates.
- Added Direct report presets and data/field mapping docs for joins.
- Added Metrica management raw call examples for create/update.
- Added API application description doc for Direct access request.
- Avoided truthiness checks for Yandex clients in server/smoke test.
- Implemented `direct.list_campaigns` tool handler.
- Implemented `direct.list_adgroups`, `direct.list_ads`, and `direct.list_keywords` tool handlers.
- Implemented `direct.report` tool handler.
- Implemented `direct.list_clients` tool handler.
- Implemented `direct.list_dictionaries` tool handler.
- Implemented `direct.get_changes` tool handler.
- Implemented `direct.list_sitelinks` tool handler.
- Implemented `direct.list_vcards` tool handler.
- Implemented `direct.list_adextensions` tool handler.
- Implemented `direct.list_bids` tool handler.
- Implemented `direct.list_bidmodifiers` tool handler.
- Implemented Metrica tool handlers (list counters, counter info, report, logs export).
- Added token refresh unit tests.
- Added Dockerfile and local setup instructions.
- Added MCP usage examples.
- Added `.env.example` template.
- Added environment validation script.
- Implemented raw call tools for Direct and Metrica.
- Added smoke test script.
- Updated README with setup and usage pointers.
- Added OAuth code exchange script.
- Added validation checklist for real-credential testing.
