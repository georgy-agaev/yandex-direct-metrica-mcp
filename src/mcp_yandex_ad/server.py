"""MCP server for Yandex Direct + Metrica."""

import json
import logging
import os
import re
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from .accounts import AccountProfile, load_accounts_registry
from .accounts_store import delete_account, read_accounts_file, upsert_account
from .cache import TTLCache
from .auth import TokenManager
from .clients import YandexClients, build_clients, build_direct_client
from .config import AppConfig, load_config
from .errors import MissingClientError, WriteGuardError, normalize_error
from .hf_common import HFError, hf_payload
from .hf_direct import handle as hf_direct_handle
from .hf_join import handle as hf_join_handle
from .hf_metrica import handle as hf_metrica_handle
from .ratelimit import RateLimiter
from .retry import with_retries
from .tools import tool_definitions

logger = logging.getLogger("yandex-direct-metrica-mcp")

_DASHBOARD_TEMPLATE_OPTION1_2026_01_28_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "templates" / "dashboard-template-option1-2026-01-28.html"
)
_DASHBOARD_TEMPLATE_OPTION1_2026_01_28_CACHE: str | None = None


def _dashboard_get_option1_template() -> str:
    """Load the Option 1 dashboard HTML template from docs (cached).

    Falls back to the in-code template string if the file is missing.
    """
    global _DASHBOARD_TEMPLATE_OPTION1_2026_01_28_CACHE
    if _DASHBOARD_TEMPLATE_OPTION1_2026_01_28_CACHE is not None:
        return _DASHBOARD_TEMPLATE_OPTION1_2026_01_28_CACHE
    try:
        _DASHBOARD_TEMPLATE_OPTION1_2026_01_28_CACHE = _DASHBOARD_TEMPLATE_OPTION1_2026_01_28_PATH.read_text(
            encoding="utf-8"
        )
    except Exception:
        _DASHBOARD_TEMPLATE_OPTION1_2026_01_28_CACHE = _DASHBOARD_TEMPLATE_OPTION1_2026_01_28
    return _DASHBOARD_TEMPLATE_OPTION1_2026_01_28_CACHE

_DASHBOARD_TEMPLATE_OPTION1_2026_01_28 = """<!doctype html>
<html lang="ru">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>BI Dashboard — Yandex Direct + Metrica</title>
    <style>
      :root {
        --bg: #0b1020;
        --panel: rgba(255,255,255,.04);
        --text: #eaf0ff;
        --muted: rgba(234,240,255,.72);
        --border: rgba(255,255,255,.10);
        --grid: rgba(255,255,255,.08);
        --accent: #7aa2ff;
        --good: #2dd4bf;
        --bad: #fb7185;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: -apple-system, system-ui, Segoe UI, Roboto, Arial, sans-serif;
        color: var(--text);
        background: radial-gradient(1200px 800px at 20% 0%, #17214a 0%, #0b1020 55%, #070a14 100%);
      }
      .container { max-width: 1180px; margin: 0 auto; padding: 24px; }
      header { display: flex; gap: 16px; justify-content: space-between; align-items: flex-end; }
      h1 { font-size: 22px; margin: 0; letter-spacing: .2px; }
      .meta { color: var(--muted); font-size: 12px; line-height: 1.4; text-align: right; }
      .grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 12px; margin-top: 14px; }
      .card { background: linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.03)); border: 1px solid var(--border); border-radius: 14px; padding: 14px; box-shadow: 0 12px 30px rgba(0,0,0,.22); }
      .col-12 { grid-column: span 12; }
      .col-8 { grid-column: span 8; }
      .col-6 { grid-column: span 6; }
      .col-4 { grid-column: span 4; }
      @media (max-width: 980px) { header { flex-direction: column; align-items: flex-start; } .meta { text-align: left; } .col-8, .col-6, .col-4 { grid-column: span 12; } }

      .title { font-size: 12px; color: var(--muted); font-weight: 600; letter-spacing: .3px; text-transform: uppercase; margin: 0 0 10px; }
      .kpis { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
      @media (max-width: 980px) { .kpis { grid-template-columns: repeat(2, 1fr); } }
      .kpi { padding: 12px; border-radius: 12px; border: 1px solid var(--grid); background: rgba(0,0,0,.12); }
      .kpi .label { font-size: 12px; color: var(--muted); }
      .kpi .value { margin-top: 4px; font-size: 20px; font-weight: 800; }
      .kpi .delta { margin-top: 4px; font-size: 12px; color: var(--muted); }
      .delta.up { color: var(--good); }
      .delta.down { color: var(--bad); }
      .delta.neutral { color: var(--muted); }

      .funnel { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
      @media (max-width: 980px) { .funnel { grid-template-columns: 1fr; } }
      .step { padding: 10px; border-radius: 12px; border: 1px solid var(--grid); background: rgba(0,0,0,.10); }
      .step .slabel { font-size: 12px; color: var(--muted); }
      .step .svalue { margin-top: 4px; font-size: 18px; font-weight: 800; }
      .step .srate { margin-top: 4px; font-size: 12px; color: var(--muted); }

      canvas { width: 100%; height: 220px; border: 1px solid var(--grid); border-radius: 12px; background: rgba(0,0,0,.12); }
      table { width: 100%; border-collapse: collapse; font-size: 13px; }
      th, td { padding: 10px 8px; border-bottom: 1px solid var(--grid); vertical-align: top; }
      th { color: var(--muted); font-weight: 600; text-align: left; }
      .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", \"Courier New\", monospace; }
      .badge { display: inline-flex; gap: 6px; align-items: center; font-size: 12px; padding: 4px 8px; border-radius: 999px; border: 1px solid var(--grid); color: var(--muted); }
      .badge b { color: var(--text); }
      ul { margin: 0; padding-left: 18px; }
      li { margin: 6px 0; color: var(--text); }
      .note { color: var(--muted); font-size: 12px; margin-top: 8px; }
    </style>
  </head>
  <body>
    <div class="container">
      <header>
        <div>
          <h1 id="title">BI Dashboard</h1>
          <div class="note" id="subtitle">Данные: Direct + Метрика. Сравнение: vs предыдущий период той же длины.</div>
        </div>
        <div class="meta">
          <div><span class="mono" id="account">—</span></div>
          <div>Период: <span class="mono" id="period">—</span></div>
          <div>Сравнение: <span class="mono" id="prev-period">—</span></div>
          <div>Generated: <span class="mono" id="generated">—</span></div>
        </div>
      </header>

      <section class="grid">
        <div class="card col-12">
          <div class="title">KPI</div>
          <div class="kpis">
            <div class="kpi"><div class="label">Показы</div><div class="value" id="kpi-impr">—</div><div class="delta" id="kpi-impr-d">—</div></div>
            <div class="kpi"><div class="label">Клики</div><div class="value" id="kpi-clicks">—</div><div class="delta" id="kpi-clicks-d">—</div></div>
            <div class="kpi"><div class="label">CTR</div><div class="value" id="kpi-ctr">—</div><div class="delta" id="kpi-ctr-d">—</div></div>
            <div class="kpi"><div class="label">Расход</div><div class="value" id="kpi-cost">—</div><div class="delta" id="kpi-cost-d">—</div></div>
            <div class="kpi"><div class="label">CPC</div><div class="value" id="kpi-cpc">—</div><div class="delta" id="kpi-cpc-d">—</div></div>
            <div class="kpi"><div class="label">Визиты (Метрика)</div><div class="value" id="kpi-visits">—</div><div class="delta" id="kpi-visits-d">—</div></div>
          </div>
          <div class="note" id="kpi-note"></div>
        </div>

        <div class="card col-12">
          <div class="title">Воронка</div>
          <div class="funnel">
            <div class="step"><div class="slabel">Показы → Клики</div><div class="svalue" id="f-imp-click">—</div><div class="srate" id="f-imp-click-r">—</div></div>
            <div class="step"><div class="slabel">Клики → Визиты</div><div class="svalue" id="f-click-visit">—</div><div class="srate" id="f-click-visit-r">—</div></div>
            <div class="step"><div class="slabel">Визиты → Engaged</div><div class="svalue" id="f-visit-eng">—</div><div class="srate" id="f-visit-eng-r">—</div></div>
            <div class="step"><div class="slabel">Engaged → Leads</div><div class="svalue" id="f-eng-lead">—</div><div class="srate" id="f-eng-lead-r">—</div></div>
            <div class="step"><div class="slabel">Leads (итого)</div><div class="svalue" id="f-leads">—</div><div class="srate" id="f-leads-r">—</div></div>
          </div>
          <div class="note">Engaged = визиты * (1 - bounceRate). Leads заполняются, если заданы `goal_ids`.</div>
        </div>

        <div class="card col-8">
          <div class="title">Динамика по дням</div>
          <canvas id="chart"></canvas>
          <div class="note">Линии: клики (current/prev) и визиты (current/prev) — по общей шкале.</div>
        </div>

        <div class="card col-4">
          <div class="title">Рекомендации</div>
          <div class="badge"><b>Сделать сегодня</b></div>
          <ul id="today"></ul>
          <div style="height:10px"></div>
          <div class="badge"><b>Вопросы</b></div>
          <ul id="questions"></ul>
          <div style="height:10px"></div>
          <div class="badge"><b>Notes</b></div>
          <ul id="notes"></ul>
        </div>

        <div class="card col-12">
          <div class="title">Активные кампании</div>
          <table>
            <thead>
              <tr>
                <th>Кампания</th>
                <th>Показы</th>
                <th>Клики</th>
                <th>CTR</th>
                <th>Расход</th>
                <th>CPC</th>
                <th>Тренд</th>
                <th>vs Пред.</th>
              </tr>
            </thead>
            <tbody id="campaigns"></tbody>
          </table>
          <div class="note">Тренд = change clicks (last day vs first day) внутри периода. vs Пред. = change clicks vs previous period.</div>
        </div>
      </section>
    </div>

    <script>
      window.__DASHBOARD_DATA__ = /*__DATA_JSON__*/;

      const DATA = window.__DASHBOARD_DATA__ || {};
      const meta = DATA.meta || {};
      const direct = DATA.direct || {};
      const metrica = DATA.metrica || {};
      const rec = DATA.recommendations || {};

      const fmtInt = new Intl.NumberFormat('ru-RU');
      const fmt2 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
      const fmtPct = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });

      const setText = (id, t) => { const el = document.getElementById(id); if (el) el.textContent = t; };

      const curD = (direct.current || {});
      const prevD = (direct.prev || {});
      const curM = (metrica.current || {});
      const prevM = (metrica.prev || {});

      setText('title', meta.project_name ? `${meta.project_name} — BI Dashboard` : 'BI Dashboard');
      setText('account', meta.account_id || meta.direct_client_login || '—');
      setText('period', `${meta.date_from || '—'} … ${meta.date_to || '—'}`);
      setText('prev-period', `${meta.prev_date_from || '—'} … ${meta.prev_date_to || '—'}`);
      setText('generated', meta.generated_at || '—');

      const pctDelta = (cur, prev) => {
        const c = Number(cur), p = Number(prev);
        if (!Number.isFinite(c) || !Number.isFinite(p) || p <= 0) return null;
        return ((c / p) - 1) * 100;
      };
      const setDelta = (id, cur, prev, betterHigher) => {
        const el = document.getElementById(id);
        if (!el) return;
        const d = pctDelta(cur, prev);
        if (d === null) { el.className = 'delta neutral'; el.textContent = '—'; return; }
        const up = d > 0;
        const good = (betterHigher ? up : !up);
        el.className = 'delta ' + (d === 0 ? 'neutral' : (good ? 'up' : 'down'));
        const sign = d > 0 ? '+' : '';
        el.textContent = `${sign}${fmtPct.format(d)}% vs пред.`;
      };

      const impr = Number((curD.totals || {}).impressions || 0);
      const clicks = Number((curD.totals || {}).clicks || 0);
      const cost = Number((curD.totals || {}).cost_rub || 0);
      const ctr = impr > 0 ? (100 * clicks / impr) : 0;
      const cpc = clicks > 0 ? (cost / clicks) : 0;
      const visits = Number((curM.totals || {}).visits || 0);
      const bounce = (curM.totals || {}).bounce_rate;
      const dur = (curM.totals || {}).avg_visit_duration_seconds;

      setText('kpi-impr', fmtInt.format(impr));
      setText('kpi-clicks', fmtInt.format(clicks));
      setText('kpi-ctr', `${fmtPct.format(ctr)}%`);
      setText('kpi-cost', `${fmt2.format(cost)} ₽`);
      setText('kpi-cpc', `${fmt2.format(cpc)} ₽`);
      setText('kpi-visits', fmtInt.format(visits));

      setDelta('kpi-impr-d', impr, Number((prevD.totals || {}).impressions || 0), true);
      setDelta('kpi-clicks-d', clicks, Number((prevD.totals || {}).clicks || 0), true);
      setDelta('kpi-ctr-d', ctr, ((Number((prevD.totals || {}).impressions || 0) > 0) ? (100 * Number((prevD.totals || {}).clicks || 0) / Number((prevD.totals || {}).impressions || 0)) : 0), true);
      setDelta('kpi-cost-d', cost, Number((prevD.totals || {}).cost_rub || 0), false);
      setDelta('kpi-cpc-d', cpc, ((Number((prevD.totals || {}).clicks || 0) > 0) ? (Number((prevD.totals || {}).cost_rub || 0) / Number((prevD.totals || {}).clicks || 0)) : 0), false);
      setDelta('kpi-visits-d', visits, Number((prevM.totals || {}).visits || 0), true);

      const notes = [];
      if (bounce !== undefined && bounce !== null) notes.push(`Bounce ≈ ${fmtPct.format(Number(bounce))}%`);
      if (dur !== undefined && dur !== null) notes.push(`Avg dur ≈ ${fmt2.format(Number(dur))}s`);
      setText('kpi-note', notes.join(' · '));

      // Funnel
      const engaged = Number((curM.totals || {}).engaged || 0);
      const leads = Number((curM.totals || {}).leads || 0);
      const rate = (a, b) => (b > 0 ? (100 * a / b) : 0);
      setText('f-imp-click', `${fmtInt.format(impr)} → ${fmtInt.format(clicks)}`);
      setText('f-imp-click-r', `CTR ≈ ${fmtPct.format(rate(clicks, impr))}%`);
      setText('f-click-visit', `${fmtInt.format(clicks)} → ${fmtInt.format(visits)}`);
      setText('f-click-visit-r', `≈ ${fmtPct.format(rate(visits, clicks))}%`);
      setText('f-visit-eng', `${fmtInt.format(visits)} → ${fmtInt.format(engaged)}`);
      setText('f-visit-eng-r', `≈ ${fmtPct.format(rate(engaged, visits))}%`);
      setText('f-eng-lead', `${fmtInt.format(engaged)} → ${fmtInt.format(leads)}`);
      setText('f-eng-lead-r', `≈ ${fmtPct.format(rate(leads, engaged))}%`);
      setText('f-leads', fmtInt.format(leads));
      setText('f-leads-r', leads > 0 ? `≈ ${fmt2.format(cost / leads)} ₽ за lead` : '—');

      // Recommendations
      const fillList = (id, items) => {
        const el = document.getElementById(id);
        if (!el) return;
        const arr = Array.isArray(items) ? items : [];
        el.innerHTML = arr.map(x => `<li>${String(x)}</li>`).join('') || '<li>—</li>';
      };
      fillList('today', rec.today_actions);
      fillList('questions', rec.discussion_questions);
      fillList('notes', rec.notes);

      // Campaigns
      const tbody = document.getElementById('campaigns');
      const campaigns = Array.isArray(direct.campaigns) ? direct.campaigns : [];
      const rows = campaigns.slice(0, 30).map(c => {
        const name = (c.campaign_name || '').trim() || `#${c.campaign_id}`;
        const imp = Number((c.current || {}).impressions || 0);
        const clk = Number((c.current || {}).clicks || 0);
        const cost = Number((c.current || {}).cost_rub || 0);
        const ctr = imp > 0 ? (100 * clk / imp) : 0;
        const cpc = clk > 0 ? (cost / clk) : 0;
        const trend = c.trend || null;
        let trendTxt = '—';
        if (trend && trend.kind === 'inf') trendTxt = '∞';
        else if (trend && Number.isFinite(Number(trend.pct))) trendTxt = `${Number(trend.pct) > 0 ? '+' : ''}${Number(trend.pct).toFixed(1)}%`;
        const vs = c.vs_prev_clicks_pct;
        const vsTxt = (vs === null || vs === undefined || !Number.isFinite(Number(vs))) ? '—' : `${Number(vs) > 0 ? '+' : ''}${Number(vs).toFixed(1)}%`;
        return `<tr><td>${name}</td><td>${fmtInt.format(imp)}</td><td>${fmtInt.format(clk)}</td><td>${fmtPct.format(ctr)}%</td><td>${fmt2.format(cost)} ₽</td><td>${fmt2.format(cpc)} ₽</td><td>${trendTxt}</td><td>${vsTxt}</td></tr>`;
      }).join('');
      if (tbody) tbody.innerHTML = rows || '<tr><td colspan=\"8\" style=\"color: rgba(234,240,255,.6)\">No data</td></tr>';

      // Chart: normalize to max within each series group (simple rendering, no deps)
      const canvas = document.getElementById('chart');
      const ctx = canvas.getContext('2d');
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.floor(rect.width * dpr);
      canvas.height = Math.floor(rect.height * dpr);
      ctx.scale(dpr, dpr);

      const W = rect.width, H = rect.height;
      const pad = 14;
      const plotW = W - pad * 2;
      const plotH = H - pad * 2;

      const curDailyD = Array.isArray(curD.daily) ? curD.daily : [];
      const prevDailyD = Array.isArray(prevD.daily) ? prevD.daily : [];
      const curDailyM = Array.isArray(curM.daily) ? curM.daily : [];
      const prevDailyM = Array.isArray(prevM.daily) ? prevM.daily : [];

      const byDate = (arr, field) => new Map(arr.map(x => [String(x.date), Number(x[field] || 0)]));
      const curClicks = byDate(curDailyD, 'clicks');
      const prevClicks = byDate(prevDailyD, 'clicks');
      const curVisits = byDate(curDailyM, 'visits');
      const prevVisits = byDate(prevDailyM, 'visits');
      const labels = curDailyD.map(x => String(x.date));
      const points = labels.map((d, i) => ({
        i,
        curClicks: curClicks.get(d) || 0,
        prevClicks: prevClicks.get(d) || 0,
        curVisits: curVisits.get(d) || 0,
        prevVisits: prevVisits.get(d) || 0,
      }));

      const max = (k) => Math.max(1, ...points.map(p => Number(p[k] || 0)));
      const maxClicks = Math.max(max('curClicks'), max('prevClicks'));
      const maxVisits = Math.max(max('curVisits'), max('prevVisits'));

      const xAt = (i) => pad + (points.length <= 1 ? 0 : (plotW * i) / (points.length - 1));
      const yAt = (val, m) => pad + plotH - (plotH * (val / m));

      ctx.clearRect(0, 0, W, H);
      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const y = pad + (plotH * i) / 4;
        ctx.beginPath();
        ctx.moveTo(pad, y);
        ctx.lineTo(pad + plotW, y);
        ctx.stroke();
      }

      const draw = (getter, m, color, width) => {
        if (!points.length) return;
        ctx.beginPath();
        points.forEach((p, i) => {
          const x = xAt(i);
          const y = yAt(getter(p), m);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.strokeStyle = color;
        ctx.lineWidth = width;
        ctx.stroke();
      };

      draw(p => p.prevClicks, maxClicks, 'rgba(122,162,255,0.30)', 2);
      draw(p => p.curClicks, maxClicks, 'rgba(122,162,255,0.95)', 2);
      if (curDailyM.length || prevDailyM.length) {
        draw(p => p.prevVisits, maxVisits, 'rgba(45,212,191,0.25)', 2);
        draw(p => p.curVisits, maxVisits, 'rgba(45,212,191,0.90)', 2);
      }
    </script>
  </body>
</html>
"""


