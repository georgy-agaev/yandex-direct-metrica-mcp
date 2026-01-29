# Claude Code prompts (copy/paste)

## 1) Generate multi-account dashboard (last 30 days to yesterday)

Prompt:

“Generate `dashboard.generate_option1` for **all accounts** for the last 30 days **to yesterday** (inclusive).  
Save to `/Users/<you>/dashboards` with `dashboard_slug=all_accounts`, `all_accounts=true`, `return_data=false`.  
Then, **analyze the generated JSON** (KPI, funnels, campaigns, coverage/warnings) and ensure the dashboard contains **non-template, data-driven recommendations**:
- “Сделать сегодня” — 3–7 bullets tied to конкретным метрикам (CPL/CTR/отказы/лиды/расход/аномалии).
- “Вопросы для обсуждения” — 3–7 bullets with hypotheses/next checks.

If recommendations in the produced dashboard look generic or repeated across accounts, update them **per account** in the JSON and re-embed the updated JSON into the HTML (`window.__DASHBOARD_DATA__`) so the UI shows correct recommendations.

Return the path to the generated HTML file.”

## 2) Generate single-account dashboard

Prompt:

“Generate `dashboard.generate_option1` for `account_id=<your_account_id>` for the last 30 days **to yesterday**.  
Save to `/Users/<you>/dashboards` with `dashboard_slug=<slug>`, `return_data=false`.  
Then, analyze the generated JSON and write **data-driven recommendations** (not boilerplate) into the dashboard:
- Today actions (3–7)
- Discussion questions (3–7)

Return the HTML path.”

## 3) Join Direct vs Metrica by UTM (example)

Prompt:

“Run `join.hf.direct_vs_metrica_by_utm` for the last 30 days **to yesterday** for:
- `campaign_id=<campaign_id>`
- `counter_id=<metrica_counter_id>`
- `direct_client_login=<direct_client_login>`
- `utm_campaign=<utm_campaign>`

Show totals and first 5 rows of `joined_by_date`.”