@dataclass
class AppContext:
    config: AppConfig
    tokens: TokenManager
    clients: YandexClients
    cache: TTLCache | None
    direct_rate_limiter: RateLimiter
    metrica_rate_limiter: RateLimiter
    direct_clients_cache: dict[str, object]
    direct_clients_cache_lock: threading.Lock
    direct_clients_cache_max_size: int = 8
    accounts_registry_lock: threading.Lock = field(default_factory=threading.Lock)
    accounts_registry_cache: dict[str, AccountProfile] | None = None
    accounts_registry_mtime: float | None = None

    # Convenience wrappers so HF modules don't have to import server internals.
    def _direct_get(self, resource: str, params: dict[str, Any]) -> dict[str, Any]:
        return _direct_get(self, resource, params)

    def _direct_call(self, resource: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return _direct_call(self, resource, method, params)

    def _direct_report(self, params: dict[str, Any]) -> dict[str, Any]:
        return _direct_report(self, params)

    def _metrica_get_management(self, resource: str, params: dict[str, Any]) -> dict[str, Any]:
        return _metrica_get_management(self, resource, params)

    def _metrica_management_call(
        self,
        resource: str,
        method: str,
        params: dict[str, Any] | None,
        data: dict[str, Any] | None,
        path_args: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return _metrica_management_call(self, resource, method, params, data, path_args)

    def _metrica_get_counter(self, counter_id: str, params: dict[str, Any]) -> dict[str, Any]:
        return _metrica_get_counter(self, counter_id, params)

    def _metrica_get_stats(self, params: dict[str, Any]) -> dict[str, Any]:
        return _metrica_get_stats(self, params)

    def _metrica_logs_call(
        self,
        action: str,
        path_args: dict[str, Any],
        params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return _metrica_logs_call(self, action, path_args, params)


WRITE_TOOLS = {
    "direct.create_campaigns",
    "direct.update_campaigns",
    "direct.create_adgroups",
    "direct.update_adgroups",
    "direct.create_ads",
    "direct.update_ads",
    "direct.create_keywords",
    "direct.update_keywords",
}


def _missing_envs(config: AppConfig) -> list[str]:
    missing = []
    if not config.access_token and not config.refresh_token:
        missing.append("YANDEX_ACCESS_TOKEN or YANDEX_REFRESH_TOKEN")
    if config.refresh_token and not (config.client_id and config.client_secret):
        missing.append("YANDEX_CLIENT_ID/YANDEX_CLIENT_SECRET")
    return missing


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True)


def _text_response(payload: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=_json_text(payload))]


def _summarize_payload(tool: str, payload: dict[str, Any]) -> str:
    if "error" in payload and isinstance(payload["error"], dict):
        err = payload["error"]
        msg = err.get("message") or err.get("type") or "error"
        rid = err.get("request_id")
        return f"{tool}: error: {msg}" + (f" (request_id={rid})" if rid else "")

    result = payload.get("result")
    if isinstance(result, dict):
        counts: list[str] = []
        for key, value in result.items():
            if isinstance(value, list):
                counts.append(f"{key}={len(value)}")
        if counts:
            return f"{tool}: ok ({', '.join(counts)})"
        return f"{tool}: ok (result keys: {', '.join(result.keys())})"

    top_keys = ", ".join(list(payload.keys())[:8]) if isinstance(payload, dict) else ""
    return f"{tool}: ok" + (f" (keys: {top_keys})" if top_keys else "")


def _ok_result(ctx: AppContext, tool: str, payload: dict[str, Any]) -> tuple[list[TextContent], dict[str, Any]]:
    """Return both human content and structured content."""
    mode = (ctx.config.content_mode or "json").strip().lower()
    if mode in {"summary", "summ"}:
        return [TextContent(type="text", text=_summarize_payload(tool, payload))], payload
    if mode in {"summary_json", "summary+json", "summ+json"}:
        return [
            TextContent(type="text", text=_summarize_payload(tool, payload)),
            TextContent(type="text", text=_json_text(payload)),
        ], payload
    return _text_response(payload), payload


def _error_response(tool: str, exc: Exception) -> list[TextContent]:
    payload = normalize_error(tool, exc)
    logger.error("%s failed: %s", tool, payload["error"].get("message", exc.__class__.__name__))
    return _text_response(payload)


def _is_write_tool(name: str, args: dict[str, Any] | None = None) -> bool:
    if name in WRITE_TOOLS:
        return True
    if name == "direct.raw_call":
        method = (args or {}).get("method") or "get"
        return str(method).lower() != "get"
    if name == "metrica.raw_call":
        method = (args or {}).get("method") or "get"
        return str(method).lower() != "get"
    # HF tools execute writes only when apply=true; enforce base write guardrails then.
    if name.startswith("direct.hf.") and (args or {}).get("apply"):
        return True
    return False


def _enforce_write_guard(config: AppConfig, name: str, args: dict[str, Any] | None = None) -> None:
    if not _is_write_tool(name, args):
        return
    if getattr(config, "public_readonly", False):
        raise WriteGuardError(
            "public",
            "Write operations are disabled in public read-only mode.",
            "Use the pro edition or run without MCP_PUBLIC_READONLY=true.",
        )
    if not config.write_enabled:
        raise WriteGuardError(
            "direct",
            "Write operations are disabled.",
            "Set MCP_WRITE_ENABLED=true to allow write operations.",
        )
    if config.write_sandbox_only and not config.use_sandbox:
        raise WriteGuardError(
            "direct",
            "Write operations are allowed only in sandbox.",
            "Set YANDEX_DIRECT_SANDBOX=true or disable MCP_WRITE_SANDBOX_ONLY.",
        )


def _normalize_raw_data(data: Any) -> Any:
    if isinstance(data, bytes):
        return data.decode("utf-8", "ignore")
    return data


def _normalize_direct_client_login(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    normalized = value.strip()
    return normalized or None


def _refresh_accounts_registry(ctx: AppContext, *, force: bool = False) -> dict[str, AccountProfile]:
    path = ctx.config.accounts_file
    if not path:
        return ctx.config.accounts or {}

    try:
        mtime = os.stat(path).st_mtime
    except FileNotFoundError:
        return {}

    with ctx.accounts_registry_lock:
        if not force and ctx.accounts_registry_cache is not None and ctx.accounts_registry_mtime == mtime:
            return ctx.accounts_registry_cache

        accounts = load_accounts_registry(path)
        ctx.accounts_registry_cache = accounts
        ctx.accounts_registry_mtime = mtime

        # Keep tool schemas (enums) in sync for list_tools calls.
        try:
            ctx.config.accounts.clear()
            ctx.config.accounts.update(accounts)
        except Exception:
            pass
        return accounts


def _resolve_account_overrides(
    ctx: AppContext,
    tool: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Resolve `account_id` to per-call Direct/Metrica defaults."""
    account_id = args.get("account_id")
    if not account_id:
        return args
    if not isinstance(account_id, str):
        account_id = str(account_id)
    account_id = account_id.strip()
    if not account_id:
        return args

    accounts = _refresh_accounts_registry(ctx)
    profile = (accounts or {}).get(account_id)
    if profile is None:
        available = ", ".join(sorted((accounts or {}).keys()))
        raise ValueError(f"Unknown account_id: {account_id}. Available: {available or '<none>'}")

    resolved = dict(args)

    # Direct: resolve Client-Login
    if tool.startswith(("direct.", "direct.hf.", "join.hf.", "dashboard.")):
        explicit_login = _normalize_direct_client_login(resolved.get("direct_client_login"))
        profile_login = _normalize_direct_client_login(profile.direct_client_login)
        if explicit_login and profile_login and explicit_login != profile_login:
            raise ValueError(
                f"direct_client_login={explicit_login} conflicts with account_id={account_id} "
                f"(direct_client_login={profile_login})"
            )
        if not explicit_login and profile_login:
            resolved["direct_client_login"] = profile_login

    # Metrica: resolve counter_id if the tool expects it
    needs_counter = tool.startswith(
        ("metrica.report", "metrica.counter_info", "metrica.logs_export", "metrica.hf.", "join.hf.", "dashboard.")
    )
    if needs_counter and not resolved.get("counter_id"):
        counters = [str(x).strip() for x in (profile.metrica_counter_ids or []) if str(x).strip()]
        if len(counters) == 1:
            resolved["counter_id"] = counters[0]
        elif len(counters) > 1:
            raise ValueError(
                f"Multiple Metrica counters configured for account_id={account_id}; "
                f"pass counter_id explicitly. Available: {', '.join(counters)}"
            )

    return resolved


def _dashboard_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _dashboard_safe_slug(value: str | None) -> str:
    value = (value or "").strip()
    if not value:
        return "default"
    out: list[str] = []
    for ch in value:
        if ch.isalnum() or ch in {"-", "_", "."}:
            out.append(ch)
        elif ch.isspace():
            out.append("_")
    return ("".join(out)[:80] or "default")


def _dashboard_float_or_zero(value: Any) -> float:
    try:
        if isinstance(value, str):
            cleaned = (
                value.replace("\xa0", " ")
                .replace(" ", "")
                .strip()
                .replace(",", ".")
            )
            if cleaned == "":
                return 0.0
            return float(cleaned)
        return float(value)
    except Exception:
        return 0.0


def _dashboard_sum(values: list[float]) -> float:
    total = 0.0
    for v in values:
        total += float(v)
    return total


def _dashboard_rub_to_micros(value_rub: float) -> int:
    # Direct reports for verified accounts return Cost as RUB. Keep both RUB and micros.
    try:
        return int(round(float(value_rub) * 1_000_000))
    except Exception:
        return 0


def _dashboard_safe_div(n: float, d: float) -> float | None:
    try:
        if float(d) == 0.0:
            return None
        return float(n) / float(d)
    except Exception:
        return None


def _dashboard_parse_ymd(value: str) -> date:
    value = (value or "").strip()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        raise ValueError(f"Invalid date: {value!r}. Expected YYYY-MM-DD.")


def _dashboard_to_ymd(value: date) -> str:
    return value.isoformat()


def _dashboard_enumerate_days(start: date, end: date) -> list[date]:
    if end < start:
        return []
    days: list[date] = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur = cur + timedelta(days=1)
    return days


def _dashboard_compute_trend(values: list[float]) -> dict[str, Any] | None:
    # Trend definition (used by the dashboard): last vs first.
    if not values:
        return None
    first = float(values[0])
    last = float(values[-1])
    if first == 0.0:
        if last == 0.0:
            return {"kind": "zero", "pct": 0.0}
        return {"kind": "inf"}
    return {"kind": "pct", "pct": ((last / first) - 1.0) * 100.0}


def _dashboard_weighted_avg(items: list[dict[str, Any]], *, value_key: str, weight_key: str) -> float | None:
    total_w = 0.0
    total_v = 0.0
    for item in items:
        w = _dashboard_float_or_zero(item.get(weight_key))
        v = _dashboard_float_or_zero(item.get(value_key))
        if w <= 0:
            continue
        total_w += w
        total_v += w * v
    if total_w <= 0:
        return None
    return total_v / total_w


def _dashboard_guess_delimiter(text: str) -> str:
    if "\t" in text:
        return "\t"
    if ";" in text:
        return ";"
    return ","


def _dashboard_parse_delimited(
    raw: str,
    *,
    delimiter: str | None = None,
    columns: list[str] | None = None,
) -> list[dict[str, str]]:
    raw = raw or ""
    delimiter = delimiter or _dashboard_guess_delimiter(raw)
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        return []

    header = columns[:] if columns else []
    if not header:
        header = [c.strip() for c in lines[0].split(delimiter)]
        lines = lines[1:]

    rows: list[dict[str, str]] = []
    for line in lines:
        if line.lower().startswith(("total", "итого", "всего")):
            continue
        parts = line.split(delimiter)
        if len(parts) != len(header):
            continue
        rows.append({header[i]: parts[i] for i in range(len(header))})
    return rows


def _dashboard_build_recommendations(data: dict[str, Any]) -> dict[str, Any]:
    direct_block = data.get("direct") or {}
    metrica_block = data.get("metrica") or {}
    direct_totals = (
        (direct_block.get("current") or {}).get("totals")
        or direct_block.get("totals")
        or {}
    )
    metrica_totals = (
        (metrica_block.get("current") or {}).get("totals")
        or metrica_block.get("totals")
        or {}
    )
    coverage = data.get("coverage") or {}

    clicks = _dashboard_float_or_zero(direct_totals.get("clicks"))
    cost_rub = _dashboard_float_or_zero(direct_totals.get("cost_rub"))
    visits = _dashboard_float_or_zero(metrica_totals.get("visits"))
    bounce_rate = (
        _dashboard_float_or_zero(metrica_totals.get("bounce_rate"))
        if metrica_totals.get("bounce_rate") is not None
        else None
    )

    today_actions: list[str] = []
    discussion_questions: list[str] = []
    notes: list[str] = []

    if clicks <= 0:
        today_actions.append("Проверить, что Direct отчёт возвращает клики (период/доступ/кампании не архивированы).")
    else:
        today_actions.append(
            "Проверить топ-кампании по расходу и кликам: выключить явные аутсайдеры или ограничить бюджет (если это допустимо)."
        )
        today_actions.append(
            "Проверить поисковые фразы/ключи с высокой ценой клика и низкой вовлечённостью (UTM/цели нужны для точной оценки)."
        )

    if cost_rub > 0 and clicks > 0:
        cpc = cost_rub / clicks
        discussion_questions.append(f"Нормален ли текущий средний CPC ≈ {cpc:.2f} RUB для ниши и региона?")
    else:
        discussion_questions.append("Нужны клики/расход, чтобы обсудить CPC и эффективность по кампаниям.")

    if visits <= 0:
        notes.append("Нет данных Метрики (нужен counter_id/доступ к счётчику), рекомендации по сайту ограничены.")
        today_actions.append("Подключить/проверить доступ к счётчику Метрики и повторить выгрузку.")
    else:
        discussion_questions.append("Есть ли цели/конверсии в Метрике? Без них нельзя оценить CPL/ROI по источникам.")
        today_actions.append("Если цели настроены — добавить в отчёт метрики по целям/лидам (ym:s:goal… или revenue).")
        if bounce_rate is not None and bounce_rate >= 0:
            if bounce_rate >= 60:
                today_actions.append(
                    f"Высокий bounce rate ≈ {bounce_rate:.1f}%: проверить посадочные, скорость и соответствие объявлений ожиданиям."
                )
            elif bounce_rate <= 20:
                notes.append(f"Низкий bounce rate ≈ {bounce_rate:.1f}% — возможно, трафик хорошо совпадает с посадочной.")

    direct_cov = None
    metrica_cov = None
    if isinstance(coverage, dict):
        direct_cov = coverage.get("direct_current_daily") or coverage.get("direct_daily")
        metrica_cov = coverage.get("metrica_current_daily") or coverage.get("metrica_daily")
    if isinstance(direct_cov, dict) and isinstance(metrica_cov, dict):
        d_first, d_last = direct_cov.get("first_date"), direct_cov.get("last_date")
        m_first, m_last = metrica_cov.get("first_date"), metrica_cov.get("last_date")
        if d_first and d_last and m_first and m_last:
            if m_last < d_first or d_last < m_first:
                notes.append("Периоды Direct и Метрики не пересекаются — проверьте таймзону/период/доступ.")

    while len(today_actions) < 3:
        today_actions.append("Уточнить, какие кампании/группы разрешено менять (sandbox vs live) и лимиты по ставкам.")
    while len(discussion_questions) < 3:
        discussion_questions.append(
            "Какая UTMCampaign схема считается эталонной, чтобы корректно делать joins (по ID, по имени, по slug)?"
        )

    return {
        "today_actions": today_actions[:10],
        "discussion_questions": discussion_questions[:10],
        "notes": notes,
    }


def _dashboard_render_html(template: str, *, data_json: str) -> str:
    return template.replace("/*__DATA_JSON__*/", data_json)


def _dashboard_build_compact_result(data: dict[str, Any], *, warnings: list[str], coverage: dict[str, Any]) -> dict[str, Any]:
    direct_block = data.get("direct") or {}
    direct_cur = (direct_block.get("current") or {})
    direct_prev = (direct_block.get("prev") or {})
    direct_cur_tot = (direct_cur.get("totals") or {}) if isinstance(direct_cur, dict) else {}
    direct_prev_tot = (direct_prev.get("totals") or {}) if isinstance(direct_prev, dict) else {}

    metrica_block = data.get("metrica") or {}
    metrica_cur = (metrica_block.get("current") or {})
    metrica_prev = (metrica_block.get("prev") or {})
    metrica_cur_tot = (metrica_cur.get("totals") or {}) if isinstance(metrica_cur, dict) else {}
    metrica_prev_tot = (metrica_prev.get("totals") or {}) if isinstance(metrica_prev, dict) else {}

    return {
        "summary": {
            "direct": {
                "current": {
                    "total_impressions": direct_cur_tot.get("impressions"),
                    "total_clicks": direct_cur_tot.get("clicks"),
                    "total_cost_rub": direct_cur_tot.get("cost_rub"),
                    "ctr_pct": direct_cur_tot.get("ctr"),
                    "avg_cpc_rub": direct_cur_tot.get("cpc"),
                },
                "prev": {
                    "total_impressions": direct_prev_tot.get("impressions"),
                    "total_clicks": direct_prev_tot.get("clicks"),
                    "total_cost_rub": direct_prev_tot.get("cost_rub"),
                    "ctr_pct": direct_prev_tot.get("ctr"),
                    "avg_cpc_rub": direct_prev_tot.get("cpc"),
                },
            },
            "metrica": {
                "current": {
                    "total_visits": metrica_cur_tot.get("visits"),
                    "total_users": metrica_cur_tot.get("users"),
                    "bounce_rate_pct": metrica_cur_tot.get("bounce_rate"),
                    "avg_duration_seconds": metrica_cur_tot.get("avg_visit_duration_seconds"),
                    "avg_page_depth": metrica_cur_tot.get("page_depth"),
                    "engaged_visits": metrica_cur_tot.get("engaged"),
                    "leads_total": metrica_cur_tot.get("leads"),
                },
                "prev": {
                    "total_visits": metrica_prev_tot.get("visits"),
                    "total_users": metrica_prev_tot.get("users"),
                    "bounce_rate_pct": metrica_prev_tot.get("bounce_rate"),
                    "avg_duration_seconds": metrica_prev_tot.get("avg_visit_duration_seconds"),
                    "avg_page_depth": metrica_prev_tot.get("page_depth"),
                    "engaged_visits": metrica_prev_tot.get("engaged"),
                    "leads_total": metrica_prev_tot.get("leads"),
                },
            },
        },
        "meta": data.get("meta"),
        "warnings": warnings,
        "coverage": coverage,
    }


def _dashboard_build_metrica_sources(
    *,
    all_days: list[str],
    report: dict[str, Any],
    max_series: int = 8,
) -> dict[str, Any]:
    """Build a compact "sources" view similar to Direct Pro.

    Uses Metrica dimensions: date + trafficSource + sourceEngine (attribution=lastsign).
    Output is a small set of time series suitable for a multi-line chart:
    - Search (traffic source category)
    - Direct (traffic source category)
    - Yandex Direct (best-effort from ad engines)
    - Top engines (social/messenger/recommendation/ad), plus "Other sources" remainder.
    """
    if not isinstance(report.get("data"), list):
        return {"available": False, "series": [], "meta": {"reason": "no_data"}}

    # Collect raw rows.
    by_date_total: dict[str, float] = {}
    by_date_cat: dict[str, dict[str, float]] = {}
    by_date_engine: dict[str, dict[str, float]] = {}
    engine_totals: dict[str, float] = {}
    engine_by_cat_totals: dict[str, dict[str, float]] = {}
    cat_names: dict[str, str] = {}

    def _norm(s: Any) -> str:
        return str(s or "").strip()

    def _cat_key(dim: dict[str, Any]) -> str:
        cid = _norm(dim.get("id")).lower()
        cname = _norm(dim.get("name")).lower()
        if cid == "organic" or "поис" in cname:
            return "organic"
        if cid == "direct" or "прям" in cname:
            return "direct"
        if cid == "ad" or "реклам" in cname:
            return "ad"
        return cid or cname or "unknown"

    for row in report.get("data") or []:
        if not isinstance(row, dict):
            continue
        dims = row.get("dimensions")
        mets = row.get("metrics")
        if not isinstance(dims, list) or not isinstance(mets, list) or len(dims) < 3:
            continue
        dim_date = dims[0] if isinstance(dims[0], dict) else {"name": _norm(dims[0])}
        dim_cat = dims[1] if isinstance(dims[1], dict) else {"name": _norm(dims[1])}
        dim_engine = dims[2] if isinstance(dims[2], dict) else {"name": _norm(dims[2])}

        day = _norm(dim_date.get("name"))[:10]
        if not day:
            continue
        cat = _cat_key(dim_cat)
        if cat and cat not in cat_names:
            cat_names[cat] = _norm(dim_cat.get("name")) or cat
        engine_name = _norm(dim_engine.get("name")) or _norm(dim_engine.get("id")) or "—"
        visits = _dashboard_float_or_zero(mets[0] if len(mets) > 0 else 0)

        by_date_total[day] = by_date_total.get(day, 0.0) + visits
        by_date_cat.setdefault(day, {})
        by_date_cat[day][cat] = by_date_cat[day].get(cat, 0.0) + visits

        by_date_engine.setdefault(day, {})
        by_date_engine[day][engine_name] = by_date_engine[day].get(engine_name, 0.0) + visits

        engine_totals[engine_name] = engine_totals.get(engine_name, 0.0) + visits
        engine_by_cat_totals.setdefault(engine_name, {})
        engine_by_cat_totals[engine_name][cat] = engine_by_cat_totals[engine_name].get(cat, 0.0) + visits

    if not by_date_total:
        return {"available": False, "series": [], "meta": {"reason": "empty"}}

    # Pick a "Yandex Direct" engine within ad traffic (best effort).
    ad_engines: dict[str, float] = {}
    for engine, cats in engine_by_cat_totals.items():
        ad_total = float(cats.get("ad") or 0.0)
        if ad_total > 0:
            ad_engines[engine] = ad_total

    def _looks_like_yandex_direct(name: str) -> bool:
        lowered = name.lower()
        return ("директ" in lowered) or ("yandex" in lowered and "direct" in lowered) or ("direct" in lowered)

    yandex_direct_engine: str | None = None
    if ad_engines:
        direct_candidates = {k: v for k, v in ad_engines.items() if _looks_like_yandex_direct(k)}
        pick_from = direct_candidates if direct_candidates else ad_engines
        yandex_direct_engine = max(pick_from.items(), key=lambda kv: kv[1])[0]

    # Choose additional top engines from non-search/non-direct categories to mimic "detailed sources".
    def _primary_cat(engine: str) -> str:
        cats = engine_by_cat_totals.get(engine) or {}
        if not cats:
            return "unknown"
        return max(cats.items(), key=lambda kv: float(kv[1] or 0.0))[0]

    excluded_engines = {yandex_direct_engine} if yandex_direct_engine else set()
    engine_candidates: list[tuple[str, float]] = []
    for engine, total in engine_totals.items():
        if engine in excluded_engines:
            continue
        cat = _primary_cat(engine)
        if cat in {"organic", "direct"}:
            continue
        if total <= 0:
            continue
        engine_candidates.append((engine, float(total)))
    engine_candidates.sort(key=lambda kv: kv[1], reverse=True)

    # Leave room for: organic + direct + yandex_direct + other remainder.
    budget = max(0, int(max_series) - 4)
    top_engines = [name for name, _ in engine_candidates[:budget]]

    # Build daily series helpers.
    def _series_from_cat(cat: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for day in all_days:
            out.append({"date": day, "visits": float((by_date_cat.get(day) or {}).get(cat) or 0.0)})
        return out

    def _series_from_engine(engine: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for day in all_days:
            out.append({"date": day, "visits": float((by_date_engine.get(day) or {}).get(engine) or 0.0)})
        return out

    def _total_from_daily(daily: list[dict[str, Any]]) -> float:
        return _dashboard_sum([float(x.get("visits") or 0.0) for x in daily])

    series: list[dict[str, Any]] = []

    # Search engines (category)
    series.append(
        {
            "key": "organic",
            "label": cat_names.get("organic") or "Переходы из поисковых систем",
            "kind": "traffic_source",
            "daily": (daily := _series_from_cat("organic")),
            "total_visits": _total_from_daily(daily),
        }
    )

    # Yandex Direct (engine inside ad category)
    if yandex_direct_engine:
        series.append(
            {
                "key": f"engine:{yandex_direct_engine}",
                "label": yandex_direct_engine,
                "kind": "source_engine",
                "daily": (daily := _series_from_engine(yandex_direct_engine)),
                "total_visits": _total_from_daily(daily),
            }
        )

    # Direct visits (category)
    series.append(
        {
            "key": "direct",
            "label": cat_names.get("direct") or "Прямые заходы",
            "kind": "traffic_source",
            "daily": (daily := _series_from_cat("direct")),
            "total_visits": _total_from_daily(daily),
        }
    )

    for engine in top_engines:
        series.append(
            {
                "key": f"engine:{engine}",
                "label": engine,
                "kind": "source_engine",
                "daily": (daily := _series_from_engine(engine)),
                "total_visits": _total_from_daily(daily),
            }
        )

    # Remainder series ("Other sources") to keep totals meaningful.
    shown_keys = [s["key"] for s in series]
    shown_engines = {k.split("engine:", 1)[-1] for k in shown_keys if isinstance(k, str) and k.startswith("engine:")}
    include_other = True
    if include_other:
        other_daily: list[dict[str, Any]] = []
        for day in all_days:
            total = float(by_date_total.get(day) or 0.0)
            organic = float((by_date_cat.get(day) or {}).get("organic") or 0.0)
            direct = float((by_date_cat.get(day) or {}).get("direct") or 0.0)
            engines_sum = 0.0
            for eng in shown_engines:
                engines_sum += float((by_date_engine.get(day) or {}).get(eng) or 0.0)
            remainder = total - organic - direct - engines_sum
            if remainder < 0:
                remainder = 0.0
            other_daily.append({"date": day, "visits": remainder})
        series.append(
            {
                "key": "other",
                "label": "Другие источники",
                "kind": "remainder",
                "daily": other_daily,
                "total_visits": _total_from_daily(other_daily),
            }
        )

    # Keep most relevant series first (by total visits), but keep key categories near the top.
    def _rank(item: dict[str, Any]) -> tuple[int, float]:
        key = str(item.get("key") or "")
        fixed = {"organic": 0, "engine:" + str(yandex_direct_engine or ""): 1, "direct": 2, "other": 99}
        for fk, pr in fixed.items():
            if key == fk:
                return (pr, -float(item.get("total_visits") or 0.0))
        return (10, -float(item.get("total_visits") or 0.0))

    series.sort(key=_rank)

    return {
        "available": True,
        "attribution": "lastsign",
        "dimensions": ["ym:s:date", "ym:s:lastsignTrafficSource", "ym:s:lastsignSourceEngine"],
        "series": series[: max_series],
        "meta": {
            "max_series": int(max_series),
            "picked_yandex_direct_engine": yandex_direct_engine,
        },
    }


def _dashboard_metrica_filter_quote(value: str) -> str:
    """Quote a value for Metrica `filters` expressions."""
    value = value or ""
    if "'" not in value:
        return "'" + value.replace("\\", "\\\\") + "'"
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _dashboard_campaign_type_from_utm(
    *,
    utm_campaign: str,
    campaign_data: dict[str, Any],
    name_index: dict[str, list[str]],
) -> str | None:
    """Map a Metrica UTMCampaign value to Direct campaign type (search/rsya) best-effort.

    Option C: Split Direct-attributed visits/leads by UTMCampaign → Direct campaign type.
    Requires stable UTMCampaign values (recommended: embed campaign_id).
    """
    utm = (utm_campaign or "").strip()
    if not utm:
        return None

    # Prefer explicit numeric campaign id embedded in UTMCampaign.
    for m in re.findall(r"\b\d{6,}\b", utm):
        if m in campaign_data:
            t = str((campaign_data.get(m) or {}).get("type") or "").strip()
            return t if t in {"search", "rsya"} else None

    # Fall back to exact name matching if unique.
    ids = name_index.get(utm) or []
    if len(ids) == 1:
        cid = ids[0]
        t = str((campaign_data.get(cid) or {}).get("type") or "").strip()
        return t if t in {"search", "rsya"} else None

    return None


def _dashboard_campaign_id_from_utm(
    *,
    utm_campaign: str,
    campaign_data: dict[str, Any],
    name_index: dict[str, list[str]],
) -> str | None:
    """Map a Metrica UTMCampaign value to a Direct campaign id best-effort.

    We prefer explicit numeric campaign id embedded in UTMCampaign.
    Falls back to exact name matching if unique.
    """
    utm = (utm_campaign or "").strip()
    if not utm:
        return None

    for m in re.findall(r"\b\d{6,}\b", utm):
        if m in campaign_data:
            return m

    ids = name_index.get(utm) or []
    if len(ids) == 1:
        return ids[0]

    return None


def _dashboard_build_metrica_direct_by_campaign_utm(
    *,
    all_days: list[str],
    report: dict[str, Any],
    campaign_data: dict[str, Any],
    goals_mode: str,
    goal_ids_user: list[str],
    report_is_direct_only: bool,
) -> dict[str, Any]:
    """Build per-campaign (campaignId) daily visits/leads from UTMCampaign report (best effort).

    This enables per-campaign CPL in the dashboard when UTMCampaign values are stable and
    the UTMCampaign report can be limited to Direct-attributed traffic.
    """
    rows = report.get("data")
    if not isinstance(rows, list) or not rows:
        return {"available": False, "reason": "no_data"}

    # Index by campaign name/shortName for exact matching.
    name_index: dict[str, list[str]] = {}
    for cid, camp in (campaign_data or {}).items():
        if not isinstance(camp, dict):
            continue
        for key in ("name", "shortName"):
            n = str(camp.get(key) or "").strip()
            if not n:
                continue
            name_index.setdefault(n, [])
            if cid not in name_index[n]:
                name_index[n].append(cid)

    by_campaign_date: dict[str, dict[str, dict[str, float]]] = {}
    total_direct_visits = 0.0
    classified_visits = 0.0
    total_direct_leads = 0.0
    classified_leads = 0.0
    unclassified_by_utm: dict[str, float] = {}
    unclassified_leads_by_utm: dict[str, float] = {}

    for row in rows:
        if not isinstance(row, dict):
            continue
        dims = row.get("dimensions")
        mets = row.get("metrics")
        if not isinstance(dims, list) or not isinstance(mets, list) or len(dims) < 2 or len(mets) < 2:
            continue

        dim_date = dims[0] if isinstance(dims[0], dict) else {"name": str(dims[0])}
        dim_utm = dims[1] if isinstance(dims[1], dict) else {"name": str(dims[1])}

        day = str(dim_date.get("name") or "")[:10]
        if not day:
            continue

        visits = _dashboard_float_or_zero(mets[0])
        bounce = _dashboard_float_or_zero(mets[1])
        leads = 0.0
        if goals_mode == "selected" and goal_ids_user:
            for i, _gid in enumerate(goal_ids_user):
                idx = 2 + i
                if idx < len(mets):
                    leads += _dashboard_float_or_zero(mets[idx])
        else:
            leads = _dashboard_float_or_zero(mets[2] if len(mets) > 2 else 0.0)

        if report_is_direct_only:
            total_direct_visits += visits
            total_direct_leads += leads

        utm = str(dim_utm.get("name") or "").strip()
        cid = _dashboard_campaign_id_from_utm(utm_campaign=utm, campaign_data=campaign_data, name_index=name_index)
        if cid is None:
            if report_is_direct_only:
                key = utm or "(not set)"
                unclassified_by_utm[key] = unclassified_by_utm.get(key, 0.0) + visits
                unclassified_leads_by_utm[key] = unclassified_leads_by_utm.get(key, 0.0) + leads
            continue

        classified_visits += visits
        classified_leads += leads
        by_campaign_date.setdefault(cid, {})
        bucket = by_campaign_date[cid].setdefault(
            day, {"visits": 0.0, "bounce_sum": 0.0, "bounce_weight": 0.0, "leads": 0.0}
        )
        bucket["visits"] += visits
        bucket["bounce_sum"] += bounce * visits
        bucket["bounce_weight"] += visits
        bucket["leads"] += leads

    def _series_for_campaign(cid: str) -> dict[str, Any]:
        daily: list[dict[str, Any]] = []
        by_day = by_campaign_date.get(cid) or {}
        for day in all_days:
            vals = by_day.get(day) or {}
            visits = float(vals.get("visits") or 0.0)
            bw = float(vals.get("bounce_weight") or 0.0)
            br = float(vals.get("bounce_sum") or 0.0) / bw if bw > 0 else 0.0
            leads = float(vals.get("leads") or 0.0)
            engaged = visits * (1.0 - br / 100.0) if br >= 0 else 0.0
            daily.append({"date": day, "visits": visits, "bounceRate": br, "engaged": engaged, "leads": leads})
        return {
            "daily": daily,
            "totals": {
                "visits": _dashboard_sum([float(x.get("visits") or 0.0) for x in daily]),
                "leads": _dashboard_sum([float(x.get("leads") or 0.0) for x in daily]),
                "engaged": _dashboard_sum([float(x.get("engaged") or 0.0) for x in daily]),
                "bounce_rate": _dashboard_weighted_avg(daily, value_key="bounceRate", weight_key="visits"),
            },
        }

    top_unknown = sorted(unclassified_by_utm.items(), key=lambda x: x[1], reverse=True)[:8]
    share = (100.0 * classified_visits / total_direct_visits) if total_direct_visits > 0 else None
    leads_share = (100.0 * classified_leads / total_direct_leads) if total_direct_leads > 0 else None
    campaigns_out: dict[str, Any] = {}
    for cid in sorted(by_campaign_date.keys()):
        campaigns_out[str(cid)] = _series_for_campaign(str(cid))

    return {
        "available": True,
        "method": "utm_campaign",
        "meta": {
            "report_is_direct_only": bool(report_is_direct_only),
            "mapped_campaigns": len(campaigns_out),
            "classified_visits": classified_visits,
            "classified_leads": classified_leads,
            "total_direct_visits": (total_direct_visits if report_is_direct_only else None),
            "total_direct_leads": (total_direct_leads if report_is_direct_only else None),
            "classified_share_pct": (share if report_is_direct_only else None),
            "classified_leads_share_pct": (leads_share if report_is_direct_only else None),
            "top_unclassified_utm": (
                [
                    {"utm_campaign": k, "visits": v, "leads": float(unclassified_leads_by_utm.get(k) or 0.0)}
                    for k, v in top_unknown
                    if k
                ]
                if report_is_direct_only
                else []
            ),
        },
        "campaigns": campaigns_out,
    }


def _dashboard_build_metrica_direct_split_by_utm(
    *,
    all_days: list[str],
    report: dict[str, Any],
    campaign_data: dict[str, Any],
    goals_mode: str,
    goal_ids_user: list[str],
    report_is_direct_only: bool,
) -> dict[str, Any]:
    """Build UTMCampaign-attributed daily series split into Search/RSYA via UTMCampaign mapping.

    We intentionally do NOT combine UTMCampaign with lastsign source dimensions in one report because
    Metrica Stat API can reject some dimension combinations. Instead, we rely on the assumption
    that UTMs are applied to Direct clicks consistently (recommended: utm_campaign includes campaign_id).
    """
    rows = report.get("data")
    if not isinstance(rows, list) or not rows:
        return {"available": False, "reason": "no_data"}

    # Index by campaign name/shortName for exact matching.
    name_index: dict[str, list[str]] = {}
    for cid, camp in (campaign_data or {}).items():
        if not isinstance(camp, dict):
            continue
        for key in ("name", "shortName"):
            n = str(camp.get(key) or "").strip()
            if not n:
                continue
            name_index.setdefault(n, [])
            if cid not in name_index[n]:
                name_index[n].append(cid)

    by_date_type: dict[str, dict[str, dict[str, float]]] = {}
    total_direct_visits = 0.0
    classified_visits = 0.0
    unclassified_by_utm: dict[str, float] = {}
    total_direct_leads = 0.0
    classified_leads = 0.0
    unclassified_leads_by_utm: dict[str, float] = {}

    for row in rows:
        if not isinstance(row, dict):
            continue
        dims = row.get("dimensions")
        mets = row.get("metrics")
        if not isinstance(dims, list) or not isinstance(mets, list) or len(dims) < 2 or len(mets) < 2:
            continue

        dim_date = dims[0] if isinstance(dims[0], dict) else {"name": str(dims[0])}
        dim_utm = dims[1] if isinstance(dims[1], dict) else {"name": str(dims[1])}

        day = str(dim_date.get("name") or "")[:10]
        if not day:
            continue

        visits = _dashboard_float_or_zero(mets[0])
        bounce = _dashboard_float_or_zero(mets[1])
        leads = 0.0
        if goals_mode == "selected" and goal_ids_user:
            for i, _gid in enumerate(goal_ids_user):
                idx = 2 + i
                if idx < len(mets):
                    leads += _dashboard_float_or_zero(mets[idx])
        else:
            leads = _dashboard_float_or_zero(mets[2] if len(mets) > 2 else 0.0)

        if report_is_direct_only:
            total_direct_visits += visits
            total_direct_leads += leads

        utm = str(dim_utm.get("name") or "").strip()
        t = _dashboard_campaign_type_from_utm(utm_campaign=utm, campaign_data=campaign_data, name_index=name_index)
        if t is None:
            if report_is_direct_only:
                key = utm or "(not set)"
                unclassified_by_utm[key] = unclassified_by_utm.get(key, 0.0) + visits
                unclassified_leads_by_utm[key] = unclassified_leads_by_utm.get(key, 0.0) + leads
            continue

        classified_visits += visits
        classified_leads += leads
        by_date_type.setdefault(day, {})
        bucket = by_date_type[day].setdefault(
            t, {"visits": 0.0, "bounce_sum": 0.0, "bounce_weight": 0.0, "leads": 0.0}
        )
        bucket["visits"] += visits
        bucket["bounce_sum"] += bounce * visits
        bucket["bounce_weight"] += visits
        bucket["leads"] += leads

    def _series_for_type(t: str) -> dict[str, Any]:
        daily: list[dict[str, Any]] = []
        for day in all_days:
            vals = (by_date_type.get(day) or {}).get(t) or {}
            visits = float(vals.get("visits") or 0.0)
            bw = float(vals.get("bounce_weight") or 0.0)
            br = float(vals.get("bounce_sum") or 0.0) / bw if bw > 0 else 0.0
            leads = float(vals.get("leads") or 0.0)
            engaged = visits * (1.0 - br / 100.0) if br >= 0 else 0.0
            daily.append({"date": day, "visits": visits, "bounceRate": br, "engaged": engaged, "leads": leads})
        return {
            "daily": daily,
            "totals": {
                "visits": _dashboard_sum([float(x.get("visits") or 0.0) for x in daily]),
                "leads": _dashboard_sum([float(x.get("leads") or 0.0) for x in daily]),
                "engaged": _dashboard_sum([float(x.get("engaged") or 0.0) for x in daily]),
                "bounce_rate": _dashboard_weighted_avg(daily, value_key="bounceRate", weight_key="visits"),
            },
        }

    top_unknown = sorted(unclassified_by_utm.items(), key=lambda x: x[1], reverse=True)[:8]
    share = (100.0 * classified_visits / total_direct_visits) if total_direct_visits > 0 else None
    leads_share = (100.0 * classified_leads / total_direct_leads) if total_direct_leads > 0 else None
    return {
        "available": True,
        "method": "utm_campaign",
        "meta": {
            "report_is_direct_only": bool(report_is_direct_only),
            "classified_visits": classified_visits,
            "classified_leads": classified_leads,
            "total_direct_visits": (total_direct_visits if report_is_direct_only else None),
            "total_direct_leads": (total_direct_leads if report_is_direct_only else None),
            "classified_share_pct": (share if report_is_direct_only else None),
            "classified_leads_share_pct": (leads_share if report_is_direct_only else None),
            "top_unclassified_utm": (
                [
                    {"utm_campaign": k, "visits": v, "leads": float(unclassified_leads_by_utm.get(k) or 0.0)}
                    for k, v in top_unknown
                    if k
                ]
                if report_is_direct_only
                else []
            ),
        },
        "search": _series_for_type("search"),
        "rsya": _series_for_type("rsya"),
    }


def _dashboard_build_metrica_goals(
    *,
    all_days: list[str],
    goal_ids: list[str],
    metrica_by_date: dict[str, dict[str, Any]],
    goal_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not goal_ids:
        return {"available": False, "goal_ids": [], "goals": []}

    names = goal_names or {}
    goals: list[dict[str, Any]] = []
    for gid in goal_ids:
        daily: list[dict[str, Any]] = []
        for day in all_days:
            vals = metrica_by_date.get(day) or {}
            reaches_map = vals.get("goal_reaches") if isinstance(vals, dict) else None
            reaches = 0.0
            if isinstance(reaches_map, dict):
                reaches = float(reaches_map.get(gid) or 0.0)
            daily.append({"date": day, "reaches": reaches})
        goals.append({"id": gid, "name": names.get(gid) or f"Goal {gid}", "daily": daily})

    return {
        "available": True,
        "goal_ids": goal_ids,
        "goals": goals,
        "meta": {"days": len(all_days), "goals_count": len(goals)},
    }


def _dashboard_parse_metrica_goals_report(report: dict[str, Any]) -> tuple[dict[str, str], dict[str, dict[str, float]]]:
    """Parse Metrica Stats API report with dimensions: date + goal, metric: sumGoalReachesAny.

    Returns:
    - goal_names: {goal_id: goal_name}
    - by_date_goal: {date: {goal_id: reaches}}
    """
    goal_names: dict[str, str] = {}
    by_date_goal: dict[str, dict[str, float]] = {}
    rows = report.get("data")
    if not isinstance(rows, list):
        return goal_names, by_date_goal
    for row in rows:
        if not isinstance(row, dict):
            continue
        dims = row.get("dimensions")
        mets = row.get("metrics")
        if not isinstance(dims, list) or not isinstance(mets, list) or len(dims) < 2 or not mets:
            continue
        dim_date = dims[0] if isinstance(dims[0], dict) else {"name": str(dims[0])}
        dim_goal = dims[1] if isinstance(dims[1], dict) else {"id": "", "name": str(dims[1])}
        day = str(dim_date.get("name") or "")[:10]
        gid = str(dim_goal.get("id") or "").strip()
        gname = dim_goal.get("name")
        if not day or not gid:
            continue
        if isinstance(gname, str) and gname.strip():
            goal_names[gid] = gname.strip()
        reaches = _dashboard_float_or_zero(mets[0])
        by_date_goal.setdefault(day, {})
        by_date_goal[day][gid] = by_date_goal[day].get(gid, 0.0) + reaches
    return goal_names, by_date_goal


def _dashboard_metrica_traffic_source_key(*, source_id: str, source_name: str) -> str:
    sid = (source_id or "").strip().lower()
    sname = (source_name or "").strip().lower()
    if sid == "organic" or "поис" in sname:
        return "organic"
    if sid == "direct" or "прям" in sname:
        return "direct"
    if sid == "ad" or "реклам" in sname:
        return "ad"
    return sid or sname or "unknown"


def _dashboard_metrica_is_yandex_direct_engine(engine_name: str) -> bool:
    lowered = (engine_name or "").strip().lower()
    return ("яндекс.директ" in lowered) or ("директ" in lowered) or ("yandex" in lowered and "direct" in lowered)


def _dashboard_generate_option1(ctx: AppContext, args: dict[str, Any]) -> dict[str, Any]:
    date_from_s = str(args.get("date_from") or "").strip()
    date_to_s = str(args.get("date_to") or "").strip()
    if not date_from_s or not date_to_s:
        raise ValueError("date_from and date_to are required (YYYY-MM-DD)")

    date_from_d = _dashboard_parse_ymd(date_from_s)
    date_to_d = _dashboard_parse_ymd(date_to_s)
    warnings: list[str] = []

    today_utc = datetime.now(timezone.utc).date()
    yesterday_utc = today_utc - timedelta(days=1)
    requested_date_to_d = date_to_d
    if date_to_d >= today_utc:
        date_to_d = yesterday_utc
        warnings.append(
            f"date_to adjusted from {requested_date_to_d.isoformat()} to {date_to_d.isoformat()} "
            f"(current day data is often incomplete for Direct/Metrica)."
        )

    if date_to_d < date_from_d:
        raise ValueError("date_to must be >= date_from (after excluding current day).")

    date_from_eff_s = _dashboard_to_ymd(date_from_d)
    date_to_eff_s = _dashboard_to_ymd(date_to_d)

    # Multi-account mode: build one dashboard with a dataset per account_id (account switcher in UI).
    # Note: keep this early to avoid repeating heavy report parsing logic when generating N accounts.
    multi_account_ids: list[str] = []
    if isinstance(args.get("account_ids"), list):
        multi_account_ids = [str(x).strip() for x in (args.get("account_ids") or []) if str(x).strip()]
    if bool(args.get("all_accounts")):
        accounts = _refresh_accounts_registry(ctx)
        if not multi_account_ids:
            multi_account_ids = sorted([str(x) for x in (accounts or {}).keys() if str(x).strip()])
    if multi_account_ids:
        if args.get("account_id"):
            warnings.append("account_id ignored because account_ids/all_accounts were provided (multi-account mode).")
        # In multi-account dashboards raw payloads can explode the JSON size; keep defaults conservative.
        include_raw_multi = args.get("include_raw_reports")
        if include_raw_multi is None:
            include_raw_multi = False
            warnings.append("include_raw_reports defaulted to false for multi-account dashboard (size/speed).")

        include_html = args.get("include_html")
        output_dir = args.get("output_dir")
        if include_html is None:
            include_html = not bool(output_dir)
        return_data = args.get("return_data")
        if return_data is None:
            return_data = not bool(output_dir)

        accounts_data: dict[str, Any] = {}
        accounts_errors: list[dict[str, Any]] = []
        # Generate per-account datasets (no per-account files; one combined output).
        for account_id in multi_account_ids:
            per_args = dict(args)
            per_args.pop("account_ids", None)
            per_args.pop("all_accounts", None)
            per_args["account_id"] = account_id
            per_args["date_from"] = date_from_eff_s
            per_args["date_to"] = date_to_eff_s
            per_args["include_raw_reports"] = include_raw_multi
            per_args["include_html"] = False
            per_args["output_dir"] = None
            per_args["return_data"] = True
            try:
                per_args = _resolve_account_overrides(ctx, "dashboard.generate_option1", per_args)
                per_res = _dashboard_generate_option1(ctx, per_args)
                per_data = ((per_res.get("result") or {}).get("data")) if isinstance(per_res, dict) else None
                if not isinstance(per_data, dict):
                    raise RuntimeError("Unexpected per-account dashboard result shape.")
                accounts_data[str(account_id)] = per_data
            except Exception as e:
                accounts_errors.append({"account_id": str(account_id), "error": str(e)})

        if not accounts_data:
            errors_str = "; ".join([f"{x.get('account_id')}: {x.get('error')}" for x in accounts_errors]) or "unknown"
            raise RuntimeError(f"Failed to generate multi-account dashboard. Errors: {errors_str}")

        # Stable file base name for combined dashboard.
        base = f"yandexad_dashboard__multi__{date_from_eff_s}_{date_to_eff_s}"
        if args.get("dashboard_slug"):
            base += f"__{_dashboard_safe_slug(str(args.get('dashboard_slug')))}"

        multi_meta = {
            "generated_at": _dashboard_now_iso(),
            "date_from": date_from_eff_s,
            "date_to": date_to_eff_s,
            "requested_date_to": (date_to_s if requested_date_to_d != date_to_d else None),
            "tool": "dashboard.generate_option1",
            "multi": True,
            "account_ids": list(accounts_data.keys()),
            "default_account_id": next(iter(accounts_data.keys())),
        }

        data_multi: dict[str, Any] = {
            "meta": multi_meta,
            "accounts": accounts_data,
            "warnings": warnings,
            "accounts_errors": accounts_errors,
        }

        data_json = json.dumps(data_multi, ensure_ascii=False)
        html: str | None = None
        html_path: str | None = None
        json_path: str | None = None

        if include_html or output_dir:
            html = _dashboard_render_html(_dashboard_get_option1_template(), data_json=data_json)

        if output_dir:
            out_dir = Path(str(output_dir)).expanduser()
            out_dir.mkdir(parents=True, exist_ok=True)
            data_path = out_dir / f"{base}.json"
            page_path = out_dir / f"{base}.html"
            data_path.write_text(data_json, encoding="utf-8")
            if html is not None:
                page_path.write_text(html, encoding="utf-8")
            html_path = str(page_path)
            json_path = str(data_path)

        result: dict[str, Any] = {}
        if return_data:
            result["data"] = data_multi
        else:
            # Keep the response small when output_dir is used (Claude and other clients may hit token limits).
            compact_accounts: list[dict[str, Any]] = []
            for aid, per_data in accounts_data.items():
                per_cov = per_data.get("coverage") if isinstance(per_data, dict) else {}
                per_w = per_data.get("warnings") if isinstance(per_data, dict) else []
                compact = _dashboard_build_compact_result(per_data, warnings=per_w if isinstance(per_w, list) else [], coverage=per_cov if isinstance(per_cov, dict) else {})
                compact_accounts.append(
                    {
                        "account_id": aid,
                        "project_name": ((per_data.get("meta") or {}).get("project_name") if isinstance(per_data, dict) else None),
                        "counter_id": ((per_data.get("meta") or {}).get("counter_id") if isinstance(per_data, dict) else None),
                        "direct_client_login": ((per_data.get("meta") or {}).get("direct_client_login") if isinstance(per_data, dict) else None),
                        "summary": compact.get("summary"),
                        "warnings": per_w,
                    }
                )
            result["meta"] = multi_meta
            result["warnings"] = warnings
            result["accounts"] = compact_accounts
            if accounts_errors:
                result["accounts_errors"] = accounts_errors
        if include_html:
            result["html"] = html
        if html_path or json_path:
            result["files"] = {"html_path": html_path, "json_path": json_path}
        return {"result": result}

    day_count = (date_to_d - date_from_d).days + 1
    prev_end = date_from_d - timedelta(days=1)
    prev_start = prev_end - timedelta(days=day_count - 1)

    # Ensure the embedded dataset is sufficient for UI presets (7d/30d/week/month) *and* prev comparison.
    # The dashboard UI will compute ranges client-side from the embedded daily data.
    ref_end = date_to_d

    def _preset_start_end(period: str) -> tuple[date, date]:
        end = ref_end
        if period == "custom":
            return date_from_d, date_to_d
        if period == "30d":
            return end - timedelta(days=29), end
        if period == "week":
            monday_index = end.weekday()  # Mon=0
            return end - timedelta(days=monday_index), end
        if period == "month":
            return date(end.year, end.month, 1), end
        # default 7d
        return end - timedelta(days=6), end

    required_from = prev_start
    for p in ("custom", "7d", "30d", "week", "month"):
        start_p, end_p = _preset_start_end(p)
        day_count_p = (end_p - start_p).days + 1
        prev_end_p = start_p - timedelta(days=1)
        prev_start_p = prev_end_p - timedelta(days=day_count_p - 1)
        if prev_start_p < required_from:
            required_from = prev_start_p

    fetch_from_d = required_from
    fetch_to_d = date_to_d
    fetch_from_s = _dashboard_to_ymd(fetch_from_d)
    fetch_to_s = _dashboard_to_ymd(fetch_to_d)

    include_raw = args.get("include_raw_reports")
    if include_raw is None:
        include_raw = True
    include_html = args.get("include_html")
    output_dir = args.get("output_dir")
    if include_html is None:
        include_html = not bool(output_dir)
    return_data = args.get("return_data")
    if return_data is None:
        return_data = not bool(output_dir)

    # Direct (fetch current + previous period).
    direct_report_args: dict[str, Any] = {
        "report_type": "CAMPAIGN_PERFORMANCE_REPORT",
        "date_range_type": "CUSTOM_DATE",
        "date_from": fetch_from_s,
        "date_to": fetch_to_s,
        "field_names": ["Date", "CampaignId", "Impressions", "Clicks", "Cost"],
        "format": "TSV",
        "include_vat": "YES",
        "include_discount": "NO",
    }
    if args.get("direct_client_login"):
        direct_report_args["direct_client_login"] = args.get("direct_client_login")
    direct_report_params = _build_report_params(direct_report_args)
    direct_report = _direct_report(ctx, direct_report_params, direct_client_login=args.get("direct_client_login"))

    raw = direct_report.get("raw", "") if isinstance(direct_report, dict) else ""
    columns = direct_report.get("columns") if isinstance(direct_report, dict) else None
    parsed = _dashboard_parse_delimited(str(raw), columns=columns if isinstance(columns, list) else None)

    direct_by_date: dict[str, dict[str, float]] = {}
    direct_by_campaign_date: dict[str, dict[str, dict[str, float]]] = {}
    for row in parsed:
        ymd = (row.get("Date") or "").strip()
        cid = (row.get("CampaignId") or "").strip()
        if not ymd or not cid:
            continue
        imp = _dashboard_float_or_zero(row.get("Impressions"))
        clk = _dashboard_float_or_zero(row.get("Clicks"))
        cost_rub = _dashboard_float_or_zero(row.get("Cost"))
        direct_by_date.setdefault(ymd, {"impressions": 0.0, "clicks": 0.0, "cost_rub": 0.0})
        direct_by_date[ymd]["impressions"] += imp
        direct_by_date[ymd]["clicks"] += clk
        direct_by_date[ymd]["cost_rub"] += cost_rub

        by_d = direct_by_campaign_date.setdefault(cid, {})
        by_d.setdefault(ymd, {"impressions": 0.0, "clicks": 0.0, "cost_rub": 0.0})
        by_d[ymd]["impressions"] += imp
        by_d[ymd]["clicks"] += clk
        by_d[ymd]["cost_rub"] += cost_rub

    campaign_names: dict[str, str] = {}
    try:
        campaigns_params = _build_basic_params({"field_names": ["Id", "Name"]}, default_fields=["Id", "Name"])
        campaigns = _direct_get(ctx, "campaigns", campaigns_params, direct_client_login=args.get("direct_client_login"))
        items = (campaigns.get("result") or {}).get("Campaigns", []) if isinstance(campaigns, dict) else []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                cid = item.get("Id")
                name = item.get("Name")
                if cid is None or not isinstance(name, str):
                    continue
                campaign_names[str(cid)] = name
    except Exception:
        pass

    def _campaign_type(name: str) -> str:
        lowered = (name or "").lower()
        if "поиск" in lowered:
            return "search"
        if "рся" in lowered:
            return "rsya"
        return "unknown"

    def _campaign_short_name(name: str) -> tuple[str, str]:
        raw_name = (name or "").strip()
        if not raw_name:
            return "", ""
        # Heuristic: split by " - " and keep a compact short name + an optional subtitle.
        parts = [p.strip() for p in raw_name.split(" - ") if p.strip()]
        short = parts[0] if parts else raw_name
        sub = parts[1] if len(parts) > 1 else ""
        if len(short) > 38:
            short = short[:35].rstrip() + "…"
        return short, sub

    # Full dataset for client-side ranges (period switching, comparison, mini-charts, modal).
    direct_campaign_data: dict[str, Any] = {}
    all_days = [_dashboard_to_ymd(d) for d in _dashboard_enumerate_days(fetch_from_d, fetch_to_d)]
    for cid, by_d in direct_by_campaign_date.items():
        name = campaign_names.get(cid) or ""
        short_name, sub_name = _campaign_short_name(name)
        daily: list[dict[str, Any]] = []
        total_cost = 0.0
        total_clicks = 0.0
        total_impr = 0.0
        for day in all_days:
            vals = by_d.get(day) or {}
            imp = float(vals.get("impressions") or 0.0)
            clk = float(vals.get("clicks") or 0.0)
            cost_rub = float(vals.get("cost_rub") or 0.0)
            total_impr += imp
            total_clicks += clk
            total_cost += cost_rub
            daily.append({"date": day, "impressions": imp, "clicks": clk, "cost": cost_rub})

        # Skip completely empty campaigns to reduce payload.
        if total_impr <= 0 and total_clicks <= 0 and total_cost <= 0:
            continue

        direct_campaign_data[str(cid)] = {
            "name": name or f"#{cid}",
            "shortName": short_name or (name[:38] + "…" if len(name) > 39 else name),
            "subName": sub_name,
            "type": _campaign_type(name),
            "daily": daily,
        }

    def _direct_series(start: date, end: date) -> dict[str, Any]:
        days = _dashboard_enumerate_days(start, end)
        daily: list[dict[str, Any]] = []
        totals = {"impressions": 0.0, "clicks": 0.0, "cost_rub": 0.0}
        for d in days:
            key = _dashboard_to_ymd(d)
            vals = direct_by_date.get(key) or {}
            imp = float(vals.get("impressions") or 0.0)
            clk = float(vals.get("clicks") or 0.0)
            cost_rub = float(vals.get("cost_rub") or 0.0)
            totals["impressions"] += imp
            totals["clicks"] += clk
            totals["cost_rub"] += cost_rub
            daily.append({"date": key, "impressions": imp, "clicks": clk, "cost_rub": cost_rub})

        totals["impressions"] = float(totals["impressions"])
        totals["clicks"] = float(totals["clicks"])
        totals["cost_rub"] = float(totals["cost_rub"])
        totals["cost_micros"] = _dashboard_rub_to_micros(float(totals["cost_rub"]))
        totals["ctr"] = (
            100.0 * v
            if (v := _dashboard_safe_div(float(totals["clicks"]), float(totals["impressions"])))
            is not None
            else None
        )
        totals["cpc"] = _dashboard_safe_div(float(totals["cost_rub"]), float(totals["clicks"]))
        totals["cpm"] = (
            1000.0 * v
            if (v := _dashboard_safe_div(float(totals["cost_rub"]), float(totals["impressions"])))
            is not None
            else None
        )
        return {"daily": daily, "totals": totals}

    direct_current = _direct_series(date_from_d, date_to_d)
    direct_prev = _direct_series(prev_start, prev_end)

    # Note: per-campaign period summaries, trends, and vs-prev are computed client-side from campaign_data.

    # Metrica (fetch current + previous period).
    metrica_report: dict[str, Any] | None = None
    metrica_by_date: dict[str, dict[str, Any]] = {}
    goal_ids = args.get("goal_ids")
    goal_ids_user: list[str] = []
    if isinstance(goal_ids, list):
        goal_ids_user = [str(x).strip() for x in goal_ids if str(x).strip()]
    elif goal_ids not in (None, ""):
        goal_ids_user = [str(goal_ids).strip()] if str(goal_ids).strip() else []

    # If goal_ids are not provided, default to "all goals" via a separate Metrica report
    # (goal dimension + sumGoalReachesAny). This keeps site-wide conversions visible by default.
    goals_mode = "selected" if goal_ids_user else "all"
    goal_ids_effective: list[str] = list(goal_ids_user)
    goal_names: dict[str, str] = {}
    goal_reaches_by_date: dict[str, dict[str, float]] = {}

    base_metrics = [
        "ym:s:visits",
        "ym:s:users",
        "ym:s:bounceRate",
        "ym:s:pageDepth",
        "ym:s:avgVisitDurationSeconds",
    ]
    goal_metrics = [f"ym:s:goal{gid}reaches" for gid in goal_ids_user]
    metrics_str = ",".join(base_metrics + goal_metrics)

    try:
        metrica_args = {
            "counter_id": args.get("counter_id"),
            "date_from": fetch_from_s,
            "date_to": fetch_to_s,
            "metrics": metrics_str,
            "dimensions": "ym:s:date",
            "sort": "ym:s:date",
            "limit": 100000,
        }
        if not metrica_args.get("counter_id"):
            metrica_args.pop("counter_id", None)
        metrica_params = _build_metrica_stats_params(metrica_args)
        metrica_report = _metrica_get_stats(ctx, metrica_params)
    except Exception as exc:
        warnings.append(f"Metrica report failed: {exc.__class__.__name__}")

    if isinstance(metrica_report, dict) and isinstance(metrica_report.get("data"), list):
        for row in metrica_report["data"]:
            if not isinstance(row, dict):
                continue
            dims = row.get("dimensions")
            mets = row.get("metrics")
            if not isinstance(dims, list) or not isinstance(mets, list) or not dims or not mets:
                continue
            dim0 = dims[0]
            ymd = dim0.get("name") if isinstance(dim0, dict) else str(dim0)
            visits = _dashboard_float_or_zero(mets[0] if len(mets) > 0 else 0)
            users = _dashboard_float_or_zero(mets[1] if len(mets) > 1 else 0)
            bounce_rate = _dashboard_float_or_zero(mets[2] if len(mets) > 2 else 0)
            page_depth = _dashboard_float_or_zero(mets[3] if len(mets) > 3 else 0)
            avg_dur = _dashboard_float_or_zero(mets[4] if len(mets) > 4 else 0)
            leads = 0.0
            goal_reaches: dict[str, float] = {}
            if goal_metrics:
                for i, gid in enumerate(goal_ids_user):
                    idx = len(base_metrics) + i
                    if idx < len(mets):
                        v = _dashboard_float_or_zero(mets[idx])
                        goal_reaches[gid] = v
                        leads += v
            engaged = visits * (1.0 - (bounce_rate / 100.0)) if bounce_rate >= 0 else 0.0
            metrica_by_date[str(ymd)] = {
                "visits": visits,
                "users": users,
                "bounce_rate": bounce_rate,
                "page_depth": page_depth,
                "avg_visit_duration_seconds": avg_dur,
                "leads": leads if goal_metrics else 0.0,
                "engaged": engaged,
                "goal_reaches": goal_reaches if goal_reaches else {},
            }

    # Default all-goals conversions (when goal_ids not provided).
    metrica_goals_report: dict[str, Any] | None = None
    if goals_mode == "all":
        try:
            counter_id = args.get("counter_id")
            if counter_id:
                metrica_goals_report = _metrica_get_stats(
                    ctx,
                    {
                        "ids": str(counter_id),
                        "date1": fetch_from_s,
                        "date2": fetch_to_s,
                        "metrics": "ym:s:sumGoalReachesAny",
                        "dimensions": "ym:s:date,ym:s:goal",
                        "sort": "ym:s:date",
                        "limit": 100000,
                        "lang": "ru",
                    },
                )
                goal_names, goal_reaches_by_date = _dashboard_parse_metrica_goals_report(metrica_goals_report)
                if goal_names:
                    goal_ids_effective = list(goal_names.keys())
        except Exception as exc:
            warnings.append(f"Metrica goals(all) failed: {exc.__class__.__name__}")

    # Build metrica_by_date goal reaches (for leads totals) if we got all-goals report.
    if goal_reaches_by_date:
        for day, goals_map in goal_reaches_by_date.items():
            bucket = metrica_by_date.setdefault(
                day,
                {
                    "visits": 0.0,
                    "users": 0.0,
                    "bounce_rate": 0.0,
                    "page_depth": 0.0,
                    "avg_visit_duration_seconds": 0.0,
                    "leads": 0.0,
                    "engaged": 0.0,
                    "goal_reaches": {},
                },
            )
            if not isinstance(bucket.get("goal_reaches"), dict):
                bucket["goal_reaches"] = {}
            total_day = 0.0
            for gid, reaches in (goals_map or {}).items():
                bucket["goal_reaches"][gid] = float(bucket["goal_reaches"].get(gid) or 0.0) + float(reaches or 0.0)
                total_day += float(reaches or 0.0)
            bucket["leads"] = float(bucket.get("leads") or 0.0) + total_day

    metrica_goals: dict[str, Any] = {"available": False, "goal_ids": [], "goals": []}
    try:
        counter_id = args.get("counter_id")
        if counter_id and goal_ids_effective:
            # Best effort: map goal id -> name via Management API.
            if goals_mode == "selected":
                try:
                    goals_payload = _metrica_management_call(
                        ctx,
                        resource="goals",
                        method="get",
                        params=None,
                        data=None,
                        path_args={"counterId": str(counter_id)},
                    )
                    goals_list = None
                    if isinstance(goals_payload, dict):
                        if isinstance(goals_payload.get("goals"), list):
                            goals_list = goals_payload.get("goals")
                        elif isinstance(goals_payload.get("goals"), dict) and isinstance(
                            goals_payload["goals"].get("goals"), list
                        ):
                            goals_list = goals_payload["goals"]["goals"]
                    if isinstance(goals_list, list):
                        for g in goals_list:
                            if not isinstance(g, dict):
                                continue
                            gid = str(g.get("id") or g.get("goal_id") or g.get("goalId") or "").strip()
                            name = g.get("name")
                            if gid and isinstance(name, str) and name.strip():
                                goal_names[gid] = name.strip()
                except Exception:
                    goal_names = {}

            metrica_goals = _dashboard_build_metrica_goals(
                all_days=all_days,
                goal_ids=goal_ids_effective,
                metrica_by_date=metrica_by_date,
                goal_names=goal_names,
            )
    except Exception as exc:
        warnings.append(f"Metrica goals failed: {exc.__class__.__name__}")

    metrica_sources_report: dict[str, Any] | None = None
    metrica_sources: dict[str, Any] = {"available": False, "series": []}
    try:
        counter_id = args.get("counter_id")
        if counter_id:
            metrica_sources_params = {
                "ids": str(counter_id),
                "date1": fetch_from_s,
                "date2": fetch_to_s,
                "metrics": "ym:s:visits",
                "dimensions": "ym:s:date,ym:s:lastsignTrafficSource,ym:s:lastsignSourceEngine",
                "sort": "ym:s:date",
                "limit": 100000,
                "lang": "ru",
            }
            metrica_sources_report = _metrica_get_stats(ctx, metrica_sources_params)
            if isinstance(metrica_sources_report, dict) and isinstance(metrica_sources_report.get("data"), list):
                metrica_sources = _dashboard_build_metrica_sources(
                    all_days=all_days, report=metrica_sources_report, max_series=8
                )
    except Exception as exc:
        warnings.append(f"Metrica sources report failed: {exc.__class__.__name__}")

    metrica_direct_report: dict[str, Any] | None = None
    metrica_direct: dict[str, Any] = {"available": False}
    metrica_goals_direct: dict[str, Any] = {"available": False, "goal_ids": [], "goals": []}
    metrica_direct_split_report: dict[str, Any] | None = None
    metrica_direct_split: dict[str, Any] = {"available": False}
    try:
        counter_id = args.get("counter_id")
        picked_engine = (
            (metrica_sources.get("meta") or {}).get("picked_yandex_direct_engine") if isinstance(metrica_sources, dict) else None
        )
        if counter_id:
            # For correct CPA/conversion, attribute visits + (optional) goal reaches to Direct traffic, not all visits.
            # We fetch per-day per-source rows and then pick Yandex Direct engine (best effort) or fallback to trafficSource=ad.
            direct_goal_ids: list[str] = []
            if goals_mode == "selected" and goal_ids_user:
                direct_goal_ids = list(goal_ids_user)
                goal_metrics_src = [f"ym:s:goal{gid}reaches" for gid in direct_goal_ids]
                metrics = ",".join(["ym:s:visits", "ym:s:bounceRate"] + goal_metrics_src)
            else:
                # goals_mode == "all": keep Direct leads as "any goal reaches",
                # but also request per-goal breakdown for the top N goals (best effort) to enable dashboard drilldown.
                if goals_mode == "all" and goal_ids_effective:
                    current_days = _dashboard_enumerate_days(date_from_d, date_to_d)
                    totals: dict[str, float] = {gid: 0.0 for gid in goal_ids_effective}
                    for d in current_days:
                        day = _dashboard_to_ymd(d)
                        vals = metrica_by_date.get(day) or {}
                        gr = vals.get("goal_reaches") if isinstance(vals, dict) else None
                        if not isinstance(gr, dict):
                            continue
                        for gid in goal_ids_effective:
                            totals[gid] += float(gr.get(gid) or 0.0)
                    # Cap to avoid too many metrics in a single stats request.
                    direct_goal_ids = [
                        gid for gid, _ in sorted(totals.items(), key=lambda x: x[1], reverse=True) if gid
                    ][:7]

                goal_metrics_src = [f"ym:s:goal{gid}reaches" for gid in direct_goal_ids] if direct_goal_ids else []
                metrics = ",".join(["ym:s:visits", "ym:s:bounceRate", "ym:s:sumGoalReachesAny"] + goal_metrics_src)

            metrica_direct_params = {
                "ids": str(counter_id),
                "date1": fetch_from_s,
                "date2": fetch_to_s,
                "metrics": metrics,
                "dimensions": "ym:s:date,ym:s:lastsignTrafficSource,ym:s:lastsignSourceEngine",
                "sort": "ym:s:date",
                "limit": 100000,
                "lang": "ru",
            }
            metrica_direct_report = _metrica_get_stats(ctx, metrica_direct_params)

            by_date_direct: dict[str, dict[str, Any]] = {}
            if isinstance(metrica_direct_report, dict) and isinstance(metrica_direct_report.get("data"), list):
                for row in metrica_direct_report.get("data") or []:
                    if not isinstance(row, dict):
                        continue
                    dims = row.get("dimensions")
                    mets = row.get("metrics")
                    if not isinstance(dims, list) or not isinstance(mets, list) or len(dims) < 3 or len(mets) < 2:
                        continue
                    dim_date = dims[0] if isinstance(dims[0], dict) else {"name": str(dims[0])}
                    dim_source = dims[1] if isinstance(dims[1], dict) else {"id": "", "name": str(dims[1])}
                    dim_engine = dims[2] if isinstance(dims[2], dict) else {"id": "", "name": str(dims[2])}

                    day = str(dim_date.get("name") or "")[:10]
                    if not day:
                        continue
                    source_id = str(dim_source.get("id") or "")
                    source_name = str(dim_source.get("name") or "")
                    engine_name = str(dim_engine.get("name") or dim_engine.get("id") or "")

                    is_direct_engine = bool(picked_engine) and engine_name == str(picked_engine)
                    source_key = _dashboard_metrica_traffic_source_key(source_id=source_id, source_name=source_name)
                    is_direct_fallback = (not picked_engine) and (source_key == "ad") and _dashboard_metrica_is_yandex_direct_engine(
                        engine_name
                    )
                    is_direct = is_direct_engine or is_direct_fallback
                    if not is_direct and (not picked_engine) and source_key == "ad":
                        # If we can't identify engine reliably, consider the whole "ad" category as Direct proxy.
                        is_direct = True

                    if not is_direct:
                        continue

                    visits = _dashboard_float_or_zero(mets[0])
                    bounce = _dashboard_float_or_zero(mets[1])
                    goal_reaches: dict[str, float] = {}
                    leads = 0.0
                    if goals_mode == "selected" and goal_ids_user:
                        for i, gid in enumerate(direct_goal_ids):
                            idx = 2 + i
                            if idx < len(mets):
                                v = _dashboard_float_or_zero(mets[idx])
                                goal_reaches[gid] = v
                                leads += v
                    else:
                        leads = _dashboard_float_or_zero(mets[2] if len(mets) > 2 else 0.0)
                        if direct_goal_ids:
                            for i, gid in enumerate(direct_goal_ids):
                                idx = 3 + i
                                if idx < len(mets):
                                    v = _dashboard_float_or_zero(mets[idx])
                                    goal_reaches[gid] = float(goal_reaches.get(gid) or 0.0) + v

                    bucket = by_date_direct.setdefault(
                        day, {"visits": 0.0, "bounce_sum": 0.0, "bounce_weight": 0.0, "leads": 0.0, "goal_reaches": {}}
                    )
                    bucket["visits"] += visits
                    bucket["bounce_sum"] += bounce * visits
                    bucket["bounce_weight"] += visits
                    bucket["leads"] += leads
                    if goal_reaches:
                        gr = bucket["goal_reaches"]
                        if isinstance(gr, dict):
                            for gid, v in goal_reaches.items():
                                gr[gid] = float(gr.get(gid) or 0.0) + v

            direct_daily: list[dict[str, Any]] = []
            for day in all_days:
                vals = by_date_direct.get(day) or {}
                visits = float(vals.get("visits") or 0.0)
                bounce_w = float(vals.get("bounce_weight") or 0.0)
                bounce = float(vals.get("bounce_sum") or 0.0) / bounce_w if bounce_w > 0 else 0.0
                leads = float(vals.get("leads") or 0.0)
                engaged = visits * (1.0 - bounce / 100.0) if bounce >= 0 else 0.0
                direct_daily.append(
                    {"date": day, "visits": visits, "bounceRate": bounce, "engaged": engaged, "leads": leads}
                )

            metrica_direct = {
                "available": True,
                "basis": "sourceEngine" if picked_engine else "trafficSource",
                "engine": picked_engine,
                "goals_mode": goals_mode,
                "daily": direct_daily,
                "totals": {
                    "visits": _dashboard_sum([float(x.get("visits") or 0.0) for x in direct_daily]),
                    "leads": _dashboard_sum([float(x.get("leads") or 0.0) for x in direct_daily]),
                    "engaged": _dashboard_sum([float(x.get("engaged") or 0.0) for x in direct_daily]),
                    "bounce_rate": _dashboard_weighted_avg(direct_daily, value_key="bounceRate", weight_key="visits"),
                },
                "meta": {"picked_engine": picked_engine},
            }

            # Expose per-goal breakdown for Direct-attributed reaches.
            # - selected mode: explicit goal_ids
            # - all mode: top-N goals (best effort, capped)
            if direct_goal_ids:
                metrica_by_date_direct: dict[str, dict[str, Any]] = {}
                for day, vals in by_date_direct.items():
                    metrica_by_date_direct[day] = {"goal_reaches": vals.get("goal_reaches") or {}}
                metrica_goals_direct = _dashboard_build_metrica_goals(
                    all_days=all_days,
                    goal_ids=direct_goal_ids,
                    metrica_by_date=metrica_by_date_direct,
                    goal_names=goal_names,
                )
    except Exception as exc:
        warnings.append(f"Metrica direct attribution failed: {exc.__class__.__name__}")

    # Option C: split Direct-attributed Metrica by campaign type (search/rsya) using UTMCampaign mapping.
    metrica_direct_by_campaign: dict[str, Any] = {"available": False}
    try:
        counter_id = args.get("counter_id")
        if counter_id and direct_campaign_data:
            picked_engine = (
                (metrica_sources.get("meta") or {}).get("picked_yandex_direct_engine") if isinstance(metrica_sources, dict) else None
            )
            if goals_mode == "selected" and goal_ids_user:
                goal_metrics_src = [f"ym:s:goal{gid}reaches" for gid in goal_ids_user]
                metrics = ",".join(["ym:s:visits", "ym:s:bounceRate"] + goal_metrics_src)
            else:
                metrics = "ym:s:visits,ym:s:bounceRate,ym:s:sumGoalReachesAny"

            base_params: dict[str, Any] = {
                "ids": str(counter_id),
                "date1": fetch_from_s,
                "date2": fetch_to_s,
                "metrics": metrics,
                "dimensions": "ym:s:date,ym:s:UTMCampaign",
                "sort": "ym:s:date",
                "limit": 100000,
                "lang": "ru",
                "attribution": "lastsign",
            }
            used_direct_only = False
            params = dict(base_params)
            # Prefer a Direct-only report via lastsignSourceEngine filter, but fall back if API rejects it.
            if picked_engine:
                params["dimensions"] = "ym:s:date,ym:s:UTMCampaign,ym:s:lastsignSourceEngine"
                params["filters"] = f"ym:s:lastsignSourceEngine=={_dashboard_metrica_filter_quote(str(picked_engine))}"
                try:
                    metrica_direct_split_report = _metrica_get_stats(ctx, params)
                    used_direct_only = True
                except Exception as exc:
                    warnings.append(
                        f"Option C: UTMCampaign engine filter rejected, using unfiltered UTMCampaign report: {exc.__class__.__name__}"
                    )
                    metrica_direct_split_report = _metrica_get_stats(ctx, base_params)
            else:
                metrica_direct_split_report = _metrica_get_stats(ctx, base_params)

            if isinstance(metrica_direct_split_report, dict) and isinstance(metrica_direct_split_report.get("data"), list):
                metrica_direct_split = _dashboard_build_metrica_direct_split_by_utm(
                    all_days=all_days,
                    report=metrica_direct_split_report,
                    campaign_data=direct_campaign_data,
                    goals_mode=goals_mode,
                    goal_ids_user=goal_ids_user,
                    report_is_direct_only=used_direct_only,
                )
                metrica_direct_by_campaign = _dashboard_build_metrica_direct_by_campaign_utm(
                    all_days=all_days,
                    report=metrica_direct_split_report,
                    campaign_data=direct_campaign_data,
                    goals_mode=goals_mode,
                    goal_ids_user=goal_ids_user,
                    report_is_direct_only=used_direct_only,
                )
    except Exception as exc:
        msg = str(exc)
        warnings.append(
            f"Metrica direct split by utm failed: {exc.__class__.__name__}" + (f": {msg}" if msg else "")
        )

    def _metrica_series(start: date, end: date) -> dict[str, Any]:
        days = _dashboard_enumerate_days(start, end)
        daily: list[dict[str, Any]] = []
        for d in days:
            key = _dashboard_to_ymd(d)
            vals = metrica_by_date.get(key) or {}
            visits = float(vals.get("visits") or 0.0)
            bounce_rate = vals.get("bounce_rate")
            if bounce_rate is None:
                bounce_rate = 0.0
            bounce_rate_f = float(bounce_rate)
            engaged = float(vals.get("engaged") or (visits * (1.0 - bounce_rate_f / 100.0)))
            leads = float(vals.get("leads") or 0.0)
            daily.append(
                {
                    "date": key,
                    "visits": visits,
                    "users": float(vals.get("users") or 0.0),
                    "bounce_rate": bounce_rate_f,
                    "page_depth": float(vals.get("page_depth") or 0.0),
                    "avg_visit_duration_seconds": float(vals.get("avg_visit_duration_seconds") or 0.0),
                    "engaged": engaged,
                    "leads": leads,
                }
            )

        totals = {
            "visits": _dashboard_sum([float(x.get("visits") or 0.0) for x in daily]),
            "users": _dashboard_sum([float(x.get("users") or 0.0) for x in daily]),
            "engaged": _dashboard_sum([float(x.get("engaged") or 0.0) for x in daily]),
            "leads": _dashboard_sum([float(x.get("leads") or 0.0) for x in daily]),
            "bounce_rate": _dashboard_weighted_avg(daily, value_key="bounce_rate", weight_key="visits"),
            "page_depth": _dashboard_weighted_avg(daily, value_key="page_depth", weight_key="visits"),
            "avg_visit_duration_seconds": _dashboard_weighted_avg(
                daily, value_key="avg_visit_duration_seconds", weight_key="visits"
            ),
        }
        return {"daily": daily, "totals": totals}

    metrica_current = _metrica_series(date_from_d, date_to_d)
    metrica_prev = _metrica_series(prev_start, prev_end)

    metrica_daily_out: list[dict[str, Any]] = []
    metrica_available = bool(metrica_by_date) or (
        isinstance(metrica_report, dict) and isinstance(metrica_report.get("data"), list) and metrica_report["data"]
    )
    if metrica_available:
        for day in all_days:
            vals = metrica_by_date.get(day) or {}
            visits = float(vals.get("visits") or 0.0)
            bounce = float(vals.get("bounce_rate") or 0.0)
            avg_dur = float(vals.get("avg_visit_duration_seconds") or 0.0)
            item: dict[str, Any] = {
                "date": day,
                "visits": visits,
                "bounceRate": bounce,
                "avgDuration": avg_dur,
                "engaged": float(vals.get("engaged") or (visits * (1.0 - bounce / 100.0))),
            }
            if isinstance(metrica_goals, dict) and metrica_goals.get("available"):
                item["leads"] = float(vals.get("leads") or 0.0)
            metrica_daily_out.append(item)

    coverage = {
        "direct_current_daily": {
            "count": len(direct_current["daily"]),
            "first_date": (direct_current["daily"][0]["date"] if direct_current["daily"] else None),
            "last_date": (direct_current["daily"][-1]["date"] if direct_current["daily"] else None),
        },
        "direct_prev_daily": {
            "count": len(direct_prev["daily"]),
            "first_date": (direct_prev["daily"][0]["date"] if direct_prev["daily"] else None),
            "last_date": (direct_prev["daily"][-1]["date"] if direct_prev["daily"] else None),
        },
        "metrica_current_daily": {
            "count": len(metrica_current["daily"]),
            "first_date": (metrica_current["daily"][0]["date"] if metrica_current["daily"] else None),
            "last_date": (metrica_current["daily"][-1]["date"] if metrica_current["daily"] else None),
        },
        "metrica_prev_daily": {
            "count": len(metrica_prev["daily"]),
            "first_date": (metrica_prev["daily"][0]["date"] if metrica_prev["daily"] else None),
            "last_date": (metrica_prev["daily"][-1]["date"] if metrica_prev["daily"] else None),
        },
        "metrica_sources": {
            "available": bool(metrica_sources.get("available")),
            "series": len(metrica_sources.get("series") or []) if isinstance(metrica_sources, dict) else 0,
            "first_date": (all_days[0] if all_days else None),
            "last_date": (all_days[-1] if all_days else None),
        },
        "metrica_goals": {
            "available": bool(metrica_goals.get("available")),
            "goals": len(metrica_goals.get("goals") or []) if isinstance(metrica_goals, dict) else 0,
            "first_date": (all_days[0] if all_days else None),
            "last_date": (all_days[-1] if all_days else None),
        },
        "metrica_direct": {
            "available": bool(metrica_direct.get("available")),
            "first_date": (all_days[0] if all_days else None),
            "last_date": (all_days[-1] if all_days else None),
        },
        "metrica_direct_split": {
            "available": bool(metrica_direct_split.get("available")),
            "method": (metrica_direct_split.get("method") if isinstance(metrica_direct_split, dict) else None),
            "first_date": (all_days[0] if all_days else None),
            "last_date": (all_days[-1] if all_days else None),
        },
        "metrica_direct_by_campaign": {
            "available": bool(metrica_direct_by_campaign.get("available")),
            "method": (metrica_direct_by_campaign.get("method") if isinstance(metrica_direct_by_campaign, dict) else None),
            "first_date": (all_days[0] if all_days else None),
            "last_date": (all_days[-1] if all_days else None),
        },
        "metrica_goals_direct": {
            "available": bool(metrica_goals_direct.get("available")),
            "goals": len(metrica_goals_direct.get("goals") or []) if isinstance(metrica_goals_direct, dict) else 0,
            "first_date": (all_days[0] if all_days else None),
            "last_date": (all_days[-1] if all_days else None),
        },
    }

    ident = (args.get("account_id") or args.get("direct_client_login") or "default")
    base = f"yandexad_dashboard__{_dashboard_safe_slug(str(ident))}__{date_from_eff_s}_{date_to_eff_s}"
    if args.get("dashboard_slug"):
        base += f"__{_dashboard_safe_slug(str(args.get('dashboard_slug')))}"

    project_name: str | None = None
    account_id = args.get("account_id")
    if isinstance(account_id, str) and account_id.strip():
        profile = (ctx.config.accounts or {}).get(account_id.strip())
        if profile is not None and profile.name:
            project_name = profile.name

    data: dict[str, Any] = {
        "meta": {
            "generated_at": _dashboard_now_iso(),
            "date_from": date_from_eff_s,
            "date_to": date_to_eff_s,
            "requested_date_to": (date_to_s if requested_date_to_d != date_to_d else None),
            "prev_date_from": _dashboard_to_ymd(prev_start),
            "prev_date_to": _dashboard_to_ymd(prev_end),
            "account_id": args.get("account_id"),
            "project_name": project_name,
            "direct_client_login": args.get("direct_client_login"),
            "counter_id": args.get("counter_id"),
            "tool": "dashboard.generate_option1",
            "goals_mode": goals_mode,
            "goal_ids": goal_ids_user,
            "goals_resolved_count": (len(metrica_goals.get("goals") or []) if isinstance(metrica_goals, dict) else 0),
        },
        "coverage": coverage,
        "direct": {"current": direct_current, "prev": direct_prev, "campaign_data": direct_campaign_data},
        "metrica": {
            "current": metrica_current,
            "prev": metrica_prev,
            "daily_data": metrica_daily_out,
            "sources": metrica_sources,
            "goals": metrica_goals,
            "direct": metrica_direct,
            "direct_split": metrica_direct_split,
            "direct_by_campaign": metrica_direct_by_campaign,
            "goals_direct": metrica_goals_direct,
        },
        "warnings": warnings,
    }
    if include_raw:
        data["direct"]["raw_report"] = direct_report
        data["metrica"]["raw_report"] = metrica_report
        if metrica_sources_report is not None:
            data["metrica"]["sources_raw_report"] = metrica_sources_report
        if metrica_direct_report is not None:
            data["metrica"]["direct_raw_report"] = metrica_direct_report
        if metrica_direct_split_report is not None:
            data["metrica"]["direct_split_raw_report"] = metrica_direct_split_report

    data["recommendations"] = _dashboard_build_recommendations(data)

    data_json = json.dumps(data, ensure_ascii=False)

    html: str | None = None
    html_path: str | None = None
    json_path: str | None = None

    if include_html or output_dir:
        html = _dashboard_render_html(_dashboard_get_option1_template(), data_json=data_json)

    if output_dir:
        out_dir = Path(str(output_dir)).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        data_path = out_dir / f"{base}.json"
        page_path = out_dir / f"{base}.html"
        data_path.write_text(data_json, encoding="utf-8")
        if html is not None:
            page_path.write_text(html, encoding="utf-8")
        html_path = str(page_path)
        json_path = str(data_path)

    result: dict[str, Any] = {}
    if return_data:
        result["data"] = data
    else:
        # Keep the response small when output_dir is used (Claude and other clients may hit token limits).
        result.update(_dashboard_build_compact_result(data, warnings=warnings, coverage=coverage))
    if include_html:
        result["html"] = html
    if html_path or json_path:
        result["files"] = {"html_path": html_path, "json_path": json_path}
    return {"result": result}


def _evict_one_direct_client(ctx: AppContext) -> None:
    if not ctx.direct_clients_cache:
        return
    key = next(iter(ctx.direct_clients_cache.keys()))
    ctx.direct_clients_cache.pop(key, None)


def _select_direct_client(ctx: AppContext, direct_client_login: str | None) -> object | None:
    """Select Direct client based on per-request Client-Login override."""
    override = _normalize_direct_client_login(direct_client_login)
    default_login = _normalize_direct_client_login(ctx.config.direct_client_login)

    if override is None or override == default_login:
        return ctx.clients.direct

    with ctx.direct_clients_cache_lock:
        cached = ctx.direct_clients_cache.get(override)
        if cached is not None:
            return cached

        access_token = ctx.tokens.get_access_token()
        client = build_direct_client(ctx.config, access_token, direct_client_login=override)
        if client is None:
            return None

        if len(ctx.direct_clients_cache) >= ctx.direct_clients_cache_max_size:
            _evict_one_direct_client(ctx)
        ctx.direct_clients_cache[override] = client
        return client


@dataclass(frozen=True)
class _RequestScopedContext:
    """Per-call wrapper that can override Direct Client-Login without mutating AppContext."""

    base: AppContext
    direct_client_login: str | None

    @property
    def config(self) -> AppConfig:
        return self.base.config

    def _direct_get(self, resource: str, params: dict[str, Any]) -> dict[str, Any]:
        return _direct_get(self.base, resource, params, direct_client_login=self.direct_client_login)

    def _direct_call(self, resource: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return _direct_call(self.base, resource, method, params, direct_client_login=self.direct_client_login)

    def _direct_report(self, params: dict[str, Any]) -> dict[str, Any]:
        return _direct_report(self.base, params, direct_client_login=self.direct_client_login)

    def _metrica_get_stats(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.base._metrica_get_stats(params)

    def _metrica_logs_call(
        self,
        action: str,
        path_args: dict[str, Any],
        params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return self.base._metrica_logs_call(action, path_args, params)


def _direct_get(
    ctx: AppContext,
    resource: str,
    params: dict[str, Any],
    *,
    direct_client_login: str | None = None,
) -> dict[str, Any]:
    client = _select_direct_client(ctx, direct_client_login)
    if client is None:
        raise RuntimeError("Direct client not configured.")
    resource_client = getattr(client, resource)()
    body = {"method": "get", "params": params}

    cacheable = resource in {"dictionaries"} and ctx.cache is not None
    cache_key = ""
    if cacheable:
        login_key = _normalize_direct_client_login(direct_client_login) or _normalize_direct_client_login(
            ctx.config.direct_client_login
        )
        cache_key = (
            f"direct:{resource}:{login_key or ''}:{json.dumps(body, sort_keys=True, ensure_ascii=True)}"
        )
        cached = ctx.cache.get(cache_key)
        if isinstance(cached, dict):
            return cached

    def _call() -> dict[str, Any]:
        ctx.direct_rate_limiter.acquire()
        response = resource_client.post(data=body)
        return response.data

    data = with_retries(
        _call,
        max_attempts=ctx.config.retry_max_attempts,
        base_delay_seconds=ctx.config.retry_base_delay_seconds,
        max_delay_seconds=ctx.config.retry_max_delay_seconds,
    )
    if cacheable:
        ctx.cache.set(cache_key, data)
    return data


def _direct_call(
    ctx: AppContext,
    resource: str,
    method: str,
    params: dict[str, Any],
    *,
    direct_client_login: str | None = None,
) -> dict[str, Any]:
    client = _select_direct_client(ctx, direct_client_login)
    if client is None:
        raise RuntimeError("Direct client not configured.")
    resource_client = getattr(client, resource)()
    body = {"method": method, "params": params}

    def _call() -> dict[str, Any]:
        ctx.direct_rate_limiter.acquire()
        response = resource_client.post(data=body)
        return response.data

    return with_retries(
        _call,
        max_attempts=ctx.config.retry_max_attempts,
        base_delay_seconds=ctx.config.retry_base_delay_seconds,
        max_delay_seconds=ctx.config.retry_max_delay_seconds,
    )


def _metrica_get_management(
    ctx: AppContext, resource: str, params: dict[str, Any]
) -> dict[str, Any]:
    client = ctx.clients.metrica_management
    if client is None:
        raise RuntimeError("Metrica management client not configured.")
    resource_client = getattr(client, resource)()

    cacheable = resource in {"counters"} and ctx.cache is not None
    cache_key = ""
    if cacheable:
        cache_key = f"metrica:mgmt:{resource}:{json.dumps(params or {}, sort_keys=True, ensure_ascii=True)}"
        cached = ctx.cache.get(cache_key)
        if isinstance(cached, dict):
            return cached

    def _call() -> dict[str, Any]:
        ctx.metrica_rate_limiter.acquire()
        response = resource_client.get(params=params or None)
        return response.data

    data = with_retries(
        _call,
        max_attempts=ctx.config.retry_max_attempts,
        base_delay_seconds=ctx.config.retry_base_delay_seconds,
        max_delay_seconds=ctx.config.retry_max_delay_seconds,
    )
    if cacheable:
        ctx.cache.set(cache_key, data)
    return data


def _metrica_management_call(
    ctx: AppContext,
    resource: str,
    method: str,
    params: dict[str, Any] | None,
    data: dict[str, Any] | None,
    path_args: dict[str, Any] | None,
) -> dict[str, Any]:
    client = ctx.clients.metrica_management
    if client is None:
        raise RuntimeError("Metrica management client not configured.")
    resource_client = getattr(client, resource)(**(path_args or {}))
    call = getattr(resource_client, method)
    kwargs: dict[str, Any] = {}
    if params:
        kwargs["params"] = params
    if data:
        kwargs["data"] = data

    def _call() -> dict[str, Any]:
        ctx.metrica_rate_limiter.acquire()
        response = call(**kwargs)
        return response.data

    return with_retries(
        _call,
        max_attempts=ctx.config.retry_max_attempts,
        base_delay_seconds=ctx.config.retry_base_delay_seconds,
        max_delay_seconds=ctx.config.retry_max_delay_seconds,
    )


def _metrica_get_counter(ctx: AppContext, counter_id: str, params: dict[str, Any]) -> dict[str, Any]:
    client = ctx.clients.metrica_management
    if client is None:
        raise RuntimeError("Metrica management client not configured.")

    def _call() -> dict[str, Any]:
        ctx.metrica_rate_limiter.acquire()
        response = client.counter(counterId=counter_id).get(params=params or None)
        return response.data

    return with_retries(
        _call,
        max_attempts=ctx.config.retry_max_attempts,
        base_delay_seconds=ctx.config.retry_base_delay_seconds,
        max_delay_seconds=ctx.config.retry_max_delay_seconds,
    )


def _metrica_get_stats(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    client = ctx.clients.metrica_stats
    if client is None:
        raise RuntimeError("Metrica stats client not configured.")

    def _call() -> dict[str, Any]:
        ctx.metrica_rate_limiter.acquire()
        response = client.stats().get(params=params)
        return response.data

    return with_retries(
        _call,
        max_attempts=ctx.config.retry_max_attempts,
        base_delay_seconds=ctx.config.retry_base_delay_seconds,
        max_delay_seconds=ctx.config.retry_max_delay_seconds,
    )


def _metrica_stats_call(ctx: AppContext, method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method != "get":
        raise ValueError("Metrica stats only supports GET")
    return _metrica_get_stats(ctx, params)


def _metrica_logs_call(
    ctx: AppContext, action: str, path_args: dict[str, Any], params: dict[str, Any] | None
) -> dict[str, Any]:
    logs_client = ctx.clients.metrica_logs
    if logs_client is None:
        raise RuntimeError("Metrica logs client not configured.")
    endpoint = getattr(logs_client, action)(**path_args)

    def _call() -> Any:
        ctx.metrica_rate_limiter.acquire()
        if action in {"clean", "cancel", "create"}:
            return endpoint.post(params=params or None)
        return endpoint.get(params=params or None)

    response = with_retries(
        _call,
        max_attempts=ctx.config.retry_max_attempts,
        base_delay_seconds=ctx.config.retry_base_delay_seconds,
        max_delay_seconds=ctx.config.retry_max_delay_seconds,
    )
    data = response.data
    if isinstance(data, dict):
        return data
    payload: dict[str, Any] = {"raw": _normalize_raw_data(data)}
    columns = getattr(response, "columns", None)
    if columns:
        payload["columns"] = columns
    return payload


def _direct_report(
    ctx: AppContext,
    params: dict[str, Any],
    *,
    direct_client_login: str | None = None,
) -> dict[str, Any]:
    client = _select_direct_client(ctx, direct_client_login)
    if client is None:
        raise RuntimeError("Direct client not configured.")

    def _call() -> Any:
        ctx.direct_rate_limiter.acquire()
        return client.reports().post(data={"params": params})

    response = with_retries(
        _call,
        max_attempts=ctx.config.retry_max_attempts,
        base_delay_seconds=ctx.config.retry_base_delay_seconds,
        max_delay_seconds=ctx.config.retry_max_delay_seconds,
    )
    data = response.data
    if isinstance(data, dict):
        return data
    payload: dict[str, Any] = {"raw": _normalize_raw_data(data)}
    columns = getattr(response, "columns", None)
    if columns:
        payload["columns"] = columns
    return payload


def _build_basic_params(
    args: dict[str, Any], *, default_fields: list[str]
) -> dict[str, Any]:
    if args.get("params"):
        return args["params"]

    params: dict[str, Any] = {
        "SelectionCriteria": args.get("selection_criteria") or {},
        "FieldNames": args.get("field_names") or default_fields,
    }

    _apply_page_params(params, args.get("page"))

    return params


def _build_ids_selection_params(
    args: dict[str, Any],
    *,
    default_fields: list[str],
    ids_field: str = "Ids",
) -> dict[str, Any]:
    if args.get("params"):
        return args["params"]

    selection: dict[str, Any] = dict(args.get("selection_criteria") or {})
    ids = args.get("ids")
    if ids is not None:
        selection[ids_field] = ids

    if not selection.get(ids_field):
        raise ValueError(f"{ids_field} is required (pass ids or selection_criteria.{ids_field})")

    params: dict[str, Any] = {
        "SelectionCriteria": selection,
        "FieldNames": args.get("field_names") or default_fields,
    }
    _apply_page_params(params, args.get("page"))
    return params


def _apply_page_params(params: dict[str, Any], page: dict[str, Any] | None) -> None:
    page = page or {}
    page_limit = page.get("limit")
    page_offset = page.get("offset")
    if page_limit is None and page_offset is None:
        return
    params["Page"] = {}
    if page_limit is not None:
        params["Page"]["Limit"] = page_limit
    if page_offset is not None:
        params["Page"]["Offset"] = page_offset


def _build_campaigns_params(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("params"):
        return args["params"]

    params: dict[str, Any] = {
        "SelectionCriteria": args.get("selection_criteria") or {},
        "FieldNames": args.get("field_names") or ["Id", "Name"],
    }

    optional_fields = {
        "text_campaign_field_names": "TextCampaignFieldNames",
        "mobile_app_campaign_field_names": "MobileAppCampaignFieldNames",
        "dynamic_text_campaign_field_names": "DynamicTextCampaignFieldNames",
        "cpm_banner_campaign_field_names": "CpmBannerCampaignFieldNames",
        "smart_campaign_field_names": "SmartCampaignFieldNames",
    }
    for key, api_key in optional_fields.items():
        value = args.get(key)
        if value:
            params[api_key] = value

    _apply_page_params(params, args.get("page"))

    return params


def _build_report_params(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("params"):
        return args["params"]

    params: dict[str, Any] = {}
    if not args.get("field_names"):
        raise ValueError("field_names is required")
    if not args.get("report_type"):
        raise ValueError("report_type is required")
    if args.get("selection_criteria") is not None:
        params["SelectionCriteria"] = args.get("selection_criteria")
    date_from = args.get("date_from")
    date_to = args.get("date_to")
    if date_from is not None or date_to is not None:
        selection = params.get("SelectionCriteria")
        if selection is None:
            selection = {}
            params["SelectionCriteria"] = selection
        if not isinstance(selection, dict):
            raise ValueError("selection_criteria must be an object when date_from/date_to are provided")
        if date_from is not None:
            selection["DateFrom"] = date_from
        if date_to is not None:
            selection["DateTo"] = date_to
    if args.get("field_names") is not None:
        params["FieldNames"] = args.get("field_names")
    if args.get("order_by") is not None:
        params["OrderBy"] = args.get("order_by")
    if args.get("report_name") is not None:
        params["ReportName"] = args.get("report_name")
    else:
        selection = params.get("SelectionCriteria") or {}
        date_from = (selection.get("DateFrom") if isinstance(selection, dict) else None)
        date_to = (selection.get("DateTo") if isinstance(selection, dict) else None)
        report_type = str(args.get("report_type") or "REPORT").strip()
        suffix = ""
        if date_from and date_to:
            suffix = f"_{date_from}_{date_to}"
        params["ReportName"] = f"MCP_{report_type}{suffix}"[:255]
    if args.get("report_type") is not None:
        params["ReportType"] = args.get("report_type")
    if args.get("date_range_type") is not None:
        params["DateRangeType"] = args.get("date_range_type")
    if args.get("format") is not None:
        params["Format"] = args.get("format")
    if args.get("include_vat") is not None:
        params["IncludeVAT"] = args.get("include_vat")
    if args.get("include_discount") is not None:
        params["IncludeDiscount"] = args.get("include_discount")
    if args.get("goals") is not None:
        params["Goals"] = args.get("goals")
    if args.get("attribution_models") is not None:
        params["AttributionModels"] = args.get("attribution_models")

    return params


def _build_dictionaries_params(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("params"):
        return args["params"]
    if not args.get("dictionary_names"):
        raise ValueError("dictionary_names is required")
    return {"DictionaryNames": args.get("dictionary_names") or []}


def _build_changes_params(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("params"):
        return args["params"]
    if not args.get("timestamp"):
        raise ValueError("timestamp is required")
    params: dict[str, Any] = {}
    if args.get("timestamp") is not None:
        params["Timestamp"] = args.get("timestamp")
    if args.get("field_names") is not None:
        params["FieldNames"] = args.get("field_names")
    return params


def _build_metrica_stats_params(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("params"):
        return args["params"]
    if not args.get("counter_id"):
        raise ValueError("counter_id is required")
    if not args.get("metrics"):
        raise ValueError("metrics is required")
    params: dict[str, Any] = {}
    if args.get("counter_id") is not None:
        params["ids"] = args.get("counter_id")
    if args.get("metrics") is not None:
        params["metrics"] = args.get("metrics")
    if args.get("dimensions") is not None:
        params["dimensions"] = args.get("dimensions")
    if args.get("date_from") is not None:
        params["date1"] = args.get("date_from")
    if args.get("date_to") is not None:
        params["date2"] = args.get("date_to")
    if args.get("filters") is not None:
        params["filters"] = args.get("filters")
    if args.get("sort") is not None:
        params["sort"] = args.get("sort")
    if args.get("limit") is not None:
        params["limit"] = args.get("limit")
    if args.get("offset") is not None:
        params["offset"] = args.get("offset")
    if args.get("accuracy") is not None:
        params["accuracy"] = args.get("accuracy")
    return params


def _build_logs_params(args: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    if args.get("params"):
        params = args["params"]
    else:
        params = {}
        if args.get("date_from") is not None:
            params["date1"] = args.get("date_from")
        if args.get("date_to") is not None:
            params["date2"] = args.get("date_to")
        if args.get("fields") is not None:
            params["fields"] = args.get("fields")
        if args.get("source") is not None:
            params["source"] = args.get("source")
        if not params:
            params = None

    action = args.get("action") or "allinfo"
    if action in {"create", "evaluate"} and not params:
        raise ValueError("date_from and date_to are required for logs_export")
    if action in {"create", "evaluate"} and params:
        required_map = {
            "date1": "date_from",
            "date2": "date_to",
            "fields": "fields",
            "source": "source",
        }
        missing = [label for key, label in required_map.items() if not params.get(key)]
        if missing:
            missing_list = ", ".join(missing)
            raise ValueError(f"Missing required logs_export params: {missing_list}")
    path_args: dict[str, Any] = {}
    if args.get("counter_id") is not None:
        path_args["counterId"] = args.get("counter_id")
    if args.get("request_id") is not None:
        path_args["requestId"] = args.get("request_id")
    if args.get("part_number") is not None:
        path_args["partNumber"] = args.get("part_number")
    if "counterId" not in path_args:
        raise ValueError("counter_id is required for logs_export")
    return action, path_args, params


def _build_raw_direct_args(args: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    resource = args.get("resource")
    method = args.get("method") or "get"
    params = args.get("params") or {}
    if not resource:
        raise ValueError("resource is required")
    return resource, method, params


def _build_raw_metrica_args(
    args: dict[str, Any],
) -> tuple[str, str | None, str | None, dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    api = args.get("api") or "stats"
    resource = args.get("resource")
    method = args.get("method") or "get"
    path_args = args.get("path_args") or {}
    data = args.get("data")
    params = args.get("params")
    return api, resource, method, path_args, data, params


def _build_items_params(args: dict[str, Any], *, key: str) -> dict[str, Any]:
    if args.get("params"):
        return args["params"]
    items = args.get("items") or []
    if not items:
        raise ValueError("items is required")
    return {key: items}


def _normalize_ads_items_for_add(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize TextAd callouts for `ads.add`.

    For `ads.add`, the API accepts callout bindings via `TextAd.AdExtensions` using
    the `{"AdExtensionIds":[...]}` shape.

    We accept multiple input shapes and normalize them to the add-compatible one:
    - `TextAd.AdExtensions: {"AdExtensionIds":[...]}`
    - `TextAd.AdExtensions: [{"AdExtensionId": ...}, ...]` (read shape)
    - `TextAd.CalloutSetting.AdExtensions: [{"AdExtensionId": ...}, ...]` (update shape)
    """

    normalized: list[dict[str, Any]] = []
    for item in items:
        text_ad = item.get("TextAd")
        if not isinstance(text_ad, dict):
            normalized.append(item)
            continue

        adext_ids: list[int] = []

        callout_setting = text_ad.get("CalloutSetting")
        if isinstance(callout_setting, dict) and isinstance(callout_setting.get("AdExtensions"), list):
            for entry in callout_setting["AdExtensions"]:
                if isinstance(entry, dict) and "AdExtensionId" in entry:
                    adext_ids.append(int(entry["AdExtensionId"]))

        adext = text_ad.get("AdExtensions")
        if isinstance(adext, dict) and isinstance(adext.get("AdExtensionIds"), list):
            adext_ids.extend(int(x) for x in adext["AdExtensionIds"])
        elif isinstance(adext, list):
            for entry in adext:
                if isinstance(entry, dict) and "AdExtensionId" in entry:
                    adext_ids.append(int(entry["AdExtensionId"]))

        adext_ids = list(dict.fromkeys(adext_ids))
        if not adext_ids:
            normalized.append(item)
            continue

        new_text_ad = dict(text_ad)
        new_text_ad.pop("CalloutSetting", None)
        new_text_ad["AdExtensions"] = {"AdExtensionIds": adext_ids}
        new_item = dict(item)
        new_item["TextAd"] = new_text_ad
        normalized.append(new_item)

    return normalized


def _normalize_ads_items_for_update(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Accept older callout shapes and normalize to `CalloutSetting` for `ads.update`.

    The Direct API attaches callouts via `CalloutSetting` during updates. We accept:
    - `TextAd.AdExtensions: {"AdExtensionIds":[...]}`
    - `TextAd.AdExtensions: [{"AdExtensionId": ...}, ...]` (read shape)
    - `TextAd.CalloutSetting.AdExtensions: [...]` (already normalized)
    """

    normalized: list[dict[str, Any]] = []
    for item in items:
        text_ad = item.get("TextAd")
        if not isinstance(text_ad, dict):
            normalized.append(item)
            continue

        if "CalloutSetting" in text_ad:
            normalized.append(item)
            continue

        adext = text_ad.get("AdExtensions")
        adext_ids: list[int] | None = None

        if isinstance(adext, dict) and isinstance(adext.get("AdExtensionIds"), list):
            adext_ids = [int(x) for x in adext["AdExtensionIds"]]
        elif isinstance(adext, list):
            ids: list[int] = []
            for entry in adext:
                if isinstance(entry, dict) and "AdExtensionId" in entry:
                    ids.append(int(entry["AdExtensionId"]))
            if ids:
                adext_ids = ids

        if not adext_ids:
            normalized.append(item)
            continue

        new_text_ad = dict(text_ad)
        new_text_ad.pop("AdExtensions", None)
        new_text_ad["CalloutSetting"] = {
            "AdExtensions": [{"AdExtensionId": ext_id, "Operation": "SET"} for ext_id in adext_ids]
        }
        new_item = dict(item)
        new_item["TextAd"] = new_text_ad
        normalized.append(new_item)

    return normalized


@asynccontextmanager
async def server_lifespan(server: Server) -> AsyncIterator[AppContext]:  # noqa: ARG001
    config = load_config()
    missing = _missing_envs(config)
    if missing:
        logger.warning("Missing required auth config: %s", ", ".join(missing))

    tokens = TokenManager(config)
    access_token = tokens.get_access_token()
    clients = build_clients(config, access_token)

    cache: TTLCache | None = None
    if config.cache_enabled and config.cache_ttl_seconds > 0:
        cache = TTLCache(config.cache_ttl_seconds)

    yield AppContext(
        config=config,
        tokens=tokens,
        clients=clients,
        cache=cache,
        direct_rate_limiter=RateLimiter(config.direct_rate_limit_rps),
        metrica_rate_limiter=RateLimiter(config.metrica_rate_limit_rps),
        direct_clients_cache={},
        direct_clients_cache_lock=threading.Lock(),
    )


app = Server("yandex-direct-metrica-mcp", lifespan=server_lifespan)


@app.list_tools()
async def list_tools() -> list[Tool]:
    ctx = app.request_context.lifespan_context
    if not ctx:
        return tool_definitions()
    _refresh_accounts_registry(ctx)
    return tool_definitions(ctx.config)


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None = None) -> Any:
    ctx = app.request_context.lifespan_context
    if not ctx:
        return [TextContent(type="text", text="Server not initialized.")]

    args = arguments or {}

    if name.startswith("accounts."):
        try:
            if name == "accounts.list":
                _refresh_accounts_registry(ctx)
                return _ok_result(ctx, name, {"result": read_accounts_file(ctx.config.accounts_file)})
            if name == "accounts.reload":
                accounts = _refresh_accounts_registry(ctx, force=True)
                return _ok_result(
                    ctx,
                    name,
                    {"result": {"path": ctx.config.accounts_file, "count": len(accounts), "account_ids": sorted(accounts.keys())}},
                )
            if name in {"accounts.upsert", "accounts.delete"} and not ctx.config.accounts_write_enabled:
                raise WriteGuardError(
                    "accounts",
                    "Accounts registry write operations are disabled.",
                    "Set MCP_ACCOUNTS_WRITE_ENABLED=true to allow accounts.* write operations.",
                )
            if name == "accounts.upsert":
                result = upsert_account(
                    ctx.config.accounts_file,
                    account_id=str(args.get("account_id") or ""),
                    patch=args,
                    replace=bool(args.get("replace") or False),
                )
                _refresh_accounts_registry(ctx, force=True)
                return _ok_result(ctx, name, {"result": result})
            if name == "accounts.delete":
                result = delete_account(ctx.config.accounts_file, account_id=str(args.get("account_id") or ""))
                _refresh_accounts_registry(ctx, force=True)
                return _ok_result(ctx, name, {"result": result})
            raise ValueError(f"Unknown accounts tool: {name}")
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if ctx.clients.direct is None and name.startswith("direct."):
        return _error_response(name, MissingClientError("direct", "Direct client not configured."))
    if not (
        ctx.clients.metrica_management is not None
        or ctx.clients.metrica_stats is not None
        or ctx.clients.metrica_logs is not None
    ) and name.startswith("metrica."):
        return _error_response(name, MissingClientError("metrica", "Metrica client not configured."))

    try:
        args = _resolve_account_overrides(ctx, name, args)
    except Exception as exc:  # pragma: no cover - runtime safety
        return _error_response(name, exc)
    try:
        _enforce_write_guard(ctx.config, name, args)
    except Exception as exc:  # pragma: no cover - runtime safety
        return _error_response(name, exc)

    # Human-friendly (HF) tools.
    if name.startswith("direct.hf."):
        try:
            scoped = _RequestScopedContext(ctx, args.get("direct_client_login"))
            data = hf_direct_handle(name, scoped, args)
            return _ok_result(ctx, name, data)
        except HFError as exc:
            return _text_response(hf_payload(tool=name, status="error", message=str(exc)))
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name.startswith("metrica.hf."):
        try:
            data = hf_metrica_handle(name, ctx, args)
            return _ok_result(ctx, name, data)
        except HFError as exc:
            return _text_response(hf_payload(tool=name, status="error", message=str(exc)))
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name.startswith("join.hf."):
        try:
            scoped = _RequestScopedContext(ctx, args.get("direct_client_login"))
            data = hf_join_handle(name, scoped, args)
            return _ok_result(ctx, name, data)
        except HFError as exc:
            return _text_response(hf_payload(tool=name, status="error", message=str(exc)))
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "dashboard.generate_option1":
        try:
            data = _dashboard_generate_option1(ctx, args)
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.list_campaigns":
        try:
            params = _build_campaigns_params(args)
            data = _direct_get(ctx, "campaigns", params, direct_client_login=args.get("direct_client_login"))
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.list_adgroups":
        try:
            params = _build_basic_params(args, default_fields=["Id", "Name"])
            data = _direct_get(ctx, "adgroups", params, direct_client_login=args.get("direct_client_login"))
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.list_ads":
        try:
            params = _build_basic_params(args, default_fields=["Id", "AdGroupId"])
            data = _direct_get(ctx, "ads", params, direct_client_login=args.get("direct_client_login"))
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.list_keywords":
        try:
            params = _build_basic_params(args, default_fields=["Id", "Keyword"])
            data = _direct_get(ctx, "keywords", params, direct_client_login=args.get("direct_client_login"))
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.report":
        try:
            params = _build_report_params(args)
            data = _direct_report(ctx, params, direct_client_login=args.get("direct_client_login"))
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.list_clients":
        try:
            params = _build_basic_params(args, default_fields=["ClientId", "Login"])
            data = _direct_get(ctx, "clients", params, direct_client_login=args.get("direct_client_login"))
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.list_dictionaries":
        try:
            params = _build_dictionaries_params(args)
            data = _direct_get(ctx, "dictionaries", params, direct_client_login=args.get("direct_client_login"))
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.get_changes":
        try:
            params = _build_changes_params(args)
            data = _direct_call(
                ctx,
                "changes",
                "checkCampaigns",
                params,
                direct_client_login=args.get("direct_client_login"),
            )
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.list_sitelinks":
        try:
            params = _build_ids_selection_params(args, default_fields=["Id", "Sitelinks"])
            data = _direct_get(ctx, "sitelinks", params, direct_client_login=args.get("direct_client_login"))
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.list_vcards":
        try:
            params = _build_ids_selection_params(args, default_fields=["Id"])
            data = _direct_get(ctx, "vcards", params, direct_client_login=args.get("direct_client_login"))
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.list_adextensions":
        try:
            params = _build_basic_params(args, default_fields=["Id"])
            data = _direct_get(ctx, "adextensions", params, direct_client_login=args.get("direct_client_login"))
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.list_bids":
        try:
            params = _build_basic_params(args, default_fields=["CampaignId", "KeywordId"])
            data = _direct_get(ctx, "bids", params, direct_client_login=args.get("direct_client_login"))
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.list_bidmodifiers":
        try:
            params = _build_basic_params(args, default_fields=["CampaignId"])
            data = _direct_get(ctx, "bidmodifiers", params, direct_client_login=args.get("direct_client_login"))
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.create_campaigns":
        try:
            params = _build_items_params(args, key="Campaigns")
            data = _direct_call(ctx, "campaigns", "add", params, direct_client_login=args.get("direct_client_login"))
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.update_campaigns":
        try:
            params = _build_items_params(args, key="Campaigns")
            data = _direct_call(
                ctx, "campaigns", "update", params, direct_client_login=args.get("direct_client_login")
            )
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.create_adgroups":
        try:
            params = _build_items_params(args, key="AdGroups")
            data = _direct_call(ctx, "adgroups", "add", params, direct_client_login=args.get("direct_client_login"))
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.update_adgroups":
        try:
            params = _build_items_params(args, key="AdGroups")
            data = _direct_call(
                ctx, "adgroups", "update", params, direct_client_login=args.get("direct_client_login")
            )
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.create_ads":
        try:
            params = _build_items_params(args, key="Ads")
            params["Ads"] = _normalize_ads_items_for_add(params["Ads"])
            data = _direct_call(ctx, "ads", "add", params, direct_client_login=args.get("direct_client_login"))
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.update_ads":
        try:
            params = _build_items_params(args, key="Ads")
            params["Ads"] = _normalize_ads_items_for_update(params["Ads"])
            data = _direct_call(
                ctx, "ads", "update", params, direct_client_login=args.get("direct_client_login")
            )
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.create_keywords":
        try:
            params = _build_items_params(args, key="Keywords")
            data = _direct_call(
                ctx, "keywords", "add", params, direct_client_login=args.get("direct_client_login")
            )
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.update_keywords":
        try:
            params = _build_items_params(args, key="Keywords")
            data = _direct_call(
                ctx, "keywords", "update", params, direct_client_login=args.get("direct_client_login")
            )
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "metrica.list_counters":
        try:
            params = args.get("params") or {}
            data = _metrica_get_management(ctx, "counters", params)
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "metrica.counter_info":
        try:
            counter_id = args.get("counter_id")
            if not counter_id:
                raise ValueError("counter_id is required")
            params = args.get("params") or {}
            data = _metrica_get_counter(ctx, counter_id, params)
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "metrica.report":
        try:
            params = _build_metrica_stats_params(args)
            data = _metrica_get_stats(ctx, params)
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "metrica.logs_export":
        try:
            action, path_args, params = _build_logs_params(args)
            data = _metrica_logs_call(ctx, action, path_args, params)
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.raw_call":
        try:
            resource, method, params = _build_raw_direct_args(args)
            data = _direct_call(ctx, resource, method, params, direct_client_login=args.get("direct_client_login"))
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "metrica.raw_call":
        try:
            api, resource, method, path_args, data, params = _build_raw_metrica_args(args)
            if api == "logs":
                if not resource:
                    raise ValueError("resource is required for logs api")
                data = _metrica_logs_call(ctx, resource, path_args or {}, params)
            elif api == "management":
                if not resource:
                    raise ValueError("resource is required for management api")
                data = _metrica_management_call(ctx, resource, method, params, data, path_args)
            else:
                data = _metrica_stats_call(ctx, method, params or {})
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    # Skeleton implementation for the remaining tools.
    payload = {
        "tool": name,
        "arguments": args,
        "status": "not_implemented",
        "note": "MCP skeleton only; implement API calls next.",
    }
    return _text_response(payload)


async def run_server(transport: str = "stdio", port: int = 8000) -> None:
    if transport == "sse":
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.responses import Response
        from starlette.routing import Mount, Route
        import uvicorn

        sse = SseServerTransport("/messages/")

        async def handle_sse(request):  # type: ignore[no-untyped-def]
            async with sse.connect_sse(request.scope, request.receive, request._send) as streams:  # type: ignore[attr-defined]
                await app.run(streams[0], streams[1], app.create_initialization_options())
            return Response()

        starlette_app = Starlette(
            routes=[
                Route("/sse", endpoint=handle_sse, methods=["GET"]),
                Mount("/messages/", app=sse.handle_post_message),
            ]
        )

        uvicorn_config = uvicorn.Config(
            starlette_app,
            host="0.0.0.0",
            port=port,
            log_level="info",
        )
        uvicorn_server = uvicorn.Server(uvicorn_config)
        await uvicorn_server.serve()
        return

    from mcp.server.stdio import stdio_server

    async with stdio_server() as streams:
        await app.run(streams[0], streams[1], app.create_initialization_options())
