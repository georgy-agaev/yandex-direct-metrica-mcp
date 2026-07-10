"""MCP server for Yandex Direct + Metrica."""

import json
import logging
import os
import re
import secrets
import threading
import time
from collections.abc import AsyncIterator
from contextvars import ContextVar
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
from .campaign_diagnostics import detect_special_campaign
from .clients import YandexClients, build_clients, build_direct_client
from .config import AppConfig, load_config
from .errors import MissingClientError, NotSupportedError, ToolNotAvailableError, WriteGuardError, normalize_error
from .hf_common import HFError, hf_payload
from .hf_direct import handle as hf_direct_handle
from .hf_join import handle as hf_join_handle
from .hf_metrica import handle as hf_metrica_handle
from .hf_wordstat import handle as hf_wordstat_handle
from .hf_audience import handle as hf_audience_handle
from .plugins import try_handle as plugins_try_handle
from .ratelimit import RateLimiter
from .report_names import make_unique_report_name
from .retry import with_retries
from .search_client import (
    SEARCH_API_WEB_BASE,
    SearchApiClient,
    build_search_serp_payload,
    decode_raw_data,
    normalize_search_serp,
)
from .tools import tool_definitions
from .wordstat_client import WORDSTAT_API_BASE, WordstatClient, WordstatError
from .wordstat_utils import merge_wordstat_candidate, wordstat_provider_items
from .audience_client import AudienceClient

logger = logging.getLogger("yandex-direct-metrica-mcp")

_DASHBOARD_TEMPLATE_OPTION1_2026_01_28_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "templates" / "dashboard-template-option1-2026-02-17.html"
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

_DASHBOARD_TEMPLATE_OPTION1_2026_01_28 = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>BI Dashboard | Yandex Direct + Metrica</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,600;12..96,700;12..96,800&family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
  <style>
    :root {
      --primary: #080c18;
      --secondary: #111a33;
      --accent: #0f3460;
      --highlight: #7aa2ff;
      --success: #00d26a;
      --warning: #ffc107;
      --danger: #fb7185;
      --light: #f8f9fa;
      --text-primary: #eaf0ff;
      --text-secondary: rgba(234,240,255,.72);
      --text-muted: rgba(234,240,255,.55);
      --card-bg: rgba(255,255,255,.04);
      --card-border: rgba(255,255,255,.10);
      --grid-color: rgba(255,255,255,.08);
      --shadow: 0 12px 30px rgba(0,0,0,.22);
      --accent-subtle: rgba(122,162,255,.10);
      --success-subtle: rgba(0,210,106,.08);
      --warning-subtle: rgba(255,193,7,.08);
      --danger-subtle: rgba(251,113,133,.08);
      --font-display: 'Bricolage Grotesque', ui-sans-serif, system-ui, sans-serif;
      --font-body: 'DM Sans', -apple-system, system-ui, Segoe UI, Roboto, Arial, sans-serif;
      --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }

    [data-theme="light"] {
      --primary: #f6f7fb;
      --secondary: #ffffff;
      --accent: #e9efff;
      --text-primary: #111827;
      --text-secondary: rgba(17,24,39,.70);
      --text-muted: rgba(17,24,39,.55);
      --card-bg: rgba(255,255,255,.9);
      --card-border: rgba(17,24,39,.10);
      --grid-color: rgba(17,24,39,.10);
      --shadow: 0 10px 26px rgba(17,24,39,.10);
      --accent-subtle: rgba(122,162,255,.07);
      --success-subtle: rgba(0,210,106,.06);
      --warning-subtle: rgba(255,193,7,.06);
      --danger-subtle: rgba(251,113,133,.06);
    }

    *, *::before, *::after { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: var(--font-body);
      background: radial-gradient(1200px 800px at 20% 0%, #17214a 0%, var(--primary) 55%, #070a14 100%);
      color: var(--text-primary);
      -webkit-font-smoothing: antialiased;
      transition: background .3s, color .3s;
    }
    [data-theme="light"] body {
      background: radial-gradient(1200px 800px at 20% 0%, #e9efff 0%, var(--primary) 55%, #f6f7fb 100%);
    }

    /* Top accent bar */
    body::before {
      content: '';
      position: fixed;
      top: 0; left: 0; right: 0;
      height: 3px;
      background: linear-gradient(90deg, var(--highlight), var(--success), var(--warning));
      z-index: 100;
      pointer-events: none;
    }

    /* Dot grid texture */
    body::after {
      content: '';
      position: fixed;
      inset: 0;
      background-image: radial-gradient(circle at 1px 1px, rgba(255,255,255,.025) 1px, transparent 0);
      background-size: 28px 28px;
      pointer-events: none;
      z-index: 0;
    }
    [data-theme="light"] body::after {
      background-image: radial-gradient(circle at 1px 1px, rgba(0,0,0,.03) 1px, transparent 0);
    }

    .container { max-width: 1180px; margin: 0 auto; padding: 24px; position: relative; z-index: 1; }
    header { display: flex; gap: 14px; justify-content: space-between; align-items: flex-end; }
    h1 { margin: 0; font-size: 26px; font-family: var(--font-display); font-weight: 700; letter-spacing: -.01em; }
    .sub { margin-top: 6px; color: var(--text-secondary); font-size: 13px; }
    .meta { text-align: right; font-size: 12px; color: var(--text-secondary); line-height: 1.4; }
    .mono { font-family: var(--font-mono); }

    .toolbar { display: grid; grid-template-columns: 1fr auto; gap: 10px; align-items: start; margin-top: 14px; }
    .toolbar-left { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; min-width: 0; }
    .toolbar-right { display: flex; gap: 10px; align-items: center; justify-content: flex-end; }
    .group { display: flex; gap: 8px; align-items: center; padding: 10px 12px; border-radius: 12px; background: var(--card-bg); border: 1px solid var(--card-border); box-shadow: var(--shadow); transition: border-color .3s, background .3s; }
    .group h3 { margin: 0 10px 0 0; font-size: 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .3px; font-family: var(--font-display); font-weight: 600; }
    .btn { padding: 9px 14px; border-radius: 10px; border: 1px solid var(--card-border); background: rgba(0,0,0,.12); color: var(--text-primary); cursor: pointer; transition: transform .15s ease, background .2s ease, border-color .2s ease; font-size: 13px; font-family: var(--font-body); }
    [data-theme="light"] .btn { background: rgba(17,24,39,.04); }
    .btn:hover { transform: translateY(-1px); background: rgba(122,162,255,.14); }
    .btn.active { background: rgba(122,162,255,.22); border-color: rgba(122,162,255,.40); }
    .btn.icon { padding: 9px 12px; }
    .select { height: 36px; padding: 0 10px; border-radius: 10px; border: 1px solid var(--card-border); background: rgba(0,0,0,.12); color: var(--text-primary); outline: none; font-size: 13px; font-family: var(--font-body); min-width: 220px; max-width: 320px; transition: border-color .2s; }
    .select:focus { border-color: var(--highlight); }
    [data-theme="light"] .select { background: rgba(17,24,39,.04); }
    @media (max-width: 980px) {
      .toolbar { grid-template-columns: 1fr; }
      .toolbar-left { flex-direction: column; align-items: stretch; }
      .toolbar-right { justify-content: flex-start; flex-wrap: wrap; }
      .select { min-width: 180px; }
    }

    .grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 12px; margin-top: 12px; }
    .card { background: linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.03)); border: 1px solid var(--card-border); border-radius: 14px; padding: 14px; box-shadow: var(--shadow); transition: transform .2s ease, box-shadow .2s ease, background .3s, border-color .3s; }
    .card:hover { transform: translateY(-1px); box-shadow: 0 16px 36px rgba(0,0,0,.28); }
    .col-12 { grid-column: span 12; }
    .col-8 { grid-column: span 8; }
    .col-6 { grid-column: span 6; }
    .col-4 { grid-column: span 4; }
    .title { margin: 0 0 10px; font-size: 13px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .3px; font-weight: 700; font-family: var(--font-display); }

    .kpi-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
    @media (max-width: 980px) {
      .kpi-grid { grid-template-columns: repeat(2, 1fr); }
      .col-8, .col-6, .col-4 { grid-column: span 12; }
      header { flex-direction: column; align-items: flex-start; }
      .meta { text-align: left; }
    }
    .kpi { padding: 14px; border-radius: 12px; border: 1px solid var(--grid-color); background: rgba(0,0,0,.10); transition: border-color .3s, background .3s; }
    [data-theme="light"] .kpi { background: rgba(17,24,39,.03); }
    .kpi-label { font-size: 12px; color: var(--text-muted); display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .kpi-flag { font-size: 14px; color: var(--warning); min-width: 14px; text-align: right; }
    .kpi-value { margin-top: 6px; font-size: 24px; font-weight: 800; font-family: var(--font-display); line-height: 1.1; }
    .kpi-change { margin-top: 6px; font-size: 12px; color: var(--text-muted); transition: opacity .3s; }
    .kpi-change.positive { color: var(--success); font-weight: 600; }
    .kpi-change.negative { color: var(--danger); font-weight: 600; }
    .kpi-change.neutral { color: var(--text-muted); }

    .funnel-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
    .funnel-grid.cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    @media (max-width: 980px) { .funnel-grid { grid-template-columns: 1fr; } }
    .funnel-step { padding: 14px; border-radius: 12px; border: 1px solid var(--grid-color); background: rgba(0,0,0,.10); transition: border-color .3s, box-shadow .3s, background .3s; }
    [data-theme="light"] .funnel-step { background: rgba(17,24,39,.03); }
    .funnel-step.bottleneck { border-color: rgba(255,193,7,.55); box-shadow: 0 0 0 1px rgba(255,193,7,.20) inset; animation: bottleneckPulse 2.5s ease-in-out infinite; }
    @keyframes bottleneckPulse {
      0%, 100% { box-shadow: 0 0 0 1px rgba(255,193,7,.20) inset; }
      50% { box-shadow: 0 0 8px 2px rgba(255,193,7,.18), 0 0 0 1px rgba(255,193,7,.30) inset; }
    }
    .funnel-step.bottleneck .funnel-label::after { content: " · узкое место"; color: var(--warning); font-weight: 700; }
    .funnel-label { font-size: 12px; color: var(--text-muted); }
    .funnel-value { margin-top: 6px; font-size: 24px; font-weight: 700; font-family: var(--font-display); line-height: 1.1; }
    .funnel-rate { margin-top: 6px; font-size: 12px; color: var(--text-secondary); }
    .funnel-rate.rate-good { color: var(--success); font-weight: 600; }
    .funnel-rate.rate-medium { color: var(--warning); font-weight: 600; }
    .funnel-rate.rate-bad { color: var(--danger); font-weight: 600; }
    .funnel-section-title { font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--text-muted); margin-bottom: 8px; font-family: var(--font-display); font-weight: 600; }

    .chart-wrap { height: 380px; position: relative; }
    .chart-wrap.chart-sm { height: 300px; }
    canvas { width: 100% !important; height: 100% !important; }

    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { padding: 10px 8px; border-bottom: 1px solid var(--grid-color); vertical-align: middle; }
    th { text-align: left; color: var(--text-secondary); font-weight: 700; position: sticky; top: 0; background: var(--secondary); z-index: 2; }
    [data-theme="light"] th { background: var(--secondary); }
    tr:nth-child(even) { background: var(--accent-subtle); }
    .mini-chart { width: 150px; height: 34px; }
    .comparison-badge { display: inline-flex; gap: 6px; align-items: center; padding: 4px 8px; border-radius: 999px; border: 1px solid var(--grid-color); color: var(--text-muted); font-size: 12px; }
    .comparison-badge.up { color: var(--success); border-color: rgba(0,210,106,.35); }
    .comparison-badge.down { color: var(--danger); border-color: rgba(251,113,133,.35); }

    .campaign-name { display: flex; gap: 10px; align-items: center; }
    .campaign-icon { width: 28px; height: 28px; border-radius: 10px; display: flex; align-items: center; justify-content: center; border: 1px solid var(--grid-color); background: rgba(0,0,0,.10); }
    .campaign-icon.search { color: #7aa2ff; }
    .campaign-icon.rsya { color: #2dd4bf; }
    .campaign-row { cursor: pointer; transition: background .15s, border-color .15s; border-left: 3px solid transparent; }
    .campaign-row:hover { background: rgba(122,162,255,.10); border-left-color: var(--highlight); }

    .rec-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    @media (max-width: 980px) { .rec-grid { grid-template-columns: 1fr; } }
    .rec-card { padding: 14px; border-radius: 12px; border: 1px solid var(--grid-color); background: rgba(0,0,0,.10); }
    [data-theme="light"] .rec-card { background: rgba(17,24,39,.03); }
    .rec-card h3 { margin: 0; font-size: 14px; font-family: var(--font-display); font-weight: 700; }
    .rec-card p { margin: 6px 0 0; color: var(--text-secondary); font-size: 12px; }
    .rec-list { margin: 10px 0 0; padding-left: 18px; }
    .rec-list li { margin: 6px 0; }
    .note { color: var(--text-secondary); font-size: 12px; margin-top: 8px; }
    .pills { display: flex; flex-wrap: wrap; gap: 6px; }
    .pill { display: inline-flex; align-items: center; gap: 6px; padding: 3px 8px; border-radius: 999px; border: 1px solid var(--grid-color); color: var(--text-secondary); font-size: 12px; background: rgba(0,0,0,.10); }
    [data-theme="light"] .pill { background: rgba(17,24,39,.03); }
    .pill .muted { color: var(--text-muted); }
    .alert-card { display: none; border-left: 4px solid var(--warning); background: linear-gradient(180deg, var(--warning-subtle), rgba(255,255,255,.03)); }
    .alert-card.has-danger { border-left-color: var(--danger); background: linear-gradient(180deg, var(--danger-subtle), rgba(255,255,255,.03)); }
    .alert-list { margin: 0; padding-left: 18px; }
    .alert-list li { margin: 8px 0; }
    .alert-badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px; border: 1px solid var(--grid-color); font-size: 12px; color: var(--text-muted); font-weight: 500; }
    .alert-badge.warn { color: var(--warning); border-color: rgba(255,193,7,.35); }
    .alert-badge.danger { color: var(--danger); border-color: rgba(251,113,133,.35); }
    .sources-legend { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 10px; }
    @media (max-width: 980px) { .sources-legend { grid-template-columns: 1fr; } }
    .source-item { display: flex; justify-content: space-between; gap: 10px; padding: 10px 12px; border: 1px solid var(--card-border); border-radius: 12px; background: rgba(0,0,0,.10); }
    [data-theme="light"] .source-item { background: rgba(17,24,39,.03); }
    .source-left { display: flex; gap: 10px; align-items: center; min-width: 0; }
    .swatch { width: 10px; height: 10px; border-radius: 999px; flex: 0 0 auto; box-shadow: 0 0 0 2px rgba(0,0,0,.12); }
    .source-label { font-size: 13px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .source-val { font-size: 13px; color: var(--text-secondary); white-space: nowrap; }

    /* Modal */
    .modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.55); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px); padding: 24px; z-index: 50; }
    .modal.show { display: flex; align-items: flex-start; justify-content: center; padding-top: 48px; animation: modalFadeIn .2s ease-out; }
    @keyframes modalFadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }
    .modal-panel { max-width: 1100px; width: 100%; background: var(--secondary); border: 1px solid var(--card-border); border-radius: 14px; box-shadow: var(--shadow); padding: 20px; max-height: calc(100vh - 96px); overflow-y: auto; animation: modalSlideIn .2s ease-out; }
    @keyframes modalSlideIn {
      from { opacity: 0; transform: scale(0.97) translateY(8px); }
      to { opacity: 1; transform: scale(1) translateY(0); }
    }
    [data-theme="light"] .modal-panel { background: var(--secondary); }
    .modal-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
    .modal-title { margin: 0; font-size: 18px; font-family: var(--font-display); font-weight: 700; }
    .modal-close { border: 1px solid var(--card-border); background: rgba(0,0,0,.12); color: var(--text-primary); border-radius: 10px; padding: 6px 10px; cursor: pointer; font-size: 18px; line-height: 1; transition: background .15s; min-width: 34px; text-align: center; }
    .modal-close:hover { background: rgba(122,162,255,.14); }
    [data-theme="light"] .modal-close { background: rgba(17,24,39,.04); }
    .modal-body { margin-top: 14px; }
    .modal-grid { display: grid; grid-template-columns: 1fr; gap: 12px; }
    .small { font-size: 12px; color: var(--text-secondary); }

    /* Campaigns table mobile scroll */
    @media (max-width: 980px) {
      .table-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; position: relative; }
      .table-scroll::after {
        content: '';
        position: sticky;
        right: 0; top: 0; bottom: 0;
        width: 24px;
        background: linear-gradient(90deg, transparent, var(--primary));
        pointer-events: none;
      }
      .table-scroll table { min-width: 800px; }
    }

    /* Reduced motion */
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
    }

    /* Powered-by footer */
    .powered-by {
      margin-top: 32px;
      padding: 16px 0;
      border-top: 1px solid var(--card-border);
      text-align: center;
      font-size: 12px;
      color: var(--text-muted);
    }
    .powered-by a {
      color: var(--text-secondary);
      text-decoration: none;
      font-weight: 500;
    }
    .powered-by a:hover {
      color: var(--highlight);
      text-decoration: underline;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1 id="pageTitle">BI Dashboard</h1>
        <div class="sub">Данные: Direct + Метрика. Сравнение: vs предыдущий период той же длины.</div>
      </div>
      <div class="meta">
        <div><span class="mono" id="accountMeta">—</span></div>
        <div>Период: <span class="mono" id="periodMeta">—</span></div>
        <div>Сравнение: <span class="mono" id="compareMeta">—</span></div>
        <div>Generated: <span class="mono" id="generatedMeta">—</span></div>
      </div>
    </header>

    <div class="toolbar">
      <div class="toolbar-left">
        <div class="group">
          <h3>Период</h3>
          <button class="btn period-btn active" data-period="custom">Custom</button>
          <button class="btn period-btn" data-period="7d">7d</button>
          <button class="btn period-btn" data-period="30d">30d</button>
          <button class="btn period-btn" data-period="week">Week</button>
          <button class="btn period-btn" data-period="month">Month</button>
        </div>
        <div class="group">
          <h3>Сравнение</h3>
          <button class="btn compare-btn active" data-compare="prev">Пред. период</button>
          <button class="btn compare-btn" data-compare="none">Без сравнения</button>
        </div>
        <div class="group">
          <h3>Кампании</h3>
          <button class="btn filter-btn active" data-filter="all">Все</button>
          <button class="btn filter-btn" data-filter="search">Поиск</button>
          <button class="btn filter-btn" data-filter="rsya">РСЯ</button>
          <button class="btn filter-btn" data-filter="unclassified">Не классифицировано</button>
        </div>
      </div>
      <div class="toolbar-right">
        <div class="group" id="accountGroup" style="display:none;">
          <h3>Аккаунт</h3>
          <select class="select" id="accountSelect"></select>
        </div>
        <div class="group">
          <h3>Тема</h3>
          <button class="btn icon" id="themeToggle" title="Toggle theme"><span id="themeIcon">🌙</span></button>
        </div>
      </div>
    </div>

    <div class="grid">
      <section class="card col-12">
        <div class="title">KPI</div>
        <div class="kpi-grid">
          <div class="kpi">
            <div class="kpi-label"><span>Показы</span><span class="kpi-flag" id="flag-impressions"></span></div>
            <div class="kpi-value" id="kpi-impressions">—</div>
            <div class="kpi-change neutral" id="kpi-impressions-change">—</div>
          </div>
          <div class="kpi">
            <div class="kpi-label"><span>Клики</span><span class="kpi-flag" id="flag-clicks"></span></div>
            <div class="kpi-value" id="kpi-clicks">—</div>
            <div class="kpi-change neutral" id="kpi-clicks-change">—</div>
          </div>
          <div class="kpi">
            <div class="kpi-label"><span>CTR</span><span class="kpi-flag" id="flag-ctr"></span></div>
            <div class="kpi-value" id="kpi-ctr">—</div>
            <div class="kpi-change neutral" id="kpi-ctr-change">—</div>
          </div>
          <div class="kpi">
            <div class="kpi-label"><span>Расход</span><span class="kpi-flag" id="flag-cost"></span></div>
            <div class="kpi-value" id="kpi-cost">—</div>
            <div class="kpi-change neutral" id="kpi-cost-change">—</div>
          </div>
          <div class="kpi">
            <div class="kpi-label"><span>CPC</span><span class="kpi-flag" id="flag-cpc"></span></div>
            <div class="kpi-value" id="kpi-cpc">—</div>
            <div class="kpi-change neutral" id="kpi-cpc-change">—</div>
          </div>
          <div class="kpi">
            <div class="kpi-label"><span>Визиты (Метрика)</span><span class="kpi-flag" id="flag-visits"></span></div>
            <div class="kpi-value" id="kpi-visits">—</div>
            <div class="kpi-change neutral" id="kpi-visits-change">—</div>
          </div>
        </div>
        <div class="note" id="kpi-note"></div>
      </section>

      <section class="card col-12">
        <div class="title">Воронка конверсий</div>
        <div style="display:grid; gap: 14px;">
          <div>
            <div class="funnel-section-title">Сайт (все источники)</div>
            <div class="funnel-grid cols-3">
              <div class="funnel-step" id="step-site-visits-engaged">
                <div class="funnel-label">Визиты → Engaged</div>
                <div class="funnel-value" id="funnel-site-visits-engaged">—</div>
                <div class="funnel-rate" id="conv-site-visits-engaged">—</div>
              </div>
              <div class="funnel-step" id="step-site-engaged-leads">
                <div class="funnel-label">Engaged → Leads</div>
                <div class="funnel-value" id="funnel-site-engaged-leads">—</div>
                <div class="funnel-rate" id="conv-site-engaged-leads">—</div>
              </div>
              <div class="funnel-step" id="step-site-total">
                <div class="funnel-label">Leads (итого)</div>
                <div class="funnel-value" id="funnel-site-leads-total">—</div>
                <div class="funnel-rate" id="conv-site-total">—</div>
              </div>
            </div>
          </div>
          <div>
            <div class="funnel-section-title">Директ (атрибуция Метрики)</div>
            <div class="funnel-grid">
              <div class="funnel-step" id="step-direct-impr-clicks">
                <div class="funnel-label">Показы → Клики</div>
                <div class="funnel-value" id="funnel-direct-impr-clicks">—</div>
                <div class="funnel-rate" id="conv-direct-impressions-clicks">—</div>
              </div>
              <div class="funnel-step" id="step-direct-clicks-visits">
                <div class="funnel-label">Клики → Визиты (Direct)</div>
                <div class="funnel-value" id="funnel-direct-clicks-visits">—</div>
                <div class="funnel-rate" id="conv-direct-clicks-visits">—</div>
              </div>
              <div class="funnel-step" id="step-direct-visits-engaged">
                <div class="funnel-label">Визиты (Direct) → Engaged</div>
                <div class="funnel-value" id="funnel-direct-visits-engaged">—</div>
                <div class="funnel-rate" id="conv-direct-visits-engaged">—</div>
              </div>
              <div class="funnel-step" id="step-direct-engaged-leads">
                <div class="funnel-label">Engaged (Direct) → Leads</div>
                <div class="funnel-value" id="funnel-direct-engaged-leads">—</div>
                <div class="funnel-rate" id="conv-direct-engaged-leads">—</div>
              </div>
              <div class="funnel-step" id="step-direct-cpl">
                <div class="funnel-label">CPL (Директ)</div>
                <div class="funnel-value" id="funnel-direct-cpl">—</div>
                <div class="funnel-rate" id="conv-direct-total">—</div>
              </div>
            </div>
            <div class="note" id="directFunnelNote" style="margin-top:8px;"></div>
          </div>
        </div>
        <div class="note">Engaged = визиты × (1 − bounceRate). Leads берём из целей Метрики: если <span class="mono">goal_ids</span> не заданы — используем все цели (best effort). CPL считаем по расходу Директа.</div>
      </section>

      <section class="card col-12 alert-card" id="alertsCard">
        <div class="title">Требует внимания</div>
        <ul class="alert-list" id="alertsList"></ul>
        <div class="note" id="alertsNote"></div>
      </section>

      <section class="card col-12">
        <div class="title">Рекомендации</div>
        <div class="rec-grid">
          <div class="rec-card">
            <h3>Сделать сегодня</h3>
            <p>На основе текущих данных</p>
            <ul class="rec-list" id="todayActions"></ul>
          </div>
          <div class="rec-card">
            <h3>Вопросы для обсуждения</h3>
            <p>Гипотезы и решения</p>
            <ul class="rec-list" id="discussionQuestions"></ul>
          </div>
        </div>
        <div class="note" id="recNotes"></div>
      </section>

      <section class="card col-12" id="wordstatCard" style="display:none;">
        <div class="title">Wordstat: идеи ключей и минус-слов</div>
        <div class="note" id="wordstatNote"></div>
        <table>
          <thead>
            <tr>
              <th>Кампания</th>
              <th>Seed</th>
              <th>Идеи (топ)</th>
              <th>Минус-слова (кандидаты)</th>
            </tr>
          </thead>
          <tbody id="wordstatRows"></tbody>
        </table>
        <div class="note">Блок строится на стороне сервера при <span class="mono">include_wordstat=true</span>. Для многопроектного режима данные переключаются вместе с аккаунтом.</div>
      </section>

      <section class="card col-12" id="audienceCard" style="display:none;">
        <div class="title">Audience: сегменты и пересечения</div>
        <div class="note" id="audienceNote"></div>
        <table>
          <thead>
            <tr>
              <th>Сегмент</th>
              <th>Тип</th>
              <th>Статус</th>
              <th>Размер</th>
              <th>Обновлён</th>
              <th>Health</th>
            </tr>
          </thead>
          <tbody id="audienceRows"></tbody>
        </table>
        <div style="height:10px"></div>
        <div class="note" style="margin-bottom:8px;">Top overlaps (best effort)</div>
        <table>
          <thead>
            <tr>
              <th>A</th>
              <th>B</th>
              <th>Share</th>
              <th>Abs</th>
            </tr>
          </thead>
          <tbody id="audienceOverlapRows"></tbody>
        </table>
        <div class="note">Блок строится на стороне сервера при <span class="mono">include_audience=true</span>. Для многопроектного режима данные переключаются вместе с аккаунтом.</div>
      </section>

      <section class="card col-12" id="metricaSourcesCard">
        <div class="title">Сквозная аналитика (Метрика): визиты по источникам</div>
        <div class="chart-wrap chart-sm">
          <canvas id="sourcesChart"></canvas>
        </div>
        <div class="sources-legend" id="sourcesLegend"></div>
        <div class="note">Разрез: <span class="mono">lastSignTrafficSource + lastSignSourceEngine</span>. В легенде totals за выбранный период.</div>
      </section>

      <section class="card col-12" id="metricaGoalsCard">
        <div class="title">Конверсии (Метрика): цели</div>
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin: -4px 0 10px;">
          <span class="mono" style="color:var(--text-muted); font-size:12px;">Scope</span>
          <button class="btn goal-scope-btn" data-scope="direct">Яндекс.Директ</button>
          <button class="btn goal-scope-btn" data-scope="all">Все источники</button>
          <span class="mono" style="color:var(--text-muted); font-size:12px; margin-left:10px;">Goal</span>
          <select id="goalSelect" class="btn" style="padding:9px 10px;">
            <option value="all">Все цели</option>
          </select>
        </div>
        <div class="chart-wrap chart-sm">
          <canvas id="goalsChart"></canvas>
        </div>
        <div class="sources-legend" id="goalsLegend"></div>
        <div class="note">Достижения целей (reaches). Если <span class="mono">goal_ids</span> не заданы — используем все цели (best effort).</div>
      </section>

      <section class="card col-12">
        <div class="title">Динамика по дням</div>
        <div class="chart-wrap">
          <canvas id="dailyChart"></canvas>
        </div>
        <div class="note">Клики + расход (Direct), плюс сравнение с предыдущим периодом (если включено).</div>
      </section>

      <section class="card col-12">
        <div class="title">Активные кампании</div>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Кампания</th>
                <th>Показы</th>
                <th>Клики</th>
                <th>CTR</th>
                <th>Расход</th>
                <th>CPC</th>
                <th>Leads</th>
                <th>CPL</th>
                <th>Тренд</th>
                <th>vs Пред.</th>
              </tr>
            </thead>
            <tbody id="campaignTableBody">
              <tr><td colspan="10" style="color: var(--text-muted); padding: 18px; text-align: center;">Загрузка данных…</td></tr>
            </tbody>
          </table>
        </div>
        <div class="note" id="campaignCplNote">Клик по строке откроет детали кампании. Мини-графики рисуются из реальных дневных данных Direct.</div>
      </section>
    </div>
  </div>

  <div class="modal" id="campaignModal" role="dialog" aria-modal="true">
    <div class="modal-panel">
      <div class="modal-head">
        <div>
          <h3 class="modal-title" id="modalTitle">Campaign</h3>
          <div class="small" id="modalSubtitle">—</div>
        </div>
        <button class="modal-close" id="modalClose">&#10005;</button>
      </div>
      <div class="modal-body" id="modalBody">
        <div class="modal-grid">
          <div class="card">
            <div class="title">Воронка кампании (только Direct)</div>
            <div class="funnel-grid">
              <div class="funnel-step">
                <div class="funnel-label">Показы → Клики</div>
                <div class="funnel-value" id="m-impr-clicks">—</div>
                <div class="funnel-rate" id="m-ctr">—</div>
              </div>
              <div class="funnel-step">
                <div class="funnel-label">Клики → Расход</div>
                <div class="funnel-value" id="m-clicks-cost">—</div>
                <div class="funnel-rate" id="m-cpc">—</div>
              </div>
              <div class="funnel-step">
                <div class="funnel-label">CPC</div>
                <div class="funnel-value" id="m-cpc-only">—</div>
                <div class="funnel-rate" id="m-cost-only">—</div>
              </div>
              <div class="funnel-step">
                <div class="funnel-label">Дней в периоде</div>
                <div class="funnel-value" id="m-days">—</div>
                <div class="funnel-rate">—</div>
              </div>
              <div class="funnel-step">
                <div class="funnel-label">vs Пред. (клики)</div>
                <div class="funnel-value" id="m-vs-prev">—</div>
                <div class="funnel-rate">—</div>
              </div>
            </div>
          </div>
          <div class="card">
            <div class="title">Динамика по дням (данные Direct)</div>
            <div class="chart-wrap">
              <canvas id="modalChart"></canvas>
            </div>
            <div class="note">Клики и расход по дням внутри выбранного периода.</div>
          </div>
        </div>
      </div>
    </div>
    <div class="powered-by">
      Powered by <a href="https://github.com/georgy-agaev/yandex-direct-metrica-mcp" target="_blank" rel="noopener">yandex-direct-metrica-mcp</a>
    </div>
  </div>

  <script>
    window.__DASHBOARD_DATA__ = /*__DATA_JSON__*/;
    const ROOT = document.documentElement;
    const ROOT_DATA = window.__DASHBOARD_DATA__ || {};
    const MULTI = !!(ROOT_DATA && typeof ROOT_DATA === 'object' && ROOT_DATA.accounts && typeof ROOT_DATA.accounts === 'object');
    const MULTI_META = MULTI ? (ROOT_DATA.meta || {}) : null;
    const ACCOUNTS = MULTI ? (ROOT_DATA.accounts || {}) : null;

    let ACTIVE_ACCOUNT_ID = null;
    let DATA = MULTI ? {} : ROOT_DATA;

    let meta = {};
    let campaignData = {};
    let metricaDailyData = [];
    let metricaSources = {};
    let metricaGoals = {};
    let metricaGoalsDirect = {};
    let metricaDirect = {};
    let metricaDirectAllDaily = [];
    let metricaDirectSplit = {};
    let metricaDirectByCampaign = {};
    let wordstat = {};
    let audience = {};
    let rec = {};
    let REFERENCE_DATE = null;

    function bindData(next) {
      DATA = next && typeof next === 'object' ? next : {};
      meta = DATA.meta || {};
      campaignData = ((DATA.direct || {}).campaign_data) || {};
      metricaDailyData = ((DATA.metrica || {}).daily_data) || [];
      metricaSources = ((DATA.metrica || {}).sources) || {};
      metricaGoals = ((DATA.metrica || {}).goals) || {};
      metricaGoalsDirect = ((DATA.metrica || {}).goals_direct) || {};
      metricaDirect = (((DATA.metrica || {}).direct) || {});
      metricaDirectAllDaily = metricaDirect.daily || [];
      metricaDirectSplit = ((DATA.metrica || {}).direct_split) || {};
      metricaDirectByCampaign = ((DATA.metrica || {}).direct_by_campaign) || {};
      wordstat = (DATA.wordstat || {});
      audience = (DATA.audience || {});
      rec = DATA.recommendations || {};
      REFERENCE_DATE = getLatestDatasetDate();
    }

	    function getMetricaDirectDailyForFilter(mode) {
	      if (mode === 'all') return Array.isArray(metricaDirectAllDaily) ? metricaDirectAllDaily : [];
	      if (mode === 'unclassified') return getMetricaDirectDailyUnclassified();
	      const blk = (metricaDirectSplit && metricaDirectSplit.available) ? metricaDirectSplit[mode] : null;
	      const daily = blk && Array.isArray(blk.daily) ? blk.daily : [];
	      return daily;
	    }

	    function getMetricaDirectDailyUnclassified() {
	      const allDaily = Array.isArray(metricaDirectAllDaily) ? metricaDirectAllDaily : [];
	      const splitOk = !!(metricaDirectSplit && metricaDirectSplit.available);
	      const searchDaily = splitOk && metricaDirectSplit.search && Array.isArray(metricaDirectSplit.search.daily) ? metricaDirectSplit.search.daily : [];
	      const rsyaDaily = splitOk && metricaDirectSplit.rsya && Array.isArray(metricaDirectSplit.rsya.daily) ? metricaDirectSplit.rsya.daily : [];
	      if (!allDaily.length || !splitOk) return [];

	      const mk = (daily, field) => {
	        const m = new Map();
	        (daily || []).forEach(r => { if (r && r.date) m.set(String(r.date).slice(0,10), Number(r[field] ?? 0)); });
	        return m;
	      };
	      const vAll = mk(allDaily, 'visits');
	      const vS = mk(searchDaily, 'visits');
	      const vR = mk(rsyaDaily, 'visits');
	      const lAll = mk(allDaily, 'leads');
	      const lS = mk(searchDaily, 'leads');
	      const lR = mk(rsyaDaily, 'leads');

	      // Approximate bounce rate remainder from per-day weighted sums: bounceRate * visits.
	      const brAll = mk(allDaily, 'bounceRate');
	      const brS = mk(searchDaily, 'bounceRate');
	      const brR = mk(rsyaDaily, 'bounceRate');

	      const out = [];
	      allDaily.forEach(r => {
	        const day = String(r.date || '').slice(0,10);
	        if (!day) return;
	        const va = Number(vAll.get(day) ?? 0);
	        const vs = Number(vS.get(day) ?? 0);
	        const vr = Number(vR.get(day) ?? 0);
	        const v = Math.max(0, va - vs - vr);

	        const la = Number(lAll.get(day) ?? 0);
	        const ls = Number(lS.get(day) ?? 0);
	        const lr = Number(lR.get(day) ?? 0);
	        const leads = Math.max(0, la - ls - lr);

	        const bra = Number(brAll.get(day) ?? 0);
	        const brs = Number(brS.get(day) ?? 0);
	        const brr = Number(brR.get(day) ?? 0);
	        let bounceRate = 0;
	        if (v > 0) {
	          const num = (bra * va) - (brs * vs) - (brr * vr);
	          bounceRate = Math.max(0, Math.min(100, num / v));
	        }
	        const engaged = v * (1 - bounceRate/100);
	        out.push({ date: day, visits: v, bounceRate, engaged, leads });
	      });
	      return out;
	    }

	    // UI state
	    let currentPeriod = 'custom';
	    let compareMode = 'prev'; // prev | none
	    let filterMode = 'all'; // all | search | rsya | unclassified
    let dailyChart = null;
    let modalChart = null;
    let sourcesChart = null;
    let goalsChart = null;
    let goalsScope = 'all'; // direct | all

    function setActiveAccount(accountId, opts = {}) {
      if (!MULTI) return;
      const id = String(accountId || '').trim();
      if (!id || !ACCOUNTS || !ACCOUNTS[id]) return;
      ACTIVE_ACCOUNT_ID = id;
      localStorage.setItem('yandexad_account_id', id);
      const select = document.getElementById('accountSelect');
      if (select && select.value !== id) select.value = id;
      bindData(ACCOUNTS[id]);
      updateHeaderMeta();
      periodCache.clear();
      if (opts && opts.rerender === false) return;
      updateDashboard(currentPeriod);
      if (dailyChart) dailyChart.update();
      if (modalChart) modalChart.update();
      if (sourcesChart) sourcesChart.update();
      if (goalsChart) goalsChart.update();
    }

    function initAccountSelector() {
      if (!MULTI) {
        bindData(ROOT_DATA);
        updateHeaderMeta();
        return;
      }
      const group = document.getElementById('accountGroup');
      const select = document.getElementById('accountSelect');
      if (!group || !select) {
        // Best-effort: fall back to the first dataset.
        const ids = Object.keys(ACCOUNTS || {});
        const first = ids.length ? ids[0] : null;
        bindData(first ? ACCOUNTS[first] : {});
        updateHeaderMeta();
        return;
      }

      group.style.display = '';
      const ids = Object.keys(ACCOUNTS || {});
      const defaultId = (MULTI_META && MULTI_META.default_account_id) ? String(MULTI_META.default_account_id) : (ids[0] || '');
      const saved = localStorage.getItem('yandexad_account_id');
      const initial = ids.includes(saved) ? saved : (ids.includes(defaultId) ? defaultId : (ids[0] || ''));
      select.innerHTML = '';
      ids.forEach(id => {
        const m = ((ACCOUNTS[id] || {}).meta) || {};
        const label = m.project_name ? `${m.project_name} (${id})` : id;
        const opt = document.createElement('option');
        opt.value = id;
        opt.textContent = label;
        select.appendChild(opt);
      });
      select.value = initial;
      select.addEventListener('change', () => setActiveAccount(select.value));
      ACTIVE_ACCOUNT_ID = initial;
      bindData(ACCOUNTS[initial]);
      updateHeaderMeta();
    }

    const colorsForTheme = () => {
      const light = ROOT.getAttribute('data-theme') === 'light';
      return {
        gridColor: getComputedStyle(ROOT).getPropertyValue('--grid-color').trim() || (light ? 'rgba(17,24,39,.10)' : 'rgba(255,255,255,.08)'),
        textPrimary: getComputedStyle(ROOT).getPropertyValue('--text-primary').trim(),
        textSecondary: getComputedStyle(ROOT).getPropertyValue('--text-secondary').trim(),
      };
    };

    const fmtInt = new Intl.NumberFormat('ru-RU');
    const fmt2 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });

    const setText = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
    const esc = (s) => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\\"/g,'&quot;');

    // Theme toggle
    // Important: keep applyTheme() side-effect-free w.r.t. dashboard rendering to avoid TDZ issues
    // during initial script execution.
    function applyTheme(theme) {
      if (theme === 'light') {
        ROOT.setAttribute('data-theme', 'light');
        document.getElementById('themeIcon').textContent = '☀️';
      } else {
        ROOT.removeAttribute('data-theme');
        document.getElementById('themeIcon').textContent = '🌙';
      }
      localStorage.setItem('yandexad_theme', theme);
    }
    document.getElementById('themeToggle').addEventListener('click', () => {
      const cur = ROOT.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
      applyTheme(cur === 'light' ? 'dark' : 'light');
      updateDashboard(currentPeriod);
      if (dailyChart) dailyChart.update();
      if (modalChart) modalChart.update();
      if (sourcesChart) sourcesChart.update();
      if (goalsChart) goalsChart.update();
    });
    applyTheme(localStorage.getItem('yandexad_theme') || 'dark');

    function updateHeaderMeta() {
      const title = meta.project_name ? `${meta.project_name} — BI Dashboard` : 'BI Dashboard';
      const accountLabel = meta.project_name ? `${meta.account_id || meta.direct_client_login || '—'} (${meta.project_name})` : (meta.account_id || meta.direct_client_login || '—');
      setText('pageTitle', title);
      setText('accountMeta', accountLabel);
      setText('periodMeta', `${meta.date_from || '—'} … ${meta.date_to || '—'}`);
      setText('generatedMeta', (MULTI && MULTI_META && MULTI_META.generated_at) ? MULTI_META.generated_at : (meta.generated_at || '—'));
    }

    // Date helpers
    const parseYmd = (s) => {
      const [y,m,d] = String(s).slice(0,10).split('-').map(x => Number(x));
      return new Date(y, (m || 1) - 1, d || 1, 12, 0, 0, 0);
    };
    const toYmd = (dt) => dt.toISOString().slice(0,10);
    const addDays = (dt, days) => { const x = new Date(dt); x.setDate(x.getDate() + days); return x; };
    const enumerateDays = (start, end) => {
      const out = [];
      let cur = new Date(start);
      cur.setHours(12,0,0,0);
      const stop = new Date(end);
      stop.setHours(12,0,0,0);
      while (cur <= stop) { out.push(new Date(cur)); cur = addDays(cur, 1); }
      return out;
    };
    const formatDayLabel = (dt) => {
      const dd = String(dt.getDate()).padStart(2,'0');
      const mm = String(dt.getMonth()+1).padStart(2,'0');
      return `${dd}.${mm}`;
    };

    function getLatestDatasetDate() {
      let max = null;
      Object.values(campaignData).forEach(c => {
        (c.daily || []).forEach(d => {
          const dt = parseYmd(d.date);
          if (!max || dt > max) max = dt;
        });
      });
      (metricaDailyData || []).forEach(d => {
        const dt = parseYmd(d.date);
        if (!max || dt > max) max = dt;
      });
      if (meta.date_to) {
        const dt = parseYmd(meta.date_to);
        if (!max || dt > max) max = dt;
      }
      return max || new Date();
    }

    function getPeriodRange(period, reference = REFERENCE_DATE) {
      const end = new Date(reference || new Date());
      end.setHours(12,0,0,0);
      if (period === 'custom') {
        const s = meta.date_from ? parseYmd(meta.date_from) : addDays(end, -6);
        const e = meta.date_to ? parseYmd(meta.date_to) : end;
        return { start: s, end: e };
      }
      if (period === '30d') return { start: addDays(end, -29), end };
      if (period === 'week') {
        const mondayIndex = (end.getDay() + 6) % 7;
        return { start: addDays(end, -mondayIndex), end };
      }
      if (period === 'month') return { start: new Date(end.getFullYear(), end.getMonth(), 1, 12, 0, 0, 0), end };
      // default 7d
      return { start: addDays(end, -6), end };
    }

    function buildDailyMap(daily, field) {
      const map = new Map();
      (daily || []).forEach(row => {
        const key = String(row.date || '').slice(0,10);
        const v = Number(row[field] ?? 0);
        if (!key) return;
        map.set(key, Number.isFinite(v) ? v : 0);
      });
      return map;
    }

    function hasNumericField(daily, field) {
      return Array.isArray(daily) && daily.some(row => row && typeof row === 'object' && Number.isFinite(Number(row[field])));
    }

    function aggregateCampaignsDaily(field) {
      const map = new Map();
      Object.values(campaignData).forEach(c => {
        if (filterMode !== 'all' && (c.type || 'unknown') !== filterMode) return;
        (c.daily || []).forEach(row => {
          const key = String(row.date || '').slice(0,10);
          if (!key) return;
          const v = Number(row[field] ?? 0);
          const next = (map.get(key) ?? 0) + (Number.isFinite(v) ? v : 0);
          map.set(key, next);
        });
      });
      return map;
    }

    function buildSeriesFromMap(map, start, end) {
      const days = enumerateDays(start, end);
      return { labels: days.map(formatDayLabel), values: days.map(d => map.get(toYmd(d)) ?? 0) };
    }

    const sum = (arr) => (arr || []).reduce((a, b) => a + (Number.isFinite(Number(b)) ? Number(b) : 0), 0);

    function computeTrend(values) {
      if (!values || !values.length) return null;
      const first = Number(values[0] || 0);
      const last = Number(values[values.length - 1] || 0);
      if (first === 0) return last === 0 ? { kind: 'zero', pct: 0 } : { kind: 'inf' };
      return { kind: 'pct', pct: ((last / first) - 1) * 100 };
    }

    const periodCache = new Map();

    function renderMetricaSources(range) {
      const card = document.getElementById('metricaSourcesCard');
      const legendEl = document.getElementById('sourcesLegend');
      const canvas = document.getElementById('sourcesChart');
      if (!card || !legendEl || !canvas) return;

      const series = (metricaSources && metricaSources.available && Array.isArray(metricaSources.series)) ? metricaSources.series : [];
      if (!series.length) {
        card.style.display = 'none';
        return;
      }
      card.style.display = '';

      const days = enumerateDays(range.start, range.end);
      const labels = days.map(formatDayLabel);

      // Use clearly distinct hues; avoid "similar greens" for different series.
      const palette = [
        '#ef4444', // red
        '#f59e0b', // amber
        '#14b8a6', // teal
        '#ec4899', // pink
        '#eab308', // yellow
        '#0ea5e9', // sky
        '#f97316', // orange
        '#8b5cf6', // violet
      ];
      const colors = colorsForTheme();

      const datasets = [];
      const totals = [];
      const used = new Set();
      const pickColor = (s, idx) => {
        const key = String(s.key || '');
        const label = String(s.label || '');
        if (key === 'other') return '#94a3b8';        // slate/gray
        if (key === 'organic') return '#3b82f6';      // blue
        if (key === 'direct') return '#a855f7';       // purple
        if (/директ/i.test(label)) return '#22c55e';  // green (reserve for Yandex Direct)
        // fallback: first unused from palette
        for (let i = 0; i < palette.length; i++) {
          const c = palette[(idx + i) % palette.length];
          if (!used.has(c)) return c;
        }
        return palette[idx % palette.length];
      };
      series.forEach((s, idx) => {
        const m = new Map();
        (s.daily || []).forEach(r => { if (r && r.date) m.set(String(r.date).slice(0,10), Number(r.visits ?? 0)); });
        const values = days.map(d => m.get(toYmd(d)) ?? 0);
        const total = values.reduce((a,b) => a + (Number.isFinite(Number(b)) ? Number(b) : 0), 0);
        const color = pickColor(s, idx);
        used.add(color);
        totals.push({ label: s.label || s.key || `Series ${idx+1}`, total, color });
        datasets.push({
          label: s.label || s.key || `Series ${idx+1}`,
          data: values,
          borderColor: color,
          backgroundColor: 'transparent',
          pointRadius: 0,
          borderWidth: 2,
          tension: 0.25,
        });
      });

      totals.sort((a,b) => b.total - a.total);
      legendEl.innerHTML = totals.map(t => `
        <div class="source-item">
          <div class="source-left">
            <span class="swatch" style="background:${t.color}"></span>
            <div class="source-label" title="${String(t.label).replace(/\\"/g,'&quot;')}">${String(t.label)}</div>
          </div>
          <div class="source-val">${fmtInt.format(Math.round(t.total))}</div>
        </div>
      `).join('');

      if (sourcesChart) {
        sourcesChart.destroy();
        sourcesChart = null;
      }
      if (typeof Chart === 'undefined') return;

      sourcesChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: { labels, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { color: colors.gridColor }, ticks: { color: colors.textSecondary } },
            y: { grid: { color: colors.gridColor }, ticks: { color: colors.textSecondary } },
          },
        }
      });
    }

    function renderMetricaGoals(range) {
      const card = document.getElementById('metricaGoalsCard');
      const legendEl = document.getElementById('goalsLegend');
      const canvas = document.getElementById('goalsChart');
      const goalSelect = document.getElementById('goalSelect');
      if (!card || !legendEl || !canvas) return;

      const directAvailable = !!(metricaGoalsDirect && metricaGoalsDirect.available && Array.isArray(metricaGoalsDirect.goals) && metricaGoalsDirect.goals.length);
      if (goalsScope === 'direct' && !directAvailable) goalsScope = 'all';
      const src = (goalsScope === 'direct' && directAvailable) ? metricaGoalsDirect : metricaGoals;
      const goals = (src && src.available && Array.isArray(src.goals)) ? src.goals : [];
      if (!goals.length) {
        card.style.display = 'none';
        return;
      }
      card.style.display = '';

      // Toggle buttons state
      document.querySelectorAll('.goal-scope-btn').forEach(btn => {
        const scope = btn.dataset.scope;
        btn.classList.toggle('active', scope === goalsScope);
        if (scope === 'direct') {
          btn.disabled = !directAvailable;
          btn.style.opacity = directAvailable ? '1' : '0.5';
          btn.style.cursor = directAvailable ? 'pointer' : 'not-allowed';
        }
      });

      // Populate goal selector (best effort) once per scope/source
      if (goalSelect) {
        const currentValue = goalSelect.value || 'all';
        const key = `${goalsScope}::${goals.map(g => g.id).join(',')}`;
        if (goalSelect.dataset.key !== key) {
          const options = ['<option value="all">Все цели</option>'];
          goals.forEach(g => {
            const id = g.id || '';
            const name = g.name || (id ? `Goal ${id}` : 'Goal');
            const safeName = String(name).replace(/</g,'&lt;').replace(/>/g,'&gt;');
            options.push(`<option value="${String(id).replace(/\\"/g,'&quot;')}">${safeName}</option>`);
          });
          goalSelect.innerHTML = options.join('');
          goalSelect.dataset.key = key;
          // restore selection when possible; default to "all"
          const exists = Array.from(goalSelect.options).some(o => o.value === currentValue);
          goalSelect.value = exists ? currentValue : 'all';
        }
      }
      const selectedGoalId = goalSelect ? (goalSelect.value || 'all') : 'all';

      const days = enumerateDays(range.start, range.end);
      const labels = days.map(formatDayLabel);
      const dayCount = days.length;
      const prevEnd = addDays(range.start, -1);
      const prevStart = addDays(prevEnd, -(dayCount - 1));
      const prevDays = enumerateDays(prevStart, prevEnd);

      const palette = [
        '#00d26a', '#7aa2ff', '#fb7185', '#ffc107', '#a78bfa', '#38bdf8', '#f472b6', '#22c55e',
      ];
      const colors = colorsForTheme();

      const isDirectScope = (goalsScope === 'direct' && directAvailable);
      const directLeadsMap = (isDirectScope && metricaDirectAllDaily && metricaDirectAllDaily.length && hasNumericField(metricaDirectAllDaily, 'leads'))
        ? buildDailyMap(metricaDirectAllDaily, 'leads')
        : null;

      // Build per-goal series values for the current period, and compute totals for sorting.
      const tmp = goals.map((g, idx) => {
        const m = new Map();
        (g.daily || []).forEach(r => { if (r && r.date) m.set(String(r.date).slice(0,10), Number(r.reaches ?? 0)); });
        const values = days.map(d => m.get(toYmd(d)) ?? 0);
        const totalCur = values.reduce((a,b) => a + (Number.isFinite(Number(b)) ? Number(b) : 0), 0);
        const totalPrev = prevDays.reduce((a,d) => a + (Number.isFinite(Number(m.get(toYmd(d)) ?? 0)) ? Number(m.get(toYmd(d)) ?? 0) : 0), 0);
        return {
          idx,
          id: g.id || '',
          label: g.name || `Goal ${g.id || idx}`,
          map: m,
          values,
          totalCur,
          totalPrev,
        };
      });

      // Keep chart readable: show top 7 goals + "Other goals" remainder.
      tmp.sort((a,b) => b.totalCur - a.totalCur);
      const maxGoals = 7;
      const shown = tmp.slice(0, maxGoals);
      const hidden = tmp.slice(maxGoals);

      const datasets = [];
      const legend = [];
      let anyTotalCur = null;
      let anyTotalPrev = null;

      // For the chart: either aggregate ("all") or a single selected goal.
      if (selectedGoalId === 'all') {
        let allValues = null;
        let prevValues = null;
        if (isDirectScope && directLeadsMap) {
          allValues = days.map(d => directLeadsMap.get(toYmd(d)) ?? 0);
          prevValues = prevDays.map(d => directLeadsMap.get(toYmd(d)) ?? 0);
          anyTotalCur = sum(allValues);
          anyTotalPrev = sum(prevValues);
        } else {
          allValues = labels.map((_, j) => tmp.reduce((acc, g) => acc + (Number(g.values[j]) || 0), 0));
          prevValues = prevDays.map(d => tmp.reduce((acc, g) => acc + (Number(g.map.get(toYmd(d)) ?? 0) || 0), 0));
          anyTotalCur = sum(allValues);
          anyTotalPrev = sum(prevValues);
        }
        datasets.push({
          label: 'Все цели',
          data: allValues,
          borderColor: '#00d26a',
          backgroundColor: 'transparent',
          pointRadius: 0,
          borderWidth: 2,
          tension: 0.25,
        });
        if (compareMode === 'prev') {
          datasets.push({
            label: 'Все цели (пред.)',
            data: prevValues,
            borderColor: 'rgba(0,210,106,0.35)',
            borderDash: [6, 6],
            backgroundColor: 'transparent',
            pointRadius: 0,
            borderWidth: 2,
            tension: 0.25,
          });
        }
        legend.push({ label: 'Все цели', totalCur: anyTotalCur, totalPrev: anyTotalPrev, color: '#00d26a' });
      } else {
        const picked = tmp.find(g => String(g.id) === String(selectedGoalId));
        if (picked) {
          datasets.push({
            label: picked.label,
            data: picked.values,
            borderColor: '#00d26a',
            backgroundColor: 'transparent',
            pointRadius: 0,
            borderWidth: 2,
            tension: 0.25,
          });
          if (compareMode === 'prev') {
            const pickedPrev = prevDays.map(d => picked.map.get(toYmd(d)) ?? 0);
            datasets.push({
              label: `${picked.label} (пред.)`,
              data: pickedPrev,
              borderColor: 'rgba(0,210,106,0.35)',
              borderDash: [6, 6],
              backgroundColor: 'transparent',
              pointRadius: 0,
              borderWidth: 2,
              tension: 0.25,
            });
          }
          legend.push({ label: picked.label, totalCur: picked.totalCur, totalPrev: picked.totalPrev, color: '#00d26a' });
        }
      }

      // Below-chart breakdown: always show per-goal totals (top 7 + other), regardless of chart selection.
      const breakdown = [];
      shown.forEach((g, i) => breakdown.push({ label: g.label, totalCur: g.totalCur, totalPrev: g.totalPrev, color: palette[i % palette.length] }));
      const subsetTotalCur = tmp.reduce((acc, g) => acc + (Number.isFinite(Number(g.totalCur)) ? Number(g.totalCur) : 0), 0);
      const subsetTotalPrev = tmp.reduce((acc, g) => acc + (Number.isFinite(Number(g.totalPrev)) ? Number(g.totalPrev) : 0), 0);
      let otherTotalCur = hidden.reduce((acc, g) => acc + (Number.isFinite(Number(g.totalCur)) ? Number(g.totalCur) : 0), 0);
      let otherTotalPrev = hidden.reduce((acc, g) => acc + (Number.isFinite(Number(g.totalPrev)) ? Number(g.totalPrev) : 0), 0);
      // In Direct scope, "Все цели" can be derived from sumGoalReachesAny, while we may only have top-N goals in breakdown.
      if (isDirectScope && selectedGoalId === 'all' && Number.isFinite(Number(anyTotalCur)) && Number.isFinite(Number(anyTotalPrev))) {
        const missCur = Math.max(0, Number(anyTotalCur) - subsetTotalCur);
        const missPrev = Math.max(0, Number(anyTotalPrev) - subsetTotalPrev);
        otherTotalCur += missCur;
        otherTotalPrev += missPrev;
      }
      if (otherTotalCur > 0 || otherTotalPrev > 0) {
        breakdown.push({ label: 'Другие цели', totalCur: otherTotalCur, totalPrev: otherTotalPrev, color: 'rgba(234,240,255,.55)' });
      }

      legendEl.innerHTML = breakdown.map(t => {
        let deltaHtml = '';
        if (compareMode === 'prev') {
          const prev = Number(t.totalPrev || 0);
          const cur = Number(t.totalCur || 0);
          let pct = null;
          if (prev === 0) pct = (cur === 0) ? 0 : null;
          else pct = ((cur / prev) - 1) * 100;
          const cls = (pct === null) ? 'neutral' : (pct === 0 ? 'neutral' : (pct > 0 ? 'up' : 'down'));
          const txt = (pct === null) ? '∞' : `${pct > 0 ? '+' : ''}${fmt2.format(pct)}%`;
          deltaHtml = ` <span class="comparison-badge ${cls}">${txt}</span>`;
        }
        return `
          <div class="source-item">
            <div class="source-left">
              <span class="swatch" style="background:${t.color}"></span>
              <div class="source-label" title="${String(t.label).replace(/\\"/g,'&quot;')}">${String(t.label)}</div>
            </div>
            <div class="source-val">${fmtInt.format(Math.round(t.totalCur))}${deltaHtml}</div>
          </div>
        `;
      }).join('');

      if (goalsChart) {
        goalsChart.destroy();
        goalsChart = null;
      }
      if (typeof Chart === 'undefined') return;

      goalsChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: { labels, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: { legend: { display: false } },
          scales: {
            x: { grid: { color: colors.gridColor }, ticks: { color: colors.textSecondary } },
            y: { grid: { color: colors.gridColor }, ticks: { color: colors.textSecondary } },
          },
        }
      });
    }

    function getOverallPeriodData(period) {
      if (periodCache.has(period)) return periodCache.get(period);

      const range = getPeriodRange(period);
      const dayCount = enumerateDays(range.start, range.end).length;
      const prevEnd = addDays(range.start, -1);
      const prevStart = addDays(prevEnd, -(dayCount - 1));

      const impMap = aggregateCampaignsDaily('impressions');
      const clkMap = aggregateCampaignsDaily('clicks');
      const cstMap = aggregateCampaignsDaily('cost');

      const metMap = metricaDailyData && metricaDailyData.length ? buildDailyMap(metricaDailyData, 'visits') : null;
      const bounceMap = metricaDailyData && metricaDailyData.length ? buildDailyMap(metricaDailyData, 'bounceRate') : null;
      const durMap = metricaDailyData && metricaDailyData.length ? buildDailyMap(metricaDailyData, 'avgDuration') : null;
	      const engagedMap = (metricaDailyData && hasNumericField(metricaDailyData, 'engaged')) ? buildDailyMap(metricaDailyData, 'engaged') : null;
	      const leadMap = (metricaDailyData && hasNumericField(metricaDailyData, 'leads')) ? buildDailyMap(metricaDailyData, 'leads') : null;

	      const directDailyEffective = getMetricaDirectDailyForFilter(filterMode);
	      const directDailyUnclassified = (filterMode === 'unclassified') ? getMetricaDirectDailyUnclassified() : [];
	      const directDailyEffectiveFinal = (filterMode === 'unclassified') ? directDailyUnclassified : directDailyEffective;
	      const directDailyAll = Array.isArray(metricaDirectAllDaily) ? metricaDirectAllDaily : [];

	      const directAllMap = directDailyAll && directDailyAll.length ? buildDailyMap(directDailyAll, 'visits') : null;
	      const directAllLeadMap = (directDailyAll && hasNumericField(directDailyAll, 'leads')) ? buildDailyMap(directDailyAll, 'leads') : null;

	      const directMap = directDailyEffectiveFinal && directDailyEffectiveFinal.length ? buildDailyMap(directDailyEffectiveFinal, 'visits') : null;
	      const directBounceMap = directDailyEffectiveFinal && directDailyEffectiveFinal.length ? buildDailyMap(directDailyEffectiveFinal, 'bounceRate') : null;
	      const directEngagedMap = directDailyEffectiveFinal && directDailyEffectiveFinal.length ? buildDailyMap(directDailyEffectiveFinal, 'engaged') : null;
	      const directLeadMap = (directDailyEffectiveFinal && hasNumericField(directDailyEffectiveFinal, 'leads')) ? buildDailyMap(directDailyEffectiveFinal, 'leads') : null;

      const imp = buildSeriesFromMap(impMap, range.start, range.end);
      const clk = buildSeriesFromMap(clkMap, range.start, range.end);
      const cst = buildSeriesFromMap(cstMap, range.start, range.end);

      const prevImp = buildSeriesFromMap(impMap, prevStart, prevEnd);
      const prevClk = buildSeriesFromMap(clkMap, prevStart, prevEnd);
      const prevCst = buildSeriesFromMap(cstMap, prevStart, prevEnd);

      const visitsSeries = metMap ? buildSeriesFromMap(metMap, range.start, range.end) : null;
      const prevVisitsSeries = metMap ? buildSeriesFromMap(metMap, prevStart, prevEnd) : null;
      const engagedSeries = engagedMap ? buildSeriesFromMap(engagedMap, range.start, range.end) : null;
      const leadsSeries = leadMap ? buildSeriesFromMap(leadMap, range.start, range.end) : null;

      const bounceSeries = bounceMap ? buildSeriesFromMap(bounceMap, range.start, range.end) : null;
      const prevBounceSeries = bounceMap ? buildSeriesFromMap(bounceMap, prevStart, prevEnd) : null;
      const durSeries = durMap ? buildSeriesFromMap(durMap, range.start, range.end) : null;

	      const directVisitsSeries = directMap ? buildSeriesFromMap(directMap, range.start, range.end) : null;
	      const directBounceSeries = directBounceMap ? buildSeriesFromMap(directBounceMap, range.start, range.end) : null;
	      const directEngagedSeries = directEngagedMap ? buildSeriesFromMap(directEngagedMap, range.start, range.end) : null;
	      const directLeadsSeries = directLeadMap ? buildSeriesFromMap(directLeadMap, range.start, range.end) : null;

	      const directAllVisitsSeries = directAllMap ? buildSeriesFromMap(directAllMap, range.start, range.end) : null;
	      const directAllLeadsSeries = directAllLeadMap ? buildSeriesFromMap(directAllLeadMap, range.start, range.end) : null;

	      const prevDirectVisitsSeries = directMap ? buildSeriesFromMap(directMap, prevStart, prevEnd) : null;
	      const prevDirectBounceSeries = directBounceMap ? buildSeriesFromMap(directBounceMap, prevStart, prevEnd) : null;
	      const prevDirectEngagedSeries = directEngagedMap ? buildSeriesFromMap(directEngagedMap, prevStart, prevEnd) : null;
	      const prevDirectLeadsSeries = directLeadMap ? buildSeriesFromMap(directLeadMap, prevStart, prevEnd) : null;

      // Weighted bounce rate & avg duration (weighted by visits)
      const weighted = (valSeries, weightSeries) => {
        if (!valSeries || !weightSeries) return null;
        let num = 0, den = 0;
        for (let i = 0; i < valSeries.values.length; i++) {
          const v = Number(valSeries.values[i] || 0);
          const w = Number(weightSeries.values[i] || 0);
          if (w <= 0) continue;
          num += v * w;
          den += w;
        }
        return den > 0 ? (num / den) : null;
      };

      const data = {
        range,
        prevRange: { start: prevStart, end: prevEnd },
        impressions: sum(imp.values),
        clicks: sum(clk.values),
        cost: sum(cst.values),
        visits: visitsSeries ? sum(visitsSeries.values) : null,
        engaged: engagedSeries ? sum(engagedSeries.values) : null,
        leads: leadsSeries ? sum(leadsSeries.values) : null,
        bounceRate: (bounceSeries && visitsSeries) ? weighted(bounceSeries, visitsSeries) : null,
        avgDuration: (durSeries && visitsSeries) ? weighted(durSeries, visitsSeries) : null,
	        direct: {
	          visits: directVisitsSeries ? sum(directVisitsSeries.values) : null,
	          engaged: directEngagedSeries ? sum(directEngagedSeries.values) : null,
	          leads: directLeadsSeries ? sum(directLeadsSeries.values) : null,
	          bounceRate: (directBounceSeries && directVisitsSeries) ? weighted(directBounceSeries, directVisitsSeries) : null,
	        },
	        directAll: {
	          visits: directAllVisitsSeries ? sum(directAllVisitsSeries.values) : null,
	          leads: directAllLeadsSeries ? sum(directAllLeadsSeries.values) : null,
	        },
        prev: {
          impressions: sum(prevImp.values),
          clicks: sum(prevClk.values),
          cost: sum(prevCst.values),
          visits: prevVisitsSeries ? sum(prevVisitsSeries.values) : null,
          bounceRate: (prevBounceSeries && prevVisitsSeries) ? weighted(prevBounceSeries, prevVisitsSeries) : null,
          direct: {
            visits: prevDirectVisitsSeries ? sum(prevDirectVisitsSeries.values) : null,
            engaged: prevDirectEngagedSeries ? sum(prevDirectEngagedSeries.values) : null,
            leads: prevDirectLeadsSeries ? sum(prevDirectLeadsSeries.values) : null,
            bounceRate: (prevDirectBounceSeries && prevDirectVisitsSeries) ? weighted(prevDirectBounceSeries, prevDirectVisitsSeries) : null,
          },
        },
        dailyLabels: clk.labels,
        dailyClicks: clk.values,
        dailyCost: cst.values,
        dailyDirectLeads: directLeadsSeries ? directLeadsSeries.values : null,
        dailyCpl: null,
        prevDailyClicks: prevClk.values,
        prevDailyCost: prevCst.values,
        prevDailyDirectLeads: prevDirectLeadsSeries ? prevDirectLeadsSeries.values : null,
        prevDailyCpl: null,
      };

      if (filterMode !== 'unclassified' && Array.isArray(data.dailyCost) && Array.isArray(data.dailyDirectLeads)) {
        data.dailyCpl = data.dailyCost.map((costV, i) => {
          const l = Number(data.dailyDirectLeads[i] ?? 0);
          const c = Number(costV ?? 0);
          if (!Number.isFinite(l) || l <= 0) return null;
          return Number.isFinite(c) ? (c / l) : null;
        });
      }
      if (filterMode !== 'unclassified' && Array.isArray(data.prevDailyCost) && Array.isArray(data.prevDailyDirectLeads)) {
        data.prevDailyCpl = data.prevDailyCost.map((costV, i) => {
          const l = Number(data.prevDailyDirectLeads[i] ?? 0);
          const c = Number(costV ?? 0);
          if (!Number.isFinite(l) || l <= 0) return null;
          return Number.isFinite(c) ? (c / l) : null;
        });
      }

      periodCache.set(period, data);
      return data;
    }

    function updateKpiChange(elementId, current, prev, higherIsBetter) {
      const element = document.getElementById(elementId);
      if (!element) return;
      const c = Number(current);
      const p = Number(prev);
      if (!Number.isFinite(c) || !Number.isFinite(p) || p <= 0) {
        element.className = 'kpi-change neutral';
        element.textContent = '—';
        return;
      }
      const pct = ((c / p) - 1) * 100;
      const up = pct > 0;
      const good = higherIsBetter ? up : !up;
      element.className = 'kpi-change ' + (pct === 0 ? 'neutral' : (good ? 'positive' : 'negative'));
      const sign = pct > 0 ? '+' : '';
      element.textContent = `${sign}${pct.toFixed(2)}% vs пред.`;
    }

	    function updateKpiCards(data) {
	      const impressions = data.impressions;
	      const clicks = data.clicks;
	      const cost = data.cost;
	      const visits = data.visits ?? 0;
	      const ctr = impressions > 0 ? (clicks / impressions) * 100 : 0;
	      const cpc = clicks > 0 ? (cost / clicks) : 0;

	      if (filterMode === 'unclassified') {
	        setText('kpi-impressions', '—');
	        setText('kpi-clicks', '—');
	        setText('kpi-ctr', '—');
	        setText('kpi-cost', '—');
	        setText('kpi-cpc', '—');
	      } else {
	        setText('kpi-impressions', fmtInt.format(Math.round(impressions)));
	        setText('kpi-clicks', fmtInt.format(Math.round(clicks)));
	        setText('kpi-ctr', `${ctr.toFixed(2)}%`);
	        setText('kpi-cost', `${fmt2.format(cost)} ₽`);
	        setText('kpi-cpc', `${fmt2.format(cpc)} ₽`);
	      }
	      setText('kpi-visits', data.visits === null ? '—' : fmtInt.format(Math.round(visits)));

      const showComparison = compareMode === 'prev';
      document.getElementById('compareMeta').textContent = showComparison ? `${toYmd(data.prevRange.start)} … ${toYmd(data.prevRange.end)}` : '—';

	      if (showComparison) {
	        if (filterMode === 'unclassified') {
	          ['kpi-impressions-change','kpi-clicks-change','kpi-ctr-change','kpi-cost-change','kpi-cpc-change'].forEach(id => {
	            const el = document.getElementById(id);
	            if (!el) return;
	            el.className = 'kpi-change neutral';
	            el.textContent = '—';
	          });
	        } else {
	          updateKpiChange('kpi-impressions-change', impressions, data.prev.impressions, true);
	          updateKpiChange('kpi-clicks-change', clicks, data.prev.clicks, true);
	          updateKpiChange('kpi-cost-change', cost, data.prev.cost, false);
	          const prevCtr = data.prev.impressions > 0 ? (data.prev.clicks / data.prev.impressions) * 100 : 0;
	          updateKpiChange('kpi-ctr-change', ctr, prevCtr, true);
	          const prevCpc = data.prev.clicks > 0 ? (data.prev.cost / data.prev.clicks) : 0;
	          updateKpiChange('kpi-cpc-change', cpc, prevCpc, false);
	        }
	        if (data.prev.visits !== null && data.visits !== null) {
	          updateKpiChange('kpi-visits-change', data.visits, data.prev.visits, true);
	        } else {
          document.getElementById('kpi-visits-change').textContent = '—';
          document.getElementById('kpi-visits-change').className = 'kpi-change neutral';
        }
      } else {
        ['kpi-impressions-change','kpi-clicks-change','kpi-ctr-change','kpi-cost-change','kpi-cpc-change','kpi-visits-change'].forEach(id => {
          const el = document.getElementById(id);
          if (!el) return;
          el.className = 'kpi-change neutral';
          el.textContent = '—';
        });
      }

	      const notes = [];
	      if (data.bounceRate !== null && data.bounceRate !== undefined) notes.push(`Bounce ≈ ${Number(data.bounceRate).toFixed(2)}%`);
	      if (data.avgDuration !== null && data.avgDuration !== undefined) notes.push(`Avg dur ≈ ${Number(data.avgDuration).toFixed(1)}s`);
	      if (data.direct && data.direct.visits !== null && data.direct.visits !== undefined) {
	        const suffix = (filterMode === 'all') ? '' : (filterMode === 'search' ? ' (Поиск)' : ' (РСЯ)');
	        notes.push(`Direct visits${suffix} ≈ ${fmtInt.format(Math.round(Number(data.direct.visits) || 0))}`);
	      }
	      if (data.direct && data.direct.leads !== null && data.direct.leads !== undefined) {
	        const suffix = (filterMode === 'all') ? '' : (filterMode === 'search' ? ' (Поиск)' : ' (РСЯ)');
	        notes.push(`Direct leads${suffix} ≈ ${fmtInt.format(Math.round(Number(data.direct.leads) || 0))}`);
	      }
	      document.getElementById('kpi-note').textContent = notes.join(' · ');
	    }

	    function updateFunnel(data) {
      // Reset bottleneck highlights
      const resetStep = (id) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.classList.remove('bottleneck');
        el.removeAttribute('title');
      };
      [
        'step-site-visits-engaged','step-site-engaged-leads','step-site-total',
        'step-direct-impr-clicks','step-direct-clicks-visits','step-direct-visits-engaged','step-direct-engaged-leads','step-direct-cpl'
      ].forEach(resetStep);

      const markBottleneck = (id, title) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.classList.add('bottleneck');
        if (title) el.title = title;
      };

      const impressions = data.impressions;
      const clicks = data.clicks;
      const cost = data.cost;
      const siteVisits = (data.visits ?? 0);
      const siteBounce = (data.bounceRate !== null && data.bounceRate !== undefined) ? Number(data.bounceRate) : null;
      const siteEngaged = (data.engaged !== null && data.engaged !== undefined)
        ? Number(data.engaged)
        : (siteBounce === null ? null : (siteVisits * (1 - siteBounce / 100)));
      const siteLeads = (data.leads !== null && data.leads !== undefined) ? Number(data.leads) : null;

	      const hasDirect = !!(data.direct && data.direct.visits !== null && data.direct.visits !== undefined);
	      const directVisits = hasDirect ? Number(data.direct.visits || 0) : null;
	      const directBounce = hasDirect && data.direct.bounceRate !== null && data.direct.bounceRate !== undefined ? Number(data.direct.bounceRate) : null;
	      const directEngaged = hasDirect
	        ? (data.direct.engaged !== null && data.direct.engaged !== undefined
	          ? Number(data.direct.engaged)
	          : (directBounce === null ? null : (Number(directVisits || 0) * (1 - directBounce / 100))))
	        : null;
	      const directLeads = hasDirect && data.direct.leads !== null && data.direct.leads !== undefined ? Number(data.direct.leads) : null;

      // Site funnel (all sources)
      if (siteEngaged === null) {
        setText('funnel-site-visits-engaged', `${fmtInt.format(Math.round(siteVisits))} → —`);
        setText('conv-site-visits-engaged', '—');
      } else {
        setText('funnel-site-visits-engaged', `${fmtInt.format(Math.round(siteVisits))} → ${fmtInt.format(Math.round(siteEngaged))}`);
        setText('conv-site-visits-engaged', siteVisits > 0 ? `≈ ${(100 * siteEngaged / siteVisits).toFixed(2)}%` : '—');
      }
      if (siteLeads === null) {
        setText('funnel-site-engaged-leads', `${siteEngaged === null ? '—' : fmtInt.format(Math.round(siteEngaged))} → —`);
        setText('conv-site-engaged-leads', '—');
        setText('funnel-site-leads-total', '—');
        setText('conv-site-total', '—');
      } else {
        setText('funnel-site-engaged-leads', `${siteEngaged === null ? '—' : fmtInt.format(Math.round(siteEngaged))} → ${fmtInt.format(Math.round(siteLeads))}`);
        setText('conv-site-engaged-leads', (siteEngaged && siteEngaged > 0) ? `≈ ${(100 * siteLeads / siteEngaged).toFixed(2)}%` : '—');
        setText('funnel-site-leads-total', fmtInt.format(Math.round(siteLeads)));
        setText('conv-site-total', '—');
      }

      // Site bottleneck: mark the step with the lowest available conversion rate.
      const siteRates = [];
      if (siteEngaged !== null && siteVisits > 0) siteRates.push({ id: 'step-site-visits-engaged', rate: (siteEngaged / siteVisits), label: 'Визиты → Engaged' });
      if (siteLeads !== null && siteEngaged && siteEngaged > 0) siteRates.push({ id: 'step-site-engaged-leads', rate: (siteLeads / siteEngaged), label: 'Engaged → Leads' });
      if (siteRates.length) {
        siteRates.sort((a,b) => a.rate - b.rate);
        const worst = siteRates[0];
        markBottleneck(worst.id, `Узкое место (сайт): ${worst.label} ≈ ${(100*worst.rate).toFixed(2)}%`);
      }

	      // Direct funnel (Metrica-attributed Direct traffic)
	      if (filterMode === 'unclassified') {
	        setText('funnel-direct-impr-clicks', '—');
	        setText('conv-direct-impressions-clicks', '—');
	      } else {
	        setText('funnel-direct-impr-clicks', `${fmtInt.format(Math.round(impressions))} → ${fmtInt.format(Math.round(clicks))}`);
	        setText('conv-direct-impressions-clicks', impressions > 0 ? `CTR ≈ ${(100 * clicks / impressions).toFixed(2)}%` : '—');
	      }
	      const allowDirectAttribution = hasDirect;
	      if (!allowDirectAttribution) {
	        ['funnel-direct-clicks-visits','conv-direct-clicks-visits','funnel-direct-visits-engaged','conv-direct-visits-engaged','funnel-direct-engaged-leads','conv-direct-engaged-leads','funnel-direct-cpl'].forEach(id => setText(id, '—'));
	        setText('conv-direct-total', '—');
	        setText('directFunnelNote', '');
	        return;
	      }
	      // When filter is Search/RSYA, Direct visits/leads come from UTMCampaign mapping (option C) and may be partial.
	      if (filterMode !== 'all') {
	        if (!(metricaDirectSplit && metricaDirectSplit.available)) {
	          const suffix = (filterMode === 'search') ? 'Поиск' : (filterMode === 'rsya' ? 'РСЯ' : 'Не классифицировано');
	          setText('directFunnelNote', `Директ (${suffix}) недоступен: нет корректной выборки по UTMCampaign (Option C). Проверь, что utm_campaign проставляется в кликах Директа и содержит campaign_id или уникальное имя кампании.`);
	          return;
	        }
	        const allV = (data.directAll && data.directAll.visits !== null && data.directAll.visits !== undefined) ? Number(data.directAll.visits || 0) : null;
	        const allL = (data.directAll && data.directAll.leads !== null && data.directAll.leads !== undefined) ? Number(data.directAll.leads || 0) : null;
	        const shareV = (allV && allV > 0) ? (100 * (directVisits || 0) / allV) : null;
	        const missV = (allV === null) ? null : Math.max(0, allV - (directVisits || 0));
	        const missL = (allL === null || directLeads === null) ? null : Math.max(0, allL - (directLeads || 0));
	        const suffix = filterMode === 'search' ? 'Поиск' : (filterMode === 'rsya' ? 'РСЯ' : 'Не классифицировано');
	        const parts = (filterMode === 'unclassified')
	          ? [`Директ (${suffix}) = остаток: Direct(all) − (Поиск + РСЯ).`]
	          : [`Директ (${suffix}) рассчитан через UTMCampaign → тип кампании (Option C).`];
	        if (shareV !== null) parts.push(`Покрытие визитов: ≈ ${shareV.toFixed(1)}% (${fmtInt.format(Math.round(directVisits||0))} из ${fmtInt.format(Math.round(allV))}).`);
	        if (missV !== null && missV > 0) parts.push(`Неклассифицировано визитов: ${fmtInt.format(Math.round(missV))}.`);
	        if (missL !== null && missL > 0) parts.push(`Неклассифицировано лидов: ${fmtInt.format(Math.round(missL))}.`);
	        if (filterMode !== 'unclassified') parts.push('Рекомендуется: utm_campaign должен содержать campaign_id или уникальное имя кампании.');
	        setText('directFunnelNote', parts.join(' '));
	      } else {
	        setText('directFunnelNote', '');
	      }
      if (filterMode === 'unclassified') {
        setText('funnel-direct-clicks-visits', `— → ${fmtInt.format(Math.round(directVisits || 0))}`);
        setText('conv-direct-clicks-visits', '—');
      } else {
        setText('funnel-direct-clicks-visits', `${fmtInt.format(Math.round(clicks))} → ${fmtInt.format(Math.round(directVisits || 0))}`);
        setText('conv-direct-clicks-visits', (clicks > 0) ? `≈ ${(100 * (directVisits || 0) / clicks).toFixed(2)}%` : '—');
      }

      if (directEngaged === null) {
        setText('funnel-direct-visits-engaged', `${fmtInt.format(Math.round(directVisits || 0))} → —`);
        setText('conv-direct-visits-engaged', '—');
      } else {
        setText('funnel-direct-visits-engaged', `${fmtInt.format(Math.round(directVisits || 0))} → ${fmtInt.format(Math.round(directEngaged))}`);
        setText('conv-direct-visits-engaged', (directVisits && directVisits > 0) ? `≈ ${(100 * directEngaged / directVisits).toFixed(2)}%` : '—');
      }

      if (directLeads === null) {
        setText('funnel-direct-engaged-leads', `${directEngaged === null ? '—' : fmtInt.format(Math.round(directEngaged))} → —`);
        setText('conv-direct-engaged-leads', '—');
        setText('funnel-direct-cpl', '—');
        setText('conv-direct-total', '—');
        return;
      }

      setText('funnel-direct-engaged-leads', `${directEngaged === null ? '—' : fmtInt.format(Math.round(directEngaged))} → ${fmtInt.format(Math.round(directLeads))}`);
      setText('conv-direct-engaged-leads', (directEngaged && directEngaged > 0) ? `≈ ${(100 * directLeads / directEngaged).toFixed(2)}%` : '—');
	      if (filterMode === 'unclassified') {
	        setText('funnel-direct-cpl', '—');
	        setText('conv-direct-total', (directLeads > 0) ? `${fmtInt.format(Math.round(directLeads))} leads` : '—');
	      } else {
	        setText('funnel-direct-cpl', (directLeads > 0) ? `${fmt2.format(cost / directLeads)} ₽` : '—');
	        setText('conv-direct-total', (directLeads > 0) ? `${fmtInt.format(Math.round(directLeads))} leads` : '—');
	      }

      // Direct bottleneck: mark the step with the lowest available conversion rate (excluding CTR).
      const directRates = [];
      if (filterMode !== 'unclassified' && clicks > 0 && directVisits !== null) directRates.push({ id: 'step-direct-clicks-visits', rate: (directVisits / clicks), label: 'Клики → Визиты' });
      if (directEngaged !== null && directVisits && directVisits > 0) directRates.push({ id: 'step-direct-visits-engaged', rate: (directEngaged / directVisits), label: 'Визиты → Engaged' });
      if (directLeads !== null && directEngaged && directEngaged > 0) directRates.push({ id: 'step-direct-engaged-leads', rate: (directLeads / directEngaged), label: 'Engaged → Leads' });
      if (directRates.length) {
        directRates.sort((a,b) => a.rate - b.rate);
        const worst = directRates[0];
        markBottleneck(worst.id, `Узкое место (Директ): ${worst.label} ≈ ${(100*worst.rate).toFixed(2)}%`);
      }
	    }

    function updateDailyChart(data) {
      if (!window.Chart) {
        const canvas = document.getElementById('dailyChart');
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0,0,canvas.width,canvas.height);
        return;
      }

      const colors = colorsForTheme();
      const showComparison = compareMode === 'prev';

      if (dailyChart) {
        dailyChart.destroy();
        dailyChart = null;
      }

      const ctx = document.getElementById('dailyChart').getContext('2d');
      const datasets = [
        { label: 'Клики', data: data.dailyClicks, borderColor: 'rgba(102,126,234,0.95)', fill: false, tension: 0.35, yAxisID: 'y', pointRadius: 2 },
        { label: 'Расход (₽)', data: data.dailyCost, borderColor: 'rgba(245,87,108,0.90)', fill: false, tension: 0.35, yAxisID: 'y1', pointRadius: 2 },
      ];
      if (filterMode !== 'unclassified' && Array.isArray(data.dailyCpl)) {
        datasets.push({ label: 'CPL (₽/lead)', data: data.dailyCpl, borderColor: 'rgba(0,210,106,0.90)', fill: false, tension: 0.35, yAxisID: 'y2', pointRadius: 2 });
      }

      if (showComparison && data.prevDailyClicks) {
        datasets.push({ label: 'Клики (пред.)', data: data.prevDailyClicks, borderColor: 'rgba(102,126,234,0.35)', borderDash: [5,5], fill: false, tension: 0.35, yAxisID: 'y', pointRadius: 2 });
        datasets.push({ label: 'Расход (пред.)', data: data.prevDailyCost, borderColor: 'rgba(245,87,108,0.32)', borderDash: [5,5], fill: false, tension: 0.35, yAxisID: 'y1', pointRadius: 2 });
        if (filterMode !== 'unclassified' && Array.isArray(data.prevDailyCpl)) {
          datasets.push({ label: 'CPL (пред.)', data: data.prevDailyCpl, borderColor: 'rgba(0,210,106,0.32)', borderDash: [5,5], fill: false, tension: 0.35, yAxisID: 'y2', pointRadius: 2 });
        }
      }

      dailyChart = new Chart(ctx, {
        type: 'line',
        data: { labels: data.dailyLabels, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { labels: { color: colors.textPrimary } }
          },
          scales: {
            x: { grid: { color: colors.gridColor }, ticks: { color: colors.textSecondary } },
            y: { position: 'left', grid: { color: colors.gridColor }, ticks: { color: 'rgba(102,126,234,0.95)' } },
            y1: { position: 'right', grid: { drawOnChartArea: false }, ticks: { color: 'rgba(245,87,108,0.90)' } },
            y2: { position: 'right', grid: { drawOnChartArea: false }, ticks: { color: 'rgba(0,210,106,0.90)' }, display: (filterMode !== 'unclassified' && Array.isArray(data.dailyCpl)) }
          }
        }
      });
    }

    function campaignTotalsForRange(campaign, start, end) {
      const series = buildSeries(campaign.daily || [], start, end);
      return {
        impressions: sum(series.impressions.values),
        clicks: sum(series.clicks.values),
        cost: sum(series.cost.values),
        series,
      };
    }

    function buildSeries(daily, start, end) {
      const days = enumerateDays(start, end);
      const maps = {
        impressions: buildDailyMap(daily, 'impressions'),
        clicks: buildDailyMap(daily, 'clicks'),
        cost: buildDailyMap(daily, 'cost'),
      };
      const labels = days.map(formatDayLabel);
      return {
        labels,
        impressions: { labels, values: days.map(d => maps.impressions.get(toYmd(d)) ?? 0) },
        clicks: { labels, values: days.map(d => maps.clicks.get(toYmd(d)) ?? 0) },
        cost: { labels, values: days.map(d => maps.cost.get(toYmd(d)) ?? 0) },
      };
    }

    function renderMiniChart(canvasId, clicksValues) {
      const canvas = document.getElementById(canvasId);
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      const W = canvas.width = 150;
      const H = canvas.height = 34;
      ctx.clearRect(0,0,W,H);
      const vals = clicksValues || [];
      if (!vals.length) return;
      const maxV = Math.max(1, ...vals.map(x => Number(x||0)));
      ctx.strokeStyle = 'rgba(122,162,255,0.95)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      vals.forEach((v, i) => {
        const x = (W * i) / (vals.length - 1 || 1);
        const y = H - (H * (Number(v||0) / maxV));
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }

    function isCampaignCplAvailable() {
      if (filterMode === 'unclassified') return false;
      if (!metricaDirectByCampaign || !metricaDirectByCampaign.available) return false;
      const meta = metricaDirectByCampaign.meta || {};
      return !!meta.report_is_direct_only;
    }

    function getCampaignLeadMap(campaignId) {
      const campaigns = (metricaDirectByCampaign && metricaDirectByCampaign.campaigns) ? metricaDirectByCampaign.campaigns : {};
      const blk = campaigns ? campaigns[String(campaignId)] : null;
      const daily = blk && Array.isArray(blk.daily) ? blk.daily : [];
      if (!daily.length) return null;
      return buildDailyMap(daily, 'leads');
    }

    function sumFromMap(map, start, end) {
      if (!map) return 0;
      const days = enumerateDays(start, end);
      let total = 0;
      days.forEach(d => { total += Number(map.get(toYmd(d)) ?? 0); });
      return total;
    }

    function updateCampaignTable(period) {
      const range = getPeriodRange(period);
      const dayCount = enumerateDays(range.start, range.end).length;
      const prevEnd = addDays(range.start, -1);
      const prevStart = addDays(prevEnd, -(dayCount - 1));

      const entries = Object.entries(campaignData)
        .map(([id, camp]) => ({ id, camp }))
        .filter(({ camp }) => filterMode === 'all' ? true : (camp.type === filterMode));

      const cplEnabled = isCampaignCplAvailable();

      // Sort by CPL asc (best -> worst) when available; otherwise by cost desc.
      const scored = entries.map(({ id, camp }) => {
        const cur = campaignTotalsForRange(camp, range.start, range.end);
        const prev = campaignTotalsForRange(camp, prevStart, prevEnd);
        let leadsCur = null;
        let cplCur = null;
        if (cplEnabled) {
          const leadMap = getCampaignLeadMap(id);
          if (leadMap) {
            leadsCur = sumFromMap(leadMap, range.start, range.end);
            if (leadsCur > 0) cplCur = (cur.cost / leadsCur);
          }
        }
        return { id, camp, cur, prev, leadsCur, cplCur };
      }).sort((a, b) => {
        if (cplEnabled) {
          const ax = Number(a.cplCur);
          const bx = Number(b.cplCur);
          const aOk = Number.isFinite(ax);
          const bOk = Number.isFinite(bx);
          if (aOk && bOk) return ax - bx;
          if (aOk && !bOk) return -1;
          if (!aOk && bOk) return 1;
          // fallback: cost desc
          return b.cur.cost - a.cur.cost;
        }
        return b.cur.cost - a.cur.cost;
      });

      const tbody = document.getElementById('campaignTableBody');
      if (!tbody) return;

      if (!scored.length) {
        tbody.innerHTML = '<tr><td colspan="10" style="color: var(--text-muted); padding: 18px; text-align: center;">No campaigns</td></tr>';
        const noteEl = document.getElementById('campaignCplNote');
        if (noteEl) noteEl.textContent = 'Нет кампаний для выбранного фильтра.';
        return { cplEnabled: false, worst: [] };
      }

      tbody.innerHTML = scored.slice(0, 50).map(({ id, camp, cur, prev }) => {
        const ctr = cur.impressions > 0 ? (100 * cur.clicks / cur.impressions) : 0;
        const cpc = cur.clicks > 0 ? (cur.cost / cur.clicks) : 0;

        const trend = computeTrend(cur.series.clicks.values);
        let badgeClass = 'neutral';
        let arrow = '→';
        let changeText = '—';
        if (trend && trend.kind === 'inf') { badgeClass = 'up'; arrow = '↑'; changeText = '∞'; }
        else if (trend && trend.kind === 'pct' && Number.isFinite(Number(trend.pct)) && Number(trend.pct) !== 0) {
          badgeClass = Number(trend.pct) > 0 ? 'up' : 'down';
          arrow = Number(trend.pct) > 0 ? '↑' : '↓';
          const sign = Number(trend.pct) > 0 ? '+' : '';
          changeText = `${sign}${Number(trend.pct).toFixed(1)}%`;
        }

        let vsPrev = '—';
        let vsPrevClass = 'neutral';
        if (compareMode === 'prev' && prev.clicks > 0) {
          const pct = ((cur.clicks / prev.clicks) - 1) * 100;
          const sign = pct > 0 ? '+' : '';
          vsPrev = `${sign}${pct.toFixed(1)}%`;
          vsPrevClass = pct > 0 ? 'up' : (pct < 0 ? 'down' : 'neutral');
        }

        const iconClass = camp.type === 'search' ? 'search' : (camp.type === 'rsya' ? 'rsya' : '');
        const icon = camp.type === 'search' ? '🔍' : (camp.type === 'rsya' ? '🌐' : '•');
        const name = (camp.shortName || camp.name || `#${id}`);
        const sub = (camp.subName || '').trim();

        const cplEnabled = isCampaignCplAvailable();
        let leadsCell = '—';
        let cplCell = '—';
        if (cplEnabled) {
          const leadMap = getCampaignLeadMap(id);
          if (leadMap) {
            const leadsCur = sumFromMap(leadMap, range.start, range.end);
            leadsCell = fmtInt.format(Math.round(leadsCur || 0));
            if (leadsCur > 0) cplCell = `${fmt2.format(cur.cost / leadsCur)} ₽`;
          }
        }

        return `
          <tr class="campaign-row" data-type="${camp.type || 'unknown'}" onclick="openCampaignModal('${id}')">
            <td>
              <div class="campaign-name">
                <div class="campaign-icon ${iconClass}">${icon}</div>
                <div>
                  <div>${name}</div>
                  <div style="font-size: 11px; color: var(--text-muted);">${sub}</div>
                </div>
              </div>
            </td>
            <td>${fmtInt.format(Math.round(cur.impressions))}</td>
            <td>${fmtInt.format(Math.round(cur.clicks))}</td>
            <td>${ctr.toFixed(2)}%</td>
            <td>${fmt2.format(cur.cost)} ₽</td>
            <td>${fmt2.format(cpc)} ₽</td>
            <td>${leadsCell}</td>
            <td>${cplCell}</td>
            <td><canvas class="mini-chart" id="chart-${id}"></canvas></td>
            <td><span class="comparison-badge ${vsPrevClass}">${vsPrev}</span></td>
          </tr>
        `;
      }).join('');

      // Render mini charts after DOM is updated
      setTimeout(() => {
        scored.slice(0, 50).forEach(({ id, cur }) => {
          renderMiniChart(`chart-${id}`, cur.series.clicks.values);
        });
      }, 20);

      const noteEl = document.getElementById('campaignCplNote');
      if (noteEl) {
        if (cplEnabled) {
          noteEl.textContent = 'CPL по кампаниям рассчитан best-effort через UTMCampaign → CampaignId (только если UTMCampaign отчёт удалось ограничить Direct-трафиком).';
        } else if (filterMode === 'unclassified') {
          noteEl.textContent = 'В режиме “Не классифицировано” CPL по кампаниям недоступен (нет корректной атрибуции расхода/лидов).';
        } else {
          noteEl.textContent = 'CPL по кампаниям недоступен: UTMCampaign отчёт не удалось ограничить Direct-трафиком (см. warnings).';
        }
      }

      const worst = (cplEnabled ? scored.filter(x => Number.isFinite(Number(x.cplCur))).slice().sort((a,b) => Number(b.cplCur)-Number(a.cplCur)).slice(0,3) : []);
      return { cplEnabled, worst };
    }

    function fillRecommendations() {
      const today = Array.isArray(rec.today_actions) ? rec.today_actions : [];
      const questions = Array.isArray(rec.discussion_questions) ? rec.discussion_questions : [];
      const notes = Array.isArray(rec.notes) ? rec.notes : [];

      const fill = (id, items) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.innerHTML = (items.length ? items : ['—']).map(x => `<li>${String(x)}</li>`).join('');
      };
      fill('todayActions', today);
      fill('discussionQuestions', questions);
      document.getElementById('recNotes').textContent = notes.join(' ');
    }

    function clearKpiFlags() {
      ['flag-impressions','flag-clicks','flag-ctr','flag-cost','flag-cpc','flag-visits'].forEach(id => setText(id, ''));
    }

    function renderWordstat(range) {
      const card = document.getElementById('wordstatCard');
      const note = document.getElementById('wordstatNote');
      const tbody = document.getElementById('wordstatRows');
      if (!card || !note || !tbody) return;

      const ok = !!(wordstat && wordstat.available && Array.isArray(wordstat.campaigns) && wordstat.campaigns.length);
      if (!ok) {
        card.style.display = 'none';
        return;
      }
      card.style.display = 'block';

      const m = (wordstat.meta || {});
      const periodTxt = (meta && meta.date_from && meta.date_to) ? `${meta.date_from} … ${meta.date_to}` : `${toYmd(range.start)} … ${toYmd(range.end)}`;
      note.textContent = `Период seeds/идей: ${periodTxt}. Кампаний: ${wordstat.campaigns.length}. numPhrases=${m.num_phrases ?? '—'}.`;

      const pills = (items, fmt) => {
        const arr = Array.isArray(items) ? items : [];
        if (!arr.length) return '—';
        return `<div class="pills">` + arr.map(x => fmt(x)).join('') + `</div>`;
      };

      const rows = wordstat.campaigns.slice(0, 20).map(c => {
        const cname = esc(c.campaign_name || `#${c.campaign_id}`);
        const seeds = pills(c.seeds || [], (s) => `<span class="pill"><span class="mono">${esc(s)}</span></span>`);
        const ideas = pills((c.candidates || []).slice(0, 12), (it) => {
          const p = esc(it.phrase || '');
          const score = Number(it.score ?? 0);
          const scoreTxt = Number.isFinite(score) ? fmtInt.format(Math.round(score)) : '—';
          return `<span class="pill"><span class="mono">${p}</span><span class="muted">· ${scoreTxt}</span></span>`;
        });
        const negs = pills((c.negatives || []).slice(0, 18), (it) => {
          const t = esc(it.token || '');
          const cnt = Number(it.count ?? 0);
          const cntTxt = Number.isFinite(cnt) && cnt > 0 ? fmtInt.format(cnt) : '';
          return `<span class="pill"><span class="mono">${t}</span>${cntTxt ? `<span class="muted">· ${cntTxt}</span>` : ''}</span>`;
        });
        return `<tr><td>${cname}</td><td>${seeds}</td><td>${ideas}</td><td>${negs}</td></tr>`;
      }).join('');
      tbody.innerHTML = rows || '<tr><td colspan="4" style="color: var(--text-muted)">Нет данных</td></tr>';
    }

    function renderAudience(range) {
      const card = document.getElementById('audienceCard');
      const note = document.getElementById('audienceNote');
      const tbody = document.getElementById('audienceRows');
      const otbody = document.getElementById('audienceOverlapRows');
      if (!card || !note || !tbody || !otbody) return;

      const ok = !!(audience && audience.available && Array.isArray(audience.segments) && audience.segments.length);
      if (!ok) {
        card.style.display = 'none';
        return;
      }
      card.style.display = 'block';

      const periodTxt = (meta && meta.date_from && meta.date_to) ? `${meta.date_from} … ${meta.date_to}` : `${toYmd(range.start)} … ${toYmd(range.end)}`;
      note.textContent = `Сегментов: ${audience.segments.length}. Период дашборда: ${periodTxt}.`;

      const rows = audience.segments.slice(0, 50).map(s => {
        const name = esc(s.name || `#${s.id}`);
        const type = esc(s.type || '—');
        const status = esc(s.status || '—');
        const size = (s.size !== null && s.size !== undefined) ? fmtInt.format(Number(s.size)) : '—';
        const upd = esc(s.updated_at || '—');
        const hs = (s.health && s.health.status) ? esc(s.health.status) : '—';
        const hints = (s.health && Array.isArray(s.health.hints) && s.health.hints.length) ? ` (${esc(s.health.hints.join(','))})` : '';
        return `<tr><td>${name}</td><td>${type}</td><td>${status}</td><td class="mono">${size}</td><td class="mono">${upd}</td><td>${hs}${hints}</td></tr>`;
      }).join('');
      tbody.innerHTML = rows || '<tr><td colspan="6" style="color: var(--text-muted)">Нет данных</td></tr>';

      const ovs = Array.isArray(audience.top_overlaps) ? audience.top_overlaps : [];
      const orows = ovs.slice(0, 50).map(p => {
        const a = esc(p.a || ''); const b = esc(p.b || '');
        const share = (p.overlap_share !== null && p.overlap_share !== undefined) ? esc(String(p.overlap_share)) : '—';
        const abs = (p.overlap_abs !== null && p.overlap_abs !== undefined) ? esc(String(p.overlap_abs)) : '—';
        return `<tr><td class="mono">${a}</td><td class="mono">${b}</td><td class="mono">${share}</td><td class="mono">${abs}</td></tr>`;
      }).join('');
      otbody.innerHTML = orows || '<tr><td colspan="4" style="color: var(--text-muted)">—</td></tr>';
    }

    function updateAlerts(data, tableStats) {
      const card = document.getElementById('alertsCard');
      const listEl = document.getElementById('alertsList');
      const noteEl = document.getElementById('alertsNote');
      if (!card || !listEl || !noteEl) return;

      clearKpiFlags();
      if (compareMode !== 'prev') {
        card.style.display = 'none';
        return;
      }

      const alerts = [];
      const pct = (cur, prev) => {
        const c = Number(cur); const p = Number(prev);
        if (!Number.isFinite(c) || !Number.isFinite(p) || p <= 0) return null;
        return ((c / p) - 1) * 100;
      };

      // Direct CPL (account-level)
      if (filterMode !== 'unclassified') {
        const leadsCur = data.direct ? data.direct.leads : null;
        const leadsPrev = (data.prev && data.prev.direct) ? data.prev.direct.leads : null;
        const cplCur = (Number(leadsCur) > 0) ? (Number(data.cost) / Number(leadsCur)) : null;
        const cplPrev = (Number(leadsPrev) > 0) ? (Number(data.prev.cost) / Number(leadsPrev)) : null;
        const cplPct = pct(cplCur, cplPrev);
        if (cplPct !== null && cplPct > 20) {
          alerts.push({ level: 'danger', text: `CPL вырос на ${cplPct.toFixed(1)}% (тек. ${fmt2.format(cplCur)} ₽/lead)` });
          setText('flag-cost', '⚠️');
        }
      }

      // Bounce rate (site + direct)
      const brSiteDiff = (data.bounceRate !== null && data.prev.bounceRate !== null) ? (Number(data.bounceRate) - Number(data.prev.bounceRate)) : null;
      if (brSiteDiff !== null && brSiteDiff > 5) {
        alerts.push({ level: 'warn', text: `Отказы (сайт) +${brSiteDiff.toFixed(1)} п.п.` });
        setText('flag-visits', '⚠️');
      }
      const brDirectDiff = (data.direct && data.prev && data.prev.direct && data.direct.bounceRate !== null && data.prev.direct.bounceRate !== null)
        ? (Number(data.direct.bounceRate) - Number(data.prev.direct.bounceRate)) : null;
      if (brDirectDiff !== null && brDirectDiff > 5) {
        alerts.push({ level: 'warn', text: `Отказы (Директ) +${brDirectDiff.toFixed(1)} п.п.` });
        setText('flag-visits', '⚠️');
      }

      // CTR drop
      if (filterMode !== 'unclassified') {
        const ctrCur = (data.impressions > 0) ? (100 * data.clicks / data.impressions) : 0;
        const ctrPrev = (data.prev.impressions > 0) ? (100 * data.prev.clicks / data.prev.impressions) : 0;
        const drop = ctrPrev - ctrCur;
        if (drop > 0.3) {
          alerts.push({ level: 'warn', text: `CTR упал на ${drop.toFixed(2)} п.п.` });
          setText('flag-ctr', '⚠️');
        }
      }

      // Spend up without leads growth (Direct)
      if (filterMode !== 'unclassified') {
        const costPct = pct(data.cost, data.prev.cost);
        const leadsPct = pct((data.direct || {}).leads, ((data.prev || {}).direct || {}).leads);
        if (costPct !== null && costPct > 30 && (leadsPct === null || leadsPct <= 0)) {
          alerts.push({ level: 'danger', text: `Расход +${costPct.toFixed(1)}% без роста лидов` });
          setText('flag-cost', '⚠️');
        }
      }

      // Leads down (Direct)
      const leadsDrop = pct((data.direct || {}).leads, ((data.prev || {}).direct || {}).leads);
      if (leadsDrop !== null && leadsDrop < -20) {
        alerts.push({ level: 'danger', text: `Лиды (Директ) ${leadsDrop.toFixed(1)}% vs пред.` });
        setText('flag-visits', '⚠️');
      }

      // Worst CPL campaigns
      if (tableStats && tableStats.cplEnabled && Array.isArray(tableStats.worst) && tableStats.worst.length) {
        const worstTxt = tableStats.worst.map(x => `${x.camp.shortName || x.camp.name || x.id}: ${fmt2.format(x.cplCur)} ₽`).join(' · ');
        alerts.push({ level: 'warn', text: `Топ-3 худших CPL по кампаниям: ${worstTxt}` });
      }

      if (!alerts.length) {
        card.style.display = 'none';
        return;
      }

      const hasDanger = alerts.some(a => a.level === 'danger');
      card.classList.toggle('has-danger', hasDanger);
      card.style.display = 'block';
      listEl.innerHTML = alerts.map(a => {
        const cls = a.level === 'danger' ? 'danger' : 'warn';
        const label = a.level === 'danger' ? 'Критично' : 'Внимание';
        return `<li><span class="alert-badge ${cls}">⚠️ ${label}</span> ${String(a.text)}</li>`;
      }).join('');
      noteEl.textContent = 'Алерты считаются автоматически (текущий период vs предыдущий период той же длины).';
    }

    // Funnel rate color-coding: add rate-good/rate-medium/rate-bad classes
    function colorCodeFunnelRates() {
      document.querySelectorAll('.funnel-rate').forEach(el => {
        el.classList.remove('rate-good', 'rate-medium', 'rate-bad');
        const text = el.textContent || '';
        const match = text.match(/([\\d,.]+)%/);
        if (!match) return;
        const pct = parseFloat(match[1].replace(',', '.'));
        if (!Number.isFinite(pct)) return;
        if (pct > 50) el.classList.add('rate-good');
        else if (pct >= 20) el.classList.add('rate-medium');
        else el.classList.add('rate-bad');
      });
    }

    function updateDashboard(period) {
      currentPeriod = period;
      const data = getOverallPeriodData(period);

      setText('periodMeta', `${toYmd(data.range.start)} … ${toYmd(data.range.end)}`);
      updateKpiCards(data);
      updateFunnel(data);
      colorCodeFunnelRates();
      renderMetricaSources(data.range);
      renderMetricaGoals(data.range);
      updateDailyChart(data);
      const tableStats = updateCampaignTable(period);
      fillRecommendations();
      renderWordstat(data.range);
      renderAudience(data.range);
      updateAlerts(data, tableStats);
    }

    // UI handlers
    document.querySelectorAll('.period-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        periodCache.clear();
        updateDashboard(btn.dataset.period);
      });
    });
    document.querySelectorAll('.compare-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.compare-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        compareMode = btn.dataset.compare;
        updateDashboard(currentPeriod);
      });
    });
    document.querySelectorAll('.filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        filterMode = btn.dataset.filter;
        periodCache.clear();
        updateDashboard(currentPeriod);
      });
    });
    document.querySelectorAll('.goal-scope-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.goal-scope-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        goalsScope = btn.dataset.scope || 'all';
        renderMetricaGoals(getPeriodRange(currentPeriod));
      });
    });
    const goalSelectEl = document.getElementById('goalSelect');
    if (goalSelectEl) {
      goalSelectEl.addEventListener('change', () => {
        renderMetricaGoals(getPeriodRange(currentPeriod));
      });
    }

    // Modal
    const modal = document.getElementById('campaignModal');
    const closeModal = () => { modal.classList.remove('show'); if (modalChart) { modalChart.destroy(); modalChart = null; } };
    document.getElementById('modalClose').addEventListener('click', closeModal);
    modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });
    window.openCampaignModal = (campaignId) => {
      const camp = campaignData[campaignId];
      if (!camp) return;

      const range = getPeriodRange(currentPeriod);
      const dayCount = enumerateDays(range.start, range.end).length;
      const prevEnd = addDays(range.start, -1);
      const prevStart = addDays(prevEnd, -(dayCount - 1));

      const cur = campaignTotalsForRange(camp, range.start, range.end);
      const prev = campaignTotalsForRange(camp, prevStart, prevEnd);

      const ctr = cur.impressions > 0 ? (100 * cur.clicks / cur.impressions) : 0;
      const cpc = cur.clicks > 0 ? (cur.cost / cur.clicks) : 0;
      const vsPrevClicks = (compareMode === 'prev' && prev.clicks > 0) ? (((cur.clicks / prev.clicks) - 1) * 100) : null;

      setText('modalTitle', camp.name || `#${campaignId}`);
      setText('modalSubtitle', `Period: ${toYmd(range.start)} … ${toYmd(range.end)} · type=${camp.type || 'unknown'}`);
      setText('m-impr-clicks', `${fmtInt.format(Math.round(cur.impressions))} → ${fmtInt.format(Math.round(cur.clicks))}`);
      setText('m-ctr', `CTR ≈ ${ctr.toFixed(2)}%`);
      setText('m-clicks-cost', `${fmtInt.format(Math.round(cur.clicks))} → ${fmt2.format(cur.cost)} ₽`);
      setText('m-cpc', `CPC ≈ ${fmt2.format(cpc)} ₽`);
      setText('m-cpc-only', `${fmt2.format(cpc)} ₽`);
      setText('m-cost-only', `Cost ≈ ${fmt2.format(cur.cost)} ₽`);
      setText('m-days', String(dayCount));
      setText('m-vs-prev', (vsPrevClicks === null) ? '—' : `${vsPrevClicks > 0 ? '+' : ''}${vsPrevClicks.toFixed(1)}%`);

      // Modal chart
      if (modalChart) { modalChart.destroy(); modalChart = null; }
      if (window.Chart) {
        const colors = colorsForTheme();
        const ctx = document.getElementById('modalChart').getContext('2d');
        const datasets = [
          { label: 'Клики', data: cur.series.clicks.values, borderColor: 'rgba(102,126,234,0.95)', fill: false, tension: 0.35, yAxisID: 'y', pointRadius: 2 },
          { label: 'Расход (₽)', data: cur.series.cost.values, borderColor: 'rgba(245,87,108,0.90)', fill: false, tension: 0.35, yAxisID: 'y1', pointRadius: 2 },
        ];
        if (compareMode === 'prev') {
          datasets.push({ label: 'Клики (пред.)', data: prev.series.clicks.values, borderColor: 'rgba(102,126,234,0.35)', borderDash: [5,5], fill: false, tension: 0.35, yAxisID: 'y', pointRadius: 2 });
          datasets.push({ label: 'Расход (пред.)', data: prev.series.cost.values, borderColor: 'rgba(245,87,108,0.32)', borderDash: [5,5], fill: false, tension: 0.35, yAxisID: 'y1', pointRadius: 2 });
        }
        modalChart = new Chart(ctx, {
          type: 'line',
          data: { labels: cur.series.labels, datasets },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: { legend: { labels: { color: colors.textPrimary } } },
            scales: {
              x: { grid: { color: colors.gridColor }, ticks: { color: colors.textSecondary } },
              y: { position: 'left', grid: { color: colors.gridColor }, ticks: { color: 'rgba(102,126,234,0.95)' } },
              y1: { position: 'right', grid: { drawOnChartArea: false }, ticks: { color: 'rgba(245,87,108,0.90)' } }
            }
          }
        });
      }

      modal.classList.add('show');
    };

    // Initial render
    initAccountSelector();
    updateDashboard('custom');
  </script>
</body>
</html>
"""


_TWO_PHASE_BYPASS: ContextVar[bool] = ContextVar("_TWO_PHASE_BYPASS", default=False)


@dataclass(frozen=True)
class PendingWriteAction:
    tool: str
    args: dict[str, Any]
    created_at: float
    expires_at: float


@dataclass
class AppContext:
    config: AppConfig
    tokens: TokenManager
    audience_tokens: TokenManager | None
    wordstat_tokens: TokenManager | None
    clients: YandexClients
    cache: TTLCache | None
    direct_rate_limiter: RateLimiter
    metrica_rate_limiter: RateLimiter
    audience_rate_limiter: RateLimiter
    wordstat_rate_limiter: RateLimiter
    direct_clients_cache: dict[str, object]
    direct_clients_cache_lock: threading.Lock
    direct_clients_cache_max_size: int = 8
    accounts_registry_lock: threading.Lock = field(default_factory=threading.Lock)
    accounts_registry_cache: dict[str, AccountProfile] | None = None
    accounts_registry_mtime: float | None = None
    pending_writes_lock: threading.Lock = field(default_factory=threading.Lock)
    pending_writes: dict[str, PendingWriteAction] = field(default_factory=dict)

    # Convenience wrappers so HF modules don't have to import server internals.
    def _direct_get(
        self,
        resource: str,
        params: dict[str, Any],
        *,
        direct_client_login: str | None = None,
    ) -> dict[str, Any]:
        return _direct_get(self, resource, params, direct_client_login=direct_client_login)

    def _direct_call(
        self,
        resource: str,
        method: str,
        params: dict[str, Any],
        *,
        direct_client_login: str | None = None,
    ) -> dict[str, Any]:
        return _direct_call(self, resource, method, params, direct_client_login=direct_client_login)

    def _direct_report(self, params: dict[str, Any], *, direct_client_login: str | None = None) -> dict[str, Any]:
        return _direct_report(self, params, direct_client_login=direct_client_login)

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

    def _wordstat_post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return _wordstat_post(self, path, payload)

    def _audience_call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _audience_call(self, method, path, params=params, payload=payload)


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
    if getattr(config, "audience_enabled", False):
        if config.audience_refresh_token and not (config.audience_client_id and config.audience_client_secret):
            missing.append("YANDEX_AUDIENCE_CLIENT_ID/YANDEX_AUDIENCE_CLIENT_SECRET")
    if getattr(config, "wordstat_enabled", False):
        if not config.wordstat_search_api_folder_id:
            missing.append("YANDEX_SEARCH_API_FOLDER_ID")
        if not (config.wordstat_search_api_api_key or config.wordstat_search_api_iam_token):
            missing.append("YANDEX_SEARCH_API_API_KEY or YANDEX_SEARCH_API_IAM_TOKEN")
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
    if name == "join.hf.direct_vs_metrica_by_yclid":
        # This join helper may create/clean Metrica Logs exports under the hood.
        # Treat as write unless the caller provides an existing request_id and disables cleanup.
        request_id = (args or {}).get("request_id")
        cleanup = (args or {}).get("cleanup")
        if request_id and cleanup is False:
            return False
        return True
    if name == "direct.raw_call":
        method = (args or {}).get("method") or "get"
        return str(method).lower() != "get"
    if name == "metrica.raw_call":
        method = (args or {}).get("method") or "get"
        return str(method).lower() != "get"
    if name.startswith("metrica.goals.") and name not in {"metrica.goals.list", "metrica.goals.get"}:
        return True
    if name == "audience.raw_call":
        method = (args or {}).get("method") or "GET"
        return str(method).upper() != "GET"
    if name.startswith("audience.segments.") and name not in {"audience.segments.list", "audience.segments.get", "audience.segments.stats", "audience.segments.overlap"}:
        return True
    if name.startswith("audience.upload."):
        return True
    if name == "audience.hf.apply_activation_plan":
        return True
    # HF tools execute writes only when apply=true; enforce base write guardrails then.
    if name.startswith("direct.hf.") and (args or {}).get("apply"):
        return True
    if name.startswith("metrica.hf.") and (args or {}).get("apply"):
        return True
    return False


def _enforce_write_guard(config: AppConfig, name: str, args: dict[str, Any] | None = None) -> None:
    if not _is_write_tool(name, args):
        return
    provider = "direct"
    if name.startswith(("audience.", "audience.hf.")) or name == "audience.raw_call":
        provider = "audience"
    if name.startswith("metrica."):
        provider = "metrica"
    if getattr(config, "public_readonly", False):
        raise WriteGuardError(
            "public",
            "Write operations are disabled in public read-only mode.",
            "Use the pro edition or run without MCP_PUBLIC_READONLY=true.",
        )
    if not config.write_enabled:
        raise WriteGuardError(
            provider,
            "Write operations are disabled.",
            "Set MCP_WRITE_ENABLED=true to allow write operations.",
        )
    if config.write_sandbox_only and not config.use_sandbox:
        raise WriteGuardError(
            provider,
            "Write operations are allowed only in sandbox.",
            "Set YANDEX_DIRECT_SANDBOX=true or disable MCP_WRITE_SANDBOX_ONLY.",
        )


def _pending_writes_cleanup(ctx: AppContext) -> None:
    now = time.monotonic()
    with ctx.pending_writes_lock:
        expired = [token for token, action in ctx.pending_writes.items() if action.expires_at <= now]
        for token in expired:
            ctx.pending_writes.pop(token, None)


def _pending_write_put(ctx: AppContext, *, tool: str, args: dict[str, Any]) -> tuple[str, int]:
    _pending_writes_cleanup(ctx)
    ttl = int(getattr(ctx.config, "confirm_ttl_seconds", 300) or 300)
    ttl = max(30, ttl)
    now = time.monotonic()
    token = secrets.token_urlsafe(24)
    action = PendingWriteAction(tool=tool, args=dict(args), created_at=now, expires_at=now + ttl)
    with ctx.pending_writes_lock:
        ctx.pending_writes[token] = action
    return token, ttl


def _pending_write_pop(ctx: AppContext, *, confirm_token: str) -> PendingWriteAction | None:
    _pending_writes_cleanup(ctx)
    with ctx.pending_writes_lock:
        return ctx.pending_writes.pop(confirm_token, None)


def _two_phase_planned_payload(
    tool: str, *, confirm_token: str, args: dict[str, Any], ttl_seconds: int
) -> dict[str, Any]:
    return {
        "tool": tool,
        "status": "planned",
        "result": {
            "confirm_token": confirm_token,
            "plan": {
                "summary": f"Planned write for {tool}. Call write.confirm(confirm_token) to execute.",
                "args_keys": sorted([str(k) for k in (args or {}).keys()]),
                "ttl_seconds": int(ttl_seconds),
            },
        },
    }


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
        if tool.startswith("direct.") and not _is_write_tool(tool, args):
            resolved = dict(args)
            fallback_login = _normalize_direct_client_login(resolved.get("direct_client_login")) or account_id
            resolved["direct_client_login"] = fallback_login
            resolved.pop("account_id", None)
            return resolved
        available = ", ".join(sorted((accounts or {}).keys()))
        raise ValueError(f"Unknown account_id: {account_id}. Available: {available or '<none>'}")

    resolved = dict(args)

    # Direct: resolve Client-Login
    if tool.startswith(("direct.", "direct.hf.", "join.hf.", "dashboard.", "audience.hf.")):
        explicit_login = _normalize_direct_client_login(resolved.get("direct_client_login"))
        profile_login = _normalize_direct_client_login(profile.direct_client_login)
        if explicit_login and profile_login and explicit_login != profile_login:
            if _is_write_tool(tool, args):
                raise ValueError(
                    f"direct_client_login={explicit_login} conflicts with account_id={account_id} "
                    f"(direct_client_login={profile_login})"
                )
        if not explicit_login and profile_login:
            resolved["direct_client_login"] = profile_login

    # Metrica: resolve counter_id if the tool expects it
    needs_counter = tool.startswith(
        (
            "metrica.report",
            "metrica.counter_info",
            "metrica.logs_export",
            "metrica.hf.",
            "join.hf.",
            "dashboard.",
        )
    ) or tool in {"audience.hf.segment_perf"}
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

    wordstat_block = data.get("wordstat")
    if isinstance(wordstat_block, dict) and wordstat_block.get("available") and isinstance(wordstat_block.get("campaigns"), list):
        campaigns = [c for c in wordstat_block["campaigns"] if isinstance(c, dict)]
        for c in campaigns[:3]:
            cname = str(c.get("campaign_name") or c.get("campaign_id") or "").strip()
            items = c.get("candidates")
            if not cname or not isinstance(items, list) or not items:
                continue
            top = []
            for it in items[:5]:
                if isinstance(it, dict) and it.get("phrase"):
                    top.append(str(it["phrase"]))
            if top:
                notes.append(f"Wordstat идеи для «{cname}»: " + ", ".join(top))

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


def _dashboard_micros_to_rub(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value) / 1_000_000.0
    except Exception:
        return None


def _dashboard_hf_warning_message(item: Any) -> str:
    if isinstance(item, dict):
        code = str(item.get("code") or "warning")
        message = str(item.get("message") or code)
        return f"{code}: {message}"
    return str(item)


def _dashboard_extract_report_payload(report_payload: dict[str, Any]) -> tuple[str, list[str] | None]:
    if isinstance(report_payload.get("raw"), str):
        columns = report_payload.get("columns") if isinstance(report_payload.get("columns"), list) else None
        return report_payload["raw"], columns
    result = report_payload.get("result")
    if isinstance(result, dict) and isinstance(result.get("raw"), str):
        columns = result.get("columns") if isinstance(result.get("columns"), list) else None
        return result["raw"], columns
    return "", None


def _dashboard_parse_report_rows(report_payload: dict[str, Any], *, max_rows: int | None = None) -> list[dict[str, str]]:
    raw, columns = _dashboard_extract_report_payload(report_payload)
    rows = _dashboard_parse_delimited(raw, delimiter="\t", columns=columns)
    if max_rows is not None:
        return rows[: max(0, int(max_rows))]
    return rows


def _dashboard_daily_totals(
    daily: list[dict[str, Any]],
    *,
    start_s: str,
    end_s: str,
    fields: list[str],
) -> dict[str, float]:
    totals = {field: 0.0 for field in fields}
    for row in daily or []:
        if not isinstance(row, dict):
            continue
        day = str(row.get("date") or "").strip()
        if not day or day < start_s or day > end_s:
            continue
        for field in fields:
            totals[field] += _dashboard_float_or_zero(row.get(field))
    return totals


def _dashboard_pct_change(cur: float | None, prev: float | None) -> float | None:
    try:
        if cur is None or prev is None:
            return None
        prev_f = float(prev)
        cur_f = float(cur)
        if prev_f == 0.0:
            return 0.0 if cur_f == 0.0 else None
        return ((cur_f / prev_f) - 1.0) * 100.0
    except Exception:
        return None


def _dashboard_findings_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"high": 0, "medium": 0, "low": 0, "info": 0}
    for item in items:
        severity = str(item.get("severity") or "info").lower()
        if severity not in counts:
            severity = "info"
        counts[severity] += 1
    return counts


def _dashboard_build_pro_account_data(ctx: AppContext, *, args: dict[str, Any], base_data: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    meta = (base_data.get("meta") or {}) if isinstance(base_data, dict) else {}
    direct_block = (base_data.get("direct") or {}) if isinstance(base_data, dict) else {}
    metrica_block = (base_data.get("metrica") or {}) if isinstance(base_data, dict) else {}
    campaign_data = direct_block.get("campaign_data") or {}
    campaign_summaries = direct_block.get("campaign_summaries") or {}
    direct_by_campaign = metrica_block.get("direct_by_campaign") or {}
    current_from_s = str(meta.get("date_from") or "")
    current_to_s = str(meta.get("date_to") or "")
    prev_from_s = str(meta.get("prev_date_from") or "")
    prev_to_s = str(meta.get("prev_date_to") or "")
    if not current_from_s or not current_to_s:
        return {"available": False, "warnings": ["missing current date range in base dashboard payload"]}

    total_cost_rub = _dashboard_float_or_zero((((direct_block.get("current") or {}).get("totals") or {}).get("cost_rub")))
    max_campaigns = max(1, min(50, int(args.get("max_campaigns") or 12)))
    max_keywords = max(1, min(500, int(args.get("max_keywords") or 100)))
    max_search_phrases = max(1, min(1000, int(args.get("max_search_phrases") or 200)))
    max_findings = max(1, min(100, int(args.get("max_findings") or 24)))

    scoped = _RequestScopedContext(ctx, args.get("direct_client_login"))

    def _collect_hf_report_rows(tool: str, *, max_rows: int) -> list[dict[str, str]]:
        payload = hf_direct_handle(
            tool,
            scoped,
            {
                "date_from": current_from_s,
                "date_to": current_to_s,
            },
        )
        if str(payload.get("status") or "") != "ok":
            warnings.append(f"{tool} returned status={payload.get('status')}")
            return []
        for item in payload.get("warnings") or []:
            warnings.append(f"{tool}: {_dashboard_hf_warning_message(item)}")
        return _dashboard_parse_report_rows(payload, max_rows=max_rows)

    search_phrase_rows_raw = _collect_hf_report_rows("direct.hf.report_search_phrases", max_rows=max_search_phrases)
    keyword_rows_raw = _collect_hf_report_rows("direct.hf.report_keywords", max_rows=max_keywords)

    search_phrase_rows: list[dict[str, Any]] = []
    for row in search_phrase_rows_raw:
        impressions = _dashboard_float_or_zero(row.get("Impressions"))
        clicks = _dashboard_float_or_zero(row.get("Clicks"))
        cost_rub = _dashboard_float_or_zero(row.get("Cost"))
        ctr = 100.0 * clicks / impressions if impressions > 0 else None
        search_phrase_rows.append(
            {
                "query": str(row.get("Query") or "").strip(),
                "matched_keyword": str(row.get("MatchedKeyword") or "").strip(),
                "match_type": str(row.get("MatchType") or "").strip(),
                "campaign_id": str(row.get("CampaignId") or "").strip(),
                "adgroup_id": str(row.get("AdGroupId") or "").strip(),
                "impressions": impressions,
                "clicks": clicks,
                "cost_rub": cost_rub,
                "ctr": ctr,
            }
        )
    search_phrase_rows.sort(key=lambda item: (float(item.get("cost_rub") or 0.0), float(item.get("clicks") or 0.0)), reverse=True)

    keyword_rows: list[dict[str, Any]] = []
    for row in keyword_rows_raw:
        impressions = _dashboard_float_or_zero(row.get("Impressions"))
        clicks = _dashboard_float_or_zero(row.get("Clicks"))
        cost_rub = _dashboard_float_or_zero(row.get("Cost"))
        bounces = _dashboard_float_or_zero(row.get("Bounces"))
        ctr = 100.0 * clicks / impressions if impressions > 0 else None
        bounce_rate = 100.0 * bounces / clicks if clicks > 0 else None
        keyword_rows.append(
            {
                "keyword": str(row.get("Criterion") or "").strip(),
                "criterion_id": str(row.get("CriterionId") or "").strip(),
                "criterion_type": str(row.get("CriterionType") or "").strip(),
                "campaign_id": str(row.get("CampaignId") or "").strip(),
                "adgroup_id": str(row.get("AdGroupId") or "").strip(),
                "impressions": impressions,
                "clicks": clicks,
                "cost_rub": cost_rub,
                "bounces": bounces,
                "ctr": ctr,
                "bounce_rate": bounce_rate,
            }
        )
    keyword_rows.sort(key=lambda item: (float(item.get("cost_rub") or 0.0), float(item.get("clicks") or 0.0)), reverse=True)

    watchlist_rows: list[dict[str, Any]] = []
    top_campaign_ids = sorted(
        [str(cid) for cid in campaign_summaries.keys()],
        key=lambda cid: _dashboard_float_or_zero(
            (((campaign_summaries.get(cid) or {}).get("current") or {}).get("cost_rub"))
        ),
        reverse=True,
    )[:max_campaigns]

    bid_campaign_rows: list[dict[str, Any]] = []
    for cid in top_campaign_ids[: min(8, max_campaigns)]:
        try:
            payload = hf_direct_handle("direct.hf.get_bids_summary", scoped, {"campaign_id": int(cid)})
            if str(payload.get("status") or "") != "ok":
                continue
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            count = int(result.get("count") or 0)
            if count <= 0:
                continue
            bid_campaign_rows.append(
                {
                    "campaign_id": str(cid),
                    "count": count,
                    "min_rub": _dashboard_micros_to_rub(result.get("min")),
                    "avg_rub": _dashboard_micros_to_rub(result.get("avg")),
                    "max_rub": _dashboard_micros_to_rub(result.get("max")),
                }
            )
        except Exception as exc:
            warnings.append(f"bids summary failed for campaign {cid}: {exc.__class__.__name__}")

    bids_by_campaign = {row["campaign_id"]: row for row in bid_campaign_rows}
    direct_campaigns_map = direct_by_campaign.get("campaigns") if isinstance(direct_by_campaign, dict) else {}
    if not isinstance(direct_campaigns_map, dict):
        direct_campaigns_map = {}

    for cid in top_campaign_ids:
        summary = (campaign_summaries.get(cid) or {}) if isinstance(campaign_summaries, dict) else {}
        current = (summary.get("current") or {}) if isinstance(summary, dict) else {}
        prev = (summary.get("prev") or {}) if isinstance(summary, dict) else {}
        daily_metrica = ((direct_campaigns_map.get(cid) or {}).get("daily") or []) if isinstance(direct_campaigns_map, dict) else []
        current_metrica = _dashboard_daily_totals(daily_metrica, start_s=current_from_s, end_s=current_to_s, fields=["visits", "leads", "engaged"])
        prev_metrica = _dashboard_daily_totals(daily_metrica, start_s=prev_from_s, end_s=prev_to_s, fields=["visits", "leads", "engaged"]) if prev_from_s and prev_to_s else {"visits": 0.0, "leads": 0.0, "engaged": 0.0}
        leads_cur = float(current_metrica.get("leads") or 0.0)
        leads_prev = float(prev_metrica.get("leads") or 0.0)
        cost_cur = _dashboard_float_or_zero(current.get("cost_rub"))
        cpl_cur = _dashboard_safe_div(cost_cur, leads_cur) if leads_cur > 0 else None
        clicks_delta = (summary.get("change") or {}).get("clicks_pct") if isinstance(summary.get("change"), dict) else None
        cost_delta = (summary.get("change") or {}).get("cost_pct") if isinstance(summary.get("change"), dict) else None
        leads_delta = _dashboard_pct_change(leads_cur, leads_prev)
        watchlist_rows.append(
            {
                "campaign_id": cid,
                "name": summary.get("name") or f"#{cid}",
                "short_name": summary.get("shortName") or summary.get("name") or f"#{cid}",
                "type": summary.get("type") or "unknown",
                "impressions": _dashboard_float_or_zero(current.get("impressions")),
                "clicks": _dashboard_float_or_zero(current.get("clicks")),
                "cost_rub": cost_cur,
                "ctr": current.get("ctr"),
                "cpc": current.get("cpc"),
                "visits": float(current_metrica.get("visits") or 0.0),
                "engaged": float(current_metrica.get("engaged") or 0.0),
                "leads": leads_cur,
                "cpl": cpl_cur,
                "clicks_delta_pct": clicks_delta,
                "cost_delta_pct": cost_delta,
                "leads_delta_pct": leads_delta,
                "avg_bid_rub": (bids_by_campaign.get(cid) or {}).get("avg_rub"),
            }
        )

    findings: list[dict[str, Any]] = []
    search_cost_threshold = max(1200.0, total_cost_rub * 0.03)
    for row in search_phrase_rows[:20]:
        cost_rub = float(row.get("cost_rub") or 0.0)
        clicks = float(row.get("clicks") or 0.0)
        ctr = row.get("ctr")
        if cost_rub < search_cost_threshold or clicks < 5:
            continue
        severity = "high" if (ctr is not None and float(ctr) < 2.0) else "medium"
        findings.append(
            {
                "severity": severity,
                "category": "search_terms",
                "title": f"Search phrase '{row.get('query') or '—'}' consumes spend with weak click quality",
                "entity_label": row.get("query") or "—",
                "campaign_id": row.get("campaign_id"),
                "adgroup_id": row.get("adgroup_id"),
                "metrics": {
                    "cost_rub": cost_rub,
                    "clicks": clicks,
                    "ctr": ctr,
                },
                "recommendation": "Проверьте запрос, соответствие keyword intent и список минус-слов.",
            }
        )
        if len(findings) >= max_findings:
            break

    keyword_cost_threshold = max(1000.0, total_cost_rub * 0.025)
    for row in keyword_rows[:20]:
        cost_rub = float(row.get("cost_rub") or 0.0)
        clicks = float(row.get("clicks") or 0.0)
        bounce_rate = row.get("bounce_rate")
        if cost_rub < keyword_cost_threshold or clicks < 6:
            continue
        if bounce_rate is None or float(bounce_rate) < 55.0:
            continue
        findings.append(
            {
                "severity": "medium",
                "category": "keywords",
                "title": f"Keyword '{row.get('keyword') or '—'}' drives expensive, low-quality visits",
                "entity_label": row.get("keyword") or "—",
                "campaign_id": row.get("campaign_id"),
                "adgroup_id": row.get("adgroup_id"),
                "criterion_id": row.get("criterion_id"),
                "metrics": {
                    "cost_rub": cost_rub,
                    "clicks": clicks,
                    "bounce_rate": bounce_rate,
                },
                "recommendation": "Проверьте посадочную, соответствие оффера и сегментацию keyword/adgroup.",
            }
        )
        if len(findings) >= max_findings:
            break

    campaign_cost_threshold = max(2500.0, total_cost_rub * 0.08)
    for row in watchlist_rows:
        cost_rub = float(row.get("cost_rub") or 0.0)
        clicks = float(row.get("clicks") or 0.0)
        leads = float(row.get("leads") or 0.0)
        if cost_rub >= campaign_cost_threshold and clicks >= 10 and leads <= 0:
            findings.append(
                {
                    "severity": "high",
                    "category": "campaigns",
                    "title": f"Campaign '{row.get('short_name') or row.get('name')}' spends with no attributed leads",
                    "entity_label": row.get("short_name") or row.get("name") or "—",
                    "campaign_id": row.get("campaign_id"),
                    "metrics": {
                        "cost_rub": cost_rub,
                        "clicks": clicks,
                        "visits": row.get("visits"),
                        "leads": leads,
                    },
                    "recommendation": "Проверьте intent, посадочную и корректность атрибуции по UTMCampaign.",
                }
            )
        elif (row.get("cost_delta_pct") or 0) > 20 and (row.get("leads_delta_pct") is None or float(row.get("leads_delta_pct") or 0.0) <= 0.0):
            findings.append(
                {
                    "severity": "medium",
                    "category": "campaigns",
                    "title": f"Campaign '{row.get('short_name') or row.get('name')}' grows in spend without lead growth",
                    "entity_label": row.get("short_name") or row.get("name") or "—",
                    "campaign_id": row.get("campaign_id"),
                    "metrics": {
                        "cost_delta_pct": row.get("cost_delta_pct"),
                        "clicks_delta_pct": row.get("clicks_delta_pct"),
                        "leads_delta_pct": row.get("leads_delta_pct"),
                    },
                    "recommendation": "Проверьте ставки, поисковые запросы и изменения в оффере/креативах.",
                }
            )
        if len(findings) >= max_findings:
            break

    tracking_gaps: dict[str, Any] = {"available": False}
    tracking_meta = (metrica_block.get("direct_split") or {}).get("meta") if isinstance(metrica_block.get("direct_split"), dict) else None
    if isinstance(tracking_meta, dict):
        tracking_gaps = {
            "available": True,
            "classified_share_pct": tracking_meta.get("classified_share_pct"),
            "classified_leads_share_pct": tracking_meta.get("classified_leads_share_pct"),
            "top_unclassified_utm": tracking_meta.get("top_unclassified_utm") or [],
            "method": (metrica_block.get("direct_split") or {}).get("method"),
        }
        share = tracking_meta.get("classified_share_pct")
        unknown = tracking_meta.get("top_unclassified_utm") or []
        if share is not None and float(share) < 85.0:
            findings.append(
                {
                    "severity": "high",
                    "category": "tracking",
                    "title": "A meaningful share of Direct visits could not be classified by UTMCampaign",
                    "entity_label": "UTMCampaign mapping",
                    "metrics": {
                        "classified_share_pct": share,
                        "top_unclassified_count": len(unknown) if isinstance(unknown, list) else 0,
                    },
                    "recommendation": "Нормализуйте utm_campaign: используйте campaign_id или уникальное стабильное имя кампании.",
                }
            )
        elif isinstance(unknown, list) and unknown:
            findings.append(
                {
                    "severity": "medium",
                    "category": "tracking",
                    "title": "Unclassified UTMCampaign values are still present in Direct-attributed traffic",
                    "entity_label": "UTMCampaign mapping",
                    "metrics": {
                        "top_unclassified_count": len(unknown),
                    },
                    "recommendation": "Проверьте top unclassified UTMCampaign values и унифицируйте шаблон разметки.",
                }
            )

    findings = findings[:max_findings]
    counts = _dashboard_findings_counts(findings)
    today_actions: list[str] = []
    if findings:
        for item in findings[:5]:
            today_actions.append(str(item.get("recommendation") or item.get("title") or "Проверить диагностический блок PRO."))
    else:
        today_actions.append("Критичных PRO-findings не найдено; проверьте top search phrases и campaign watchlist вручную.")

    top_search_terms = search_phrase_rows[: min(15, max_search_phrases)]
    top_keywords = keyword_rows[: min(15, max_keywords)]
    watchlist_by_campaign = {
        str(row.get("campaign_id") or ""): row
        for row in watchlist_rows
        if str(row.get("campaign_id") or "").strip()
    }
    bid_summary_by_campaign = {
        str(row.get("campaign_id") or ""): row
        for row in bid_campaign_rows
        if str(row.get("campaign_id") or "").strip()
    }
    by_campaign: dict[str, Any] = {}
    campaign_ids = {
        *[str(x).strip() for x in top_campaign_ids if str(x).strip()],
        *[str((row.get("campaign_id") or "")).strip() for row in search_phrase_rows if str((row.get("campaign_id") or "")).strip()],
        *[str((row.get("campaign_id") or "")).strip() for row in keyword_rows if str((row.get("campaign_id") or "")).strip()],
        *[str((item.get("campaign_id") or "")).strip() for item in findings if str((item.get("campaign_id") or "")).strip()],
    }
    for cid in sorted(campaign_ids):
        watch = watchlist_by_campaign.get(cid) or {}
        campaign_search_terms = [row for row in search_phrase_rows if str(row.get("campaign_id") or "") == cid][:8]
        campaign_keywords = [row for row in keyword_rows if str(row.get("campaign_id") or "") == cid][:8]
        campaign_findings = [item for item in findings if str(item.get("campaign_id") or "") == cid][:8]
        bid_summary = bid_summary_by_campaign.get(cid)
        tracking_notes: list[str] = []
        if tracking_gaps.get("available"):
            if float(watch.get("cost_rub") or 0.0) > 0.0 and float(watch.get("visits") or 0.0) <= 0.0:
                tracking_notes.append("Есть расход без визитов Metrica в attribution mapping: проверьте utm_campaign и counter binding.")
            if tracking_gaps.get("classified_share_pct") is not None and float(tracking_gaps.get("classified_share_pct") or 0.0) < 85.0:
                tracking_notes.append(
                    f"Общий UTM coverage по dashboard = {float(tracking_gaps.get('classified_share_pct') or 0.0):.1f}%."
                )
        today_actions_campaign: list[str] = []
        for item in campaign_findings:
            rec = str(item.get("recommendation") or "").strip()
            if rec and rec not in today_actions_campaign:
                today_actions_campaign.append(rec)
        if not today_actions_campaign and tracking_notes:
            today_actions_campaign.append(tracking_notes[0])
        by_campaign[cid] = {
            "available": bool(watch or campaign_search_terms or campaign_keywords or campaign_findings or bid_summary or tracking_notes),
            "watchlist": watch,
            "search_terms": campaign_search_terms,
            "keywords": campaign_keywords,
            "findings": campaign_findings,
            "bid_summary": bid_summary,
            "tracking_notes": tracking_notes,
            "today_actions": today_actions_campaign[:4],
        }

    return {
        "available": True,
        "warnings": warnings,
        "summary": {
            "findings_total": len(findings),
            "findings_by_severity": counts,
            "search_terms_rows": len(search_phrase_rows),
            "keywords_rows": len(keyword_rows),
            "watchlist_rows": len(watchlist_rows),
            "bids_campaigns": len(bid_campaign_rows),
        },
        "blocks": {
            "top_search_terms": top_search_terms,
            "top_keywords": top_keywords,
            "campaign_watchlist": watchlist_rows,
            "tracking_gaps": tracking_gaps,
            "bid_summary": {
                "available": bool(bid_campaign_rows),
                "campaigns": bid_campaign_rows,
            },
        },
        "findings": {
            "items": findings,
            "counts": counts,
        },
        "by_campaign": by_campaign,
        "recommendations": {
            "today_actions": today_actions[:5],
        },
    }


def _dashboard_wordstat_clean_seed(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    # Basic cleanup for Direct keyword operators/syntax.
    value = value.replace("!", " ").replace("+", " ").replace('"', " ").replace("'", " ")
    value = re.sub(r"[\[\]\(\)\{\}]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _dashboard_build_wordstat_block(
    ctx: AppContext,
    *,
    args: dict[str, Any],
    campaign_data: dict[str, Any],
    date_from: str,
    date_to: str,
    warnings: list[str],
) -> dict[str, Any] | None:
    if not bool(args.get("include_wordstat")):
        return None

    if not getattr(ctx.config, "wordstat_enabled", False):
        return {"available": False, "reason": "disabled"}
    if not getattr(ctx.config, "wordstat_search_api_folder_id", None) or not (
        getattr(ctx.config, "wordstat_search_api_api_key", None)
        or getattr(ctx.config, "wordstat_search_api_iam_token", None)
    ):
        return {"available": False, "reason": "not_configured"}

    max_campaigns = int(args.get("wordstat_max_campaigns") or 5)
    max_campaigns = max(1, min(20, max_campaigns))
    max_seeds = int(args.get("wordstat_max_seed_phrases_per_campaign") or 3)
    max_seeds = max(1, min(10, max_seeds))
    num_phrases = int(args.get("wordstat_num_phrases") or 50)
    if num_phrases <= 0 or num_phrases > 2000:
        num_phrases = 50
    max_candidates = int(args.get("wordstat_max_candidates_per_campaign") or 20)
    max_candidates = max(5, min(200, max_candidates))
    max_negatives = int(args.get("wordstat_max_negatives_per_campaign") or 25)
    max_negatives = max(0, min(200, max_negatives))
    language = str(args.get("wordstat_language") or "ru").strip().lower() or "ru"

    regions = args.get("wordstat_regions")
    devices = args.get("wordstat_devices")

    # Pick top campaigns by clicks in the requested period.
    scored: list[tuple[str, float]] = []
    for cid, meta in (campaign_data or {}).items():
        if not isinstance(meta, dict):
            continue
        daily = meta.get("daily")
        if not isinstance(daily, list):
            continue
        clicks = 0.0
        for row in daily:
            if not isinstance(row, dict):
                continue
            day = str(row.get("date") or "")
            if not day or day < date_from or day > date_to:
                continue
            clicks += float(row.get("clicks") or 0.0)
        if clicks > 0:
            scored.append((str(cid), clicks))
    scored.sort(key=lambda x: x[1], reverse=True)
    top_campaign_ids = [cid for cid, _ in scored[:max_campaigns]]
    if not top_campaign_ids:
        return {"available": False, "reason": "no_campaigns"}

    # Fetch keywords for these campaigns (best-effort, first page only to bound size).
    kw_by_campaign: dict[str, list[str]] = {}
    try:
        kw_res = _direct_get(
            ctx,
            "keywords",
            {
                "SelectionCriteria": {"CampaignIds": [int(x) for x in top_campaign_ids]},
                "FieldNames": ["CampaignId", "Keyword"],
                "Page": {"Limit": 1000, "Offset": 0},
            },
            direct_client_login=args.get("direct_client_login"),
        )
        items = (kw_res.get("result") or {}).get("Keywords", []) if isinstance(kw_res, dict) else []
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                cid = it.get("CampaignId")
                kw = it.get("Keyword")
                if cid is None or not isinstance(kw, str):
                    continue
                cid_s = str(cid)
                kw_clean = _dashboard_wordstat_clean_seed(kw)
                if not kw_clean:
                    continue
                kw_by_campaign.setdefault(cid_s, []).append(kw_clean)
    except Exception as exc:
        warnings.append(f"Wordstat seeds: failed to fetch Direct keywords: {exc.__class__.__name__}")

    campaigns_out: list[dict[str, Any]] = []
    for cid in top_campaign_ids:
        meta = campaign_data.get(cid) if isinstance(campaign_data, dict) else None
        cname = None
        if isinstance(meta, dict):
            cname = meta.get("name")
        name = str(cname or f"#{cid}")

        seeds: list[str] = []
        seen: set[str] = set()
        for kw in kw_by_campaign.get(cid, []):
            if kw in seen:
                continue
            seen.add(kw)
            seeds.append(kw)
            if len(seeds) >= max_seeds:
                break
        if not seeds:
            # Fallback: use campaign name as a seed (often worse than keywords, but better than nothing).
            seeds = [_dashboard_wordstat_clean_seed(name)]
            seeds = [s for s in seeds if s]

        acc: dict[str, dict[str, Any]] = {}
        for seed in seeds:
            try:
                payload: dict[str, Any] = {"phrase": seed, "numPhrases": num_phrases}
                if isinstance(regions, list) and regions:
                    payload["regions"] = [int(x) for x in regions]
                if isinstance(devices, list) and devices:
                    payload["devices"] = [str(x) for x in devices if str(x).strip()]
                resp = _wordstat_post(ctx, "topRequests", payload)
                for it in wordstat_provider_items(resp):
                    merge_wordstat_candidate(
                        acc,
                        phrase=str(it["phrase"]),
                        score=float(it["score"]),
                        seed=seed,
                        provider_source=str(it["provider_source"]),
                    )
            except Exception as exc:
                warnings.append(f"Wordstat topRequests failed for campaign {cid}: {exc.__class__.__name__}")

        candidates = [
            {
                "phrase": phrase,
                "score": float(meta.get("score") or 0.0),
                "sources": meta.get("sources") or [],
                "provider_sources": meta.get("provider_sources") or [],
            }
            for phrase, meta in sorted(acc.items(), key=lambda x: float(x[1].get("score") or 0.0), reverse=True)[
                :max_candidates
            ]
        ]
        negatives: list[dict[str, Any]] = []
        if max_negatives > 0 and candidates:
            try:
                neg_payload = hf_wordstat_handle(
                    "wordstat.hf.suggest_negative_keywords",
                    ctx,
                    {
                        "phrases": [c.get("phrase") for c in candidates if isinstance(c, dict) and c.get("phrase")],
                        "language": language,
                        "max_candidates": max_negatives,
                    },
                )
                negs = (neg_payload.get("result") or {}).get("negatives") if isinstance(neg_payload, dict) else None
                if isinstance(negs, list):
                    negatives = [x for x in negs if isinstance(x, dict)]
            except Exception:
                negatives = []
        campaigns_out.append(
            {
                "campaign_id": cid,
                "campaign_name": name,
                "seeds": seeds,
                "candidates": candidates,
                "negatives": negatives,
            }
        )

    return {
        "available": True,
        "meta": {
            "max_campaigns": max_campaigns,
            "max_seeds_per_campaign": max_seeds,
            "num_phrases": num_phrases,
            "max_candidates_per_campaign": max_candidates,
            "max_negatives_per_campaign": max_negatives,
            "language": language,
        },
        "campaigns": campaigns_out,
    }


def _dashboard_build_audience_block(
    ctx: AppContext,
    *,
    args: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any] | None:
    if not bool(args.get("include_audience")):
        return None
    if not getattr(ctx.config, "audience_enabled", False):
        return {"available": False, "reason": "disabled"}
    if ctx.audience_tokens is None or not ctx.audience_tokens.get_access_token():
        return {"available": False, "reason": "not_configured"}

    limit = 50
    try:
        raw = ctx._audience_call("GET", "/segments", params={"limit": limit, "offset": 0})
    except Exception as exc:  # pragma: no cover
        warnings.append(f"Audience: failed to list segments: {exc.__class__.__name__}")
        return {"available": False, "reason": "error"}

    seg_items = raw.get("segments")
    if not isinstance(seg_items, list):
        seg_items = raw.get("items") if isinstance(raw.get("items"), list) else []

    segments: list[dict[str, Any]] = []
    for s in seg_items:
        if not isinstance(s, dict):
            continue
        seg_id = str(s.get("id") or s.get("segment_id") or "").strip()
        if not seg_id:
            continue
        size = None
        for k in ("size", "audience_size", "users", "count"):
            if s.get(k) is not None:
                try:
                    size = int(s.get(k))
                except Exception:
                    size = None
                break
        updated_at = s.get("updated_at") or s.get("updated") or s.get("modified_at")
        status = s.get("status")
        hints: list[str] = []
        if isinstance(size, int) and size < 1000:
            hints.append("small_size")
        if str(status or "").lower() not in {"ready", "active", "available", "ok"}:
            hints.append("status_not_ready")
        segments.append(
            {
                "id": seg_id,
                "name": s.get("name"),
                "type": s.get("type"),
                "status": status,
                "updated_at": updated_at,
                "size": size,
                "health": {"status": "ok" if not hints else "warning", "hints": hints},
            }
        )
    segments = segments[:limit]

    overlaps: list[dict[str, Any]] = []
    seg_ids = [s["id"] for s in segments[:20] if isinstance(s.get("id"), str) and s.get("id")]
    if len(seg_ids) >= 2:
        try:
            ov = ctx._audience_call(
                "POST",
                "/segments/overlap",
                payload={"segment_ids": seg_ids, "mode": "top_pairs", "limit": 30},
            )
            pairs = ov.get("pairs")
            if isinstance(pairs, list):
                for p in pairs:
                    if not isinstance(p, dict):
                        continue
                    a = p.get("a") or p.get("segment_a") or p.get("id_a")
                    b = p.get("b") or p.get("segment_b") or p.get("id_b")
                    if a is None or b is None:
                        continue
                    overlaps.append(
                        {
                            "a": str(a),
                            "b": str(b),
                            "overlap_share": p.get("overlap_share") or p.get("share"),
                            "overlap_abs": p.get("overlap_abs") or p.get("count"),
                        }
                    )
        except Exception:  # pragma: no cover
            warnings.append("Audience: overlap computation failed (best effort).")

    return {
        "available": True,
        "segments": segments,
        "top_overlaps": overlaps,
        "raw_refs": [
            {"tool": "audience.segments.list", "limit": limit},
            {"tool": "audience.segments.overlap", "segment_ids": seg_ids, "mode": "top_pairs"},
        ],
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


def _dashboard_campaign_type_from_id(*, campaign_id: str, campaign_data: dict[str, Any]) -> str | None:
    cid = (campaign_id or "").strip()
    if not cid:
        return None
    t = str((campaign_data.get(cid) or {}).get("type") or "").strip()
    return t if t in {"search", "rsya"} else None


def _dashboard_campaign_id_from_metrica_direct_dim(
    *,
    dim: Any,
    campaign_data: dict[str, Any],
    name_index: dict[str, list[str]],
) -> str | None:
    """Best-effort extract Direct campaign id from Metrica `lastsignDirectClickOrder` dimension.

    In practice Metrica can return objects like:
      {id: "...", name: "...", direct_id: "N-123456"}
    where `direct_id` contains the Direct campaign id.
    """
    if dim is None:
        return None

    if isinstance(dim, dict):
        direct_id = str(dim.get("direct_id") or "").strip()
        if direct_id:
            for m in re.findall(r"\b\d{6,}\b", direct_id):
                if m in campaign_data:
                    return m

        name = str(dim.get("name") or "").strip()
        if name:
            # Sometimes the campaign id is embedded in the name.
            for m in re.findall(r"\b\d{6,}\b", name):
                if m in campaign_data:
                    return m
            ids = name_index.get(name) or []
            if len(ids) == 1:
                return ids[0]

        return None

    name = str(dim).strip()
    if not name:
        return None
    for m in re.findall(r"\b\d{6,}\b", name):
        if m in campaign_data:
            return m
    ids = name_index.get(name) or []
    if len(ids) == 1:
        return ids[0]
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
    direct_campaign_ids_allowlist: set[str] | None = None,
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
    allowlist_rows_total = 0
    allowlist_rows_matched = 0

    for row in rows:
        if not isinstance(row, dict):
            continue
        dims = row.get("dimensions")
        mets = row.get("metrics")
        if not isinstance(dims, list) or not isinstance(mets, list) or len(dims) < 2 or len(mets) < 2:
            continue

        dim_date = dims[0] if isinstance(dims[0], dict) else {"name": str(dims[0])}
        dim_utm = dims[1] if isinstance(dims[1], dict) else {"name": str(dims[1])}
        dim_click_order = None
        if direct_campaign_ids_allowlist is not None:
            allowlist_rows_total += 1
            if len(dims) >= 3:
                dim_click_order = dims[2] if isinstance(dims[2], dict) else {"name": str(dims[2])}
            cid_allow = _dashboard_campaign_id_from_metrica_direct_dim(
                dim=dim_click_order, campaign_data=campaign_data, name_index=name_index
            )
            if not cid_allow or cid_allow not in direct_campaign_ids_allowlist:
                continue
            allowlist_rows_matched += 1

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
        cid = None
        if dim_click_order is not None:
            cid = _dashboard_campaign_id_from_metrica_direct_dim(
                dim=dim_click_order, campaign_data=campaign_data, name_index=name_index
            )
        if cid is None:
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

    if direct_campaign_ids_allowlist is not None and allowlist_rows_total > 0 and allowlist_rows_matched == 0:
        return {
            "available": False,
            "reason": "allowlist_no_matches",
            "meta": {
                "report_is_direct_only": bool(report_is_direct_only),
                "allowlist_rows_total": allowlist_rows_total,
                "allowlist_rows_matched": allowlist_rows_matched,
                "allowlist_size": len(direct_campaign_ids_allowlist),
            },
        }

    return {
        "available": True,
        "method": "utm_campaign",
        "meta": {
            "report_is_direct_only": bool(report_is_direct_only),
            "allowlist_rows_total": (allowlist_rows_total if direct_campaign_ids_allowlist is not None else None),
            "allowlist_rows_matched": (allowlist_rows_matched if direct_campaign_ids_allowlist is not None else None),
            "allowlist_size": (len(direct_campaign_ids_allowlist) if direct_campaign_ids_allowlist is not None else None),
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
    direct_campaign_ids_allowlist: set[str] | None = None,
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
    allowlist_rows_total = 0
    allowlist_rows_matched = 0

    for row in rows:
        if not isinstance(row, dict):
            continue
        dims = row.get("dimensions")
        mets = row.get("metrics")
        if not isinstance(dims, list) or not isinstance(mets, list) or len(dims) < 2 or len(mets) < 2:
            continue

        dim_date = dims[0] if isinstance(dims[0], dict) else {"name": str(dims[0])}
        dim_utm = dims[1] if isinstance(dims[1], dict) else {"name": str(dims[1])}
        dim_click_order = None
        if direct_campaign_ids_allowlist is not None:
            allowlist_rows_total += 1
            if len(dims) >= 3:
                dim_click_order = dims[2] if isinstance(dims[2], dict) else {"name": str(dims[2])}
            cid_allow = _dashboard_campaign_id_from_metrica_direct_dim(
                dim=dim_click_order, campaign_data=campaign_data, name_index=name_index
            )
            if not cid_allow or cid_allow not in direct_campaign_ids_allowlist:
                continue
            allowlist_rows_matched += 1

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
        t = None
        if dim_click_order is not None:
            cid = _dashboard_campaign_id_from_metrica_direct_dim(dim=dim_click_order, campaign_data=campaign_data, name_index=name_index)
            t = _dashboard_campaign_type_from_id(campaign_id=str(cid or ""), campaign_data=campaign_data) if cid else None
        if t is None:
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
    if direct_campaign_ids_allowlist is not None and allowlist_rows_total > 0 and allowlist_rows_matched == 0:
        return {
            "available": False,
            "reason": "allowlist_no_matches",
            "meta": {
                "report_is_direct_only": bool(report_is_direct_only),
                "allowlist_rows_total": allowlist_rows_total,
                "allowlist_rows_matched": allowlist_rows_matched,
                "allowlist_size": len(direct_campaign_ids_allowlist),
            },
        }
    return {
        "available": True,
        "method": "utm_campaign",
        "meta": {
            "report_is_direct_only": bool(report_is_direct_only),
            "allowlist_rows_total": (allowlist_rows_total if direct_campaign_ids_allowlist is not None else None),
            "allowlist_rows_matched": (allowlist_rows_matched if direct_campaign_ids_allowlist is not None else None),
            "allowlist_size": (len(direct_campaign_ids_allowlist) if direct_campaign_ids_allowlist is not None else None),
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
    # Important: report names must be unique per Direct client login in multi-account runs
    # to avoid collisions/cache reuse on the Direct Reports API side.
    report_identity = _dashboard_safe_slug(str(args.get("account_id") or args.get("direct_client_login") or "default"))
    direct_report_name = make_unique_report_name(f"dashboard_option1__{report_identity}__{fetch_from_s}_{fetch_to_s}")
    direct_report_args: dict[str, Any] = {
        "report_type": "CAMPAIGN_PERFORMANCE_REPORT",
        "report_name": direct_report_name,
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
            # `cost` is RUB for Direct verified accounts. Keep an alias to reduce LLM confusion
            # when mixing with `direct.current.daily.cost_rub`.
            daily.append(
                {
                    "date": day,
                    "impressions": imp,
                    "clicks": clk,
                    "cost": cost_rub,
                    "cost_rub": cost_rub,
                }
            )

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

    # Note: the UI can compute per-campaign period summaries client-side from `campaign_data`,
    # but LLM agents often fail to aggregate daily arrays correctly. Provide a compact, pre-aggregated
    # structure so agents can generate specific recommendations reliably.
    current_from_s = date_from_eff_s
    current_to_s = date_to_eff_s
    prev_from_s = _dashboard_to_ymd(prev_start)
    prev_to_s = _dashboard_to_ymd(prev_end)

    def _pct_change(cur: float | None, prev: float | None) -> float | None:
        try:
            if cur is None or prev is None:
                return None
            prev_f = float(prev)
            cur_f = float(cur)
            if prev_f == 0.0:
                return 0.0 if cur_f == 0.0 else None
            return ((cur_f / prev_f) - 1.0) * 100.0
        except Exception:
            return None

    def _campaign_totals(cid: str, start_s: str, end_s: str) -> dict[str, Any]:
        by_d = direct_by_campaign_date.get(cid) or {}
        impressions = 0.0
        clicks = 0.0
        cost_rub = 0.0
        if isinstance(by_d, dict):
            for day, vals in by_d.items():
                day_s = str(day or "").strip()
                if not day_s or day_s < start_s or day_s > end_s:
                    continue
                if not isinstance(vals, dict):
                    continue
                impressions += float(vals.get("impressions") or 0.0)
                clicks += float(vals.get("clicks") or 0.0)
                cost_rub += float(vals.get("cost_rub") or 0.0)
        out: dict[str, Any] = {
            "impressions": float(impressions),
            "clicks": float(clicks),
            # Prefer explicit naming; keep `cost` alias for convenience.
            "cost_rub": float(cost_rub),
            "cost": float(cost_rub),
            "cost_micros": _dashboard_rub_to_micros(float(cost_rub)),
        }
        out["ctr"] = (
            100.0 * v
            if (v := _dashboard_safe_div(float(out["clicks"]), float(out["impressions"]))) is not None
            else None
        )
        out["cpc"] = _dashboard_safe_div(float(out["cost_rub"]), float(out["clicks"]))
        out["cpm"] = (
            1000.0 * v
            if (v := _dashboard_safe_div(float(out["cost_rub"]), float(out["impressions"]))) is not None
            else None
        )
        return out

    direct_campaign_summaries: dict[str, Any] = {}
    for cid, meta in direct_campaign_data.items():
        if not isinstance(meta, dict):
            continue
        cur = _campaign_totals(str(cid), current_from_s, current_to_s)
        prev = _campaign_totals(str(cid), prev_from_s, prev_to_s)
        change = {
            "impressions_pct": _pct_change(cur.get("impressions"), prev.get("impressions")),
            "clicks_pct": _pct_change(cur.get("clicks"), prev.get("clicks")),
            "cost_pct": _pct_change(cur.get("cost_rub"), prev.get("cost_rub")),
            "ctr_pp": (
                (float(cur["ctr"]) - float(prev["ctr"]))
                if cur.get("ctr") is not None and prev.get("ctr") is not None
                else None
            ),
            "cpc_pct": _pct_change(cur.get("cpc"), prev.get("cpc")),
        }
        direct_campaign_summaries[str(cid)] = {
            "name": meta.get("name"),
            "shortName": meta.get("shortName"),
            "subName": meta.get("subName"),
            "type": meta.get("type"),
            "current": cur,
            "prev": prev,
            "change": change,
        }

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
            counter_id_s = str(counter_id).strip()
            accounts_for_counter: list[str] = []
            try:
                accounts = _refresh_accounts_registry(ctx)
                for aid, acc in (accounts or {}).items():
                    if not isinstance(acc, dict):
                        continue
                    ids = acc.get("metrica_counter_ids")
                    if not isinstance(ids, list):
                        continue
                    if counter_id_s in {str(x).strip() for x in ids if str(x).strip()}:
                        accounts_for_counter.append(str(aid))
            except Exception:
                accounts_for_counter = []
            is_shared_counter = len(set(accounts_for_counter)) > 1

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
            direct_campaign_ids_allowlist: set[str] | None = None

            # Prefer a safe Direct-only report for the current account by filtering Metrica rows
            # via lastsignDirectClickOrder (Direct campaign id). This prevents cross-account
            # pollution when multiple Direct logins share one Metrica counter.
            fallback_params = dict(base_params)
            fallback_params["dimensions"] = "ym:s:date,ym:s:UTMCampaign,ym:s:lastsignDirectClickOrder"
            try:
                direct_campaign_ids_allowlist = {str(x).strip() for x in (direct_campaign_data or {}).keys() if str(x).strip()}
                metrica_direct_split_report = _metrica_get_stats(ctx, fallback_params)
                used_direct_only = True
                if is_shared_counter:
                    warnings.append(
                        "Option C: shared Metrica counter detected; using lastsignDirectClickOrder allowlist to isolate Direct traffic."
                    )
            except Exception as exc:
                msg = str(exc)
                warnings.append(
                    "Option C: lastsignDirectClickOrder report failed"
                    + (f": {exc.__class__.__name__}" if exc.__class__.__name__ else "")
                    + (f": {msg}" if msg else "")
                )
                # If the counter is not shared, we can still try a Direct-only report via source engine filter.
                if (not is_shared_counter) and picked_engine:
                    params = dict(base_params)
                    params["dimensions"] = "ym:s:date,ym:s:UTMCampaign,ym:s:lastsignSourceEngine"
                    params["filters"] = f"ym:s:lastsignSourceEngine=={_dashboard_metrica_filter_quote(str(picked_engine))}"
                    try:
                        metrica_direct_split_report = _metrica_get_stats(ctx, params)
                        used_direct_only = True
                        direct_campaign_ids_allowlist = None
                    except Exception as exc2:
                        msg2 = str(exc2)
                        warnings.append(
                            "Option C: UTMCampaign engine filter rejected"
                            + (f": {exc2.__class__.__name__}" if exc2.__class__.__name__ else "")
                            + (f": {msg2}" if msg2 else "")
                        )
                        metrica_direct_split_report = _metrica_get_stats(ctx, base_params)
                        used_direct_only = False
                        direct_campaign_ids_allowlist = None
                else:
                    # Shared counter: do not silently fall back to unfiltered counter-wide UTMCampaign report
                    # because it can catastrophically inflate Direct leads/CPL for this account.
                    metrica_direct_split_report = None

            if isinstance(metrica_direct_split_report, dict) and isinstance(metrica_direct_split_report.get("data"), list):
                metrica_direct_split = _dashboard_build_metrica_direct_split_by_utm(
                    all_days=all_days,
                    report=metrica_direct_split_report,
                    campaign_data=direct_campaign_data,
                    goals_mode=goals_mode,
                    goal_ids_user=goal_ids_user,
                    report_is_direct_only=used_direct_only,
                    direct_campaign_ids_allowlist=direct_campaign_ids_allowlist,
                )
                metrica_direct_by_campaign = _dashboard_build_metrica_direct_by_campaign_utm(
                    all_days=all_days,
                    report=metrica_direct_split_report,
                    campaign_data=direct_campaign_data,
                    goals_mode=goals_mode,
                    goal_ids_user=goal_ids_user,
                    report_is_direct_only=used_direct_only,
                    direct_campaign_ids_allowlist=direct_campaign_ids_allowlist,
                )
                if (
                    direct_campaign_ids_allowlist is not None
                    and isinstance(metrica_direct_split, dict)
                    and metrica_direct_split.get("available") is False
                    and metrica_direct_split.get("reason") == "allowlist_no_matches"
                ):
                    warnings.append(
                        "Option C: lastsignDirectClickOrder allowlist matched 0 rows; Direct funnel may be unavailable. "
                        "Check that lastsignDirectClickOrder returns Direct campaign ids for this counter."
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

    wordstat_block = _dashboard_build_wordstat_block(
        ctx,
        args=args,
        campaign_data=direct_campaign_data,
        date_from=date_from_eff_s,
        date_to=date_to_eff_s,
        warnings=warnings,
    )
    audience_block = _dashboard_build_audience_block(ctx, args=args, warnings=warnings)

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
        "direct": {
            "current": direct_current,
            "prev": direct_prev,
            "campaign_data": direct_campaign_data,
            "campaign_summaries": direct_campaign_summaries,
        },
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
    if wordstat_block is not None:
        data["wordstat"] = wordstat_block
    if audience_block is not None:
        data["audience"] = audience_block
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


def _dashboard_generate_pro_html(ctx: AppContext, args: dict[str, Any]) -> dict[str, Any]:
    option1_args = dict(args)
    option1_args["include_html"] = False
    option1_args["output_dir"] = None
    option1_args["return_data"] = True
    if option1_args.get("include_raw_reports") is None:
        option1_args["include_raw_reports"] = False

    base = _dashboard_generate_option1(ctx, option1_args)
    data = ((base.get("result") or {}).get("data")) if isinstance(base, dict) else None
    if not isinstance(data, dict):
        raise RuntimeError("dashboard.generate_pro_html: failed to build base dashboard payload")

    include_html = args.get("include_html")
    output_dir = args.get("output_dir")
    if include_html is None:
        include_html = not bool(output_dir)
    return_data = args.get("return_data")
    if return_data is None:
        return_data = not bool(output_dir)

    if bool((data.get("meta") or {}).get("multi")):
        accounts = data.get("accounts")
        if not isinstance(accounts, dict):
            raise RuntimeError("dashboard.generate_pro_html: multi-account payload is malformed")
        for account_id, per_data in accounts.items():
            if not isinstance(per_data, dict):
                continue
            per_meta = per_data.get("meta") if isinstance(per_data.get("meta"), dict) else {}
            per_args = dict(args)
            per_args.pop("all_accounts", None)
            per_args.pop("account_ids", None)
            per_args["account_id"] = account_id
            if per_meta.get("direct_client_login") is not None:
                per_args["direct_client_login"] = per_meta.get("direct_client_login")
            if per_meta.get("counter_id") is not None:
                per_args["counter_id"] = per_meta.get("counter_id")
            per_data["pro"] = _dashboard_build_pro_account_data(ctx, args=per_args, base_data=per_data)
            if isinstance(per_data.get("meta"), dict):
                per_data["meta"]["tool"] = "dashboard.generate_pro_html"
        if isinstance(data.get("meta"), dict):
            data["meta"]["tool"] = "dashboard.generate_pro_html"
    else:
        data["pro"] = _dashboard_build_pro_account_data(ctx, args=args, base_data=data)
        if isinstance(data.get("meta"), dict):
            data["meta"]["tool"] = "dashboard.generate_pro_html"

    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    date_from_s = str(meta.get("date_from") or "")
    date_to_s = str(meta.get("date_to") or "")
    ident = "multi" if bool(meta.get("multi")) else str(meta.get("account_id") or meta.get("direct_client_login") or "default")
    base_name = f"yandexad_dashboard_pro__{_dashboard_safe_slug(ident)}__{date_from_s}_{date_to_s}"
    if args.get("dashboard_slug"):
        base_name += f"__{_dashboard_safe_slug(str(args.get('dashboard_slug')))}"

    data_json = json.dumps(data, ensure_ascii=False)
    html: str | None = None
    html_path: str | None = None
    json_path: str | None = None

    if include_html or output_dir:
        html = _dashboard_render_html(_dashboard_get_option1_template(), data_json=data_json)

    if output_dir:
        out_dir = Path(str(output_dir)).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        data_path = out_dir / f"{base_name}.json"
        page_path = out_dir / f"{base_name}.html"
        data_path.write_text(data_json, encoding="utf-8")
        if html is not None:
            page_path.write_text(html, encoding="utf-8")
        html_path = str(page_path)
        json_path = str(data_path)

    result: dict[str, Any] = {}
    if return_data:
        result["data"] = data
    else:
        if bool(meta.get("multi")):
            compact_accounts: list[dict[str, Any]] = []
            for account_id, per_data in ((data.get("accounts") or {}) if isinstance(data.get("accounts"), dict) else {}).items():
                if not isinstance(per_data, dict):
                    continue
                compact = _dashboard_build_compact_result(
                    per_data,
                    warnings=(per_data.get("warnings") if isinstance(per_data.get("warnings"), list) else []),
                    coverage=(per_data.get("coverage") if isinstance(per_data.get("coverage"), dict) else {}),
                )
                compact_accounts.append(
                    {
                        "account_id": account_id,
                        "project_name": ((per_data.get("meta") or {}).get("project_name") if isinstance(per_data.get("meta"), dict) else None),
                        "summary": compact.get("summary"),
                        "pro_summary": (((per_data.get("pro") or {}).get("summary")) if isinstance(per_data.get("pro"), dict) else None),
                    }
                )
            result["meta"] = meta
            result["accounts"] = compact_accounts
            result["warnings"] = data.get("warnings") if isinstance(data.get("warnings"), list) else []
        else:
            result.update(
                _dashboard_build_compact_result(
                    data,
                    warnings=(data.get("warnings") if isinstance(data.get("warnings"), list) else []),
                    coverage=(data.get("coverage") if isinstance(data.get("coverage"), dict) else {}),
                )
            )
            if isinstance(data.get("pro"), dict):
                result["pro_summary"] = data["pro"].get("summary")
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


def _wordstat_post(ctx: AppContext, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not getattr(ctx.config, "wordstat_enabled", False):
        raise MissingClientError("wordstat", "Wordstat is disabled (MCP_WORDSTAT_ENABLED=false).")
    folder_id = getattr(ctx.config, "wordstat_search_api_folder_id", None)
    api_key = getattr(ctx.config, "wordstat_search_api_api_key", None)
    iam_token = getattr(ctx.config, "wordstat_search_api_iam_token", None)
    if not folder_id:
        raise MissingClientError("wordstat", "YANDEX_SEARCH_API_FOLDER_ID is not configured.")
    if not (api_key or iam_token):
        raise MissingClientError("wordstat", "YANDEX_SEARCH_API_API_KEY or YANDEX_SEARCH_API_IAM_TOKEN is not configured.")

    cacheable = path in {"getRegionsTree"} and ctx.cache is not None
    cache_key = ""
    if cacheable:
        cache_key = f"wordstat:{path}:{json.dumps(payload or {}, sort_keys=True, ensure_ascii=True)}"
        cached = ctx.cache.get(cache_key)
        if isinstance(cached, dict):
            return cached

    client = WordstatClient(
        folder_id=folder_id,
        api_key=api_key,
        iam_token=iam_token,
        base_url=getattr(ctx.config, "wordstat_api_base_url", None) or WORDSTAT_API_BASE,
    )

    def _call(endpoint_path: str = path) -> dict[str, Any]:
        ctx.wordstat_rate_limiter.acquire()
        return client.post(endpoint_path, payload)

    try:
        data = with_retries(
            _call,
            max_attempts=ctx.config.retry_max_attempts,
            base_delay_seconds=ctx.config.retry_base_delay_seconds,
            max_delay_seconds=ctx.config.retry_max_delay_seconds,
        )
    except WordstatError as exc:
        if path != "regions" or getattr(getattr(exc, "response", None), "status_code", None) != 404:
            raise
        data = with_retries(
            lambda: _call("getRegionsDistribution"),
            max_attempts=ctx.config.retry_max_attempts,
            base_delay_seconds=ctx.config.retry_base_delay_seconds,
            max_delay_seconds=ctx.config.retry_max_delay_seconds,
        )
    if cacheable:
        ctx.cache.set(cache_key, data)
    return data


def _search_serp(ctx: AppContext, args: dict[str, Any]) -> dict[str, Any]:
    if not getattr(ctx.config, "search_api_enabled", True):
        raise MissingClientError("search_api", "Search API tools are disabled (MCP_SEARCH_API_ENABLED=false).")
    folder_id = getattr(ctx.config, "wordstat_search_api_folder_id", None)
    api_key = getattr(ctx.config, "wordstat_search_api_api_key", None)
    iam_token = getattr(ctx.config, "wordstat_search_api_iam_token", None)
    if not folder_id:
        raise MissingClientError("search_api", "YANDEX_SEARCH_API_FOLDER_ID is not configured.")
    if not (api_key or iam_token):
        raise MissingClientError(
            "search_api",
            "YANDEX_SEARCH_API_API_KEY or YANDEX_SEARCH_API_IAM_TOKEN is not configured.",
        )

    payload, meta = build_search_serp_payload(
        args,
        folder_id=folder_id,
        default_region=getattr(ctx.config, "search_api_default_region", 213),
    )
    client = SearchApiClient(
        folder_id=folder_id,
        api_key=api_key,
        iam_token=iam_token,
        base_url=getattr(ctx.config, "search_api_web_base_url", None) or SEARCH_API_WEB_BASE,
    )

    def _call() -> dict[str, Any]:
        ctx.wordstat_rate_limiter.acquire()
        return client.search(payload)

    data = with_retries(
        _call,
        max_attempts=ctx.config.retry_max_attempts,
        base_delay_seconds=ctx.config.retry_base_delay_seconds,
        max_delay_seconds=ctx.config.retry_max_delay_seconds,
    )
    raw = decode_raw_data(data)
    normalized = normalize_search_serp(
        raw,
        response_format="FORMAT_HTML" if meta["format"] == "html" else "FORMAT_XML",
    )
    out = {
        **meta,
        "ads": normalized.get("ads") or [],
        "ads_count_top": int(normalized.get("ads_count_top") or 0),
        "ads_count_bottom": int(normalized.get("ads_count_bottom") or 0),
        "organic": normalized.get("organic") or [],
        "captcha": bool(normalized.get("captcha")),
    }
    for key in ("request_id", "found_docs_human"):
        if normalized.get(key):
            out[key] = normalized[key]
    if args.get("include_raw"):
        out["raw_html" if meta["format"] == "html" else "raw_xml"] = raw
    return out


def _audience_call(
    ctx: AppContext,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not getattr(ctx.config, "audience_enabled", False):
        raise MissingClientError("audience", "Audience is disabled (MCP_AUDIENCE_ENABLED=false).")
    if ctx.audience_tokens is None:
        raise MissingClientError("audience", "Audience client not configured.")
    access_token = ctx.audience_tokens.get_access_token()
    if not access_token:
        raise MissingClientError("audience", "Audience access token not configured.")

    normalized_path = path.strip("/")
    cacheable = method.strip().upper() == "GET" and normalized_path.lower() in {"user/info"} and ctx.cache is not None
    cache_key = ""
    if cacheable:
        cache_key = f"audience:{normalized_path}:{json.dumps(params or {}, sort_keys=True, ensure_ascii=True)}"
        cached = ctx.cache.get(cache_key)
        if isinstance(cached, dict):
            return cached

    client = AudienceClient(access_token=access_token)

    def _call() -> dict[str, Any]:
        ctx.audience_rate_limiter.acquire()
        m = method.strip().upper()
        if m == "GET":
            return client.get(normalized_path, params=params)
        if m == "POST":
            return client.post(normalized_path, payload, params=params)
        if m == "PUT":
            return client.put(normalized_path, payload, params=params)
        if m == "DELETE":
            return client.delete(normalized_path, params=params)
        raise ValueError("Audience method must be GET|POST|PUT|DELETE")

    data = with_retries(
        _call,
        max_attempts=ctx.config.retry_max_attempts,
        base_delay_seconds=ctx.config.retry_base_delay_seconds,
        max_delay_seconds=ctx.config.retry_max_delay_seconds,
    )
    if cacheable:
        ctx.cache.set(cache_key, data)
    return data


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


def _build_clients_params(args: dict[str, Any], *, default_fields: list[str]) -> dict[str, Any]:
    """Build params for Direct `clients` service.

    The Direct `clients` endpoint does **not** accept `SelectionCriteria` (even empty),
    so we must not send it by default.
    """
    if args.get("params"):
        return args["params"]

    selection = args.get("selection_criteria")
    if selection not in (None, {}, []):
        raise ValueError("selection_criteria is not supported for direct.list_clients (use params override)")

    params: dict[str, Any] = {
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
        params["ReportName"] = make_unique_report_name(f"MCP_{report_type}{suffix}")
    if args.get("report_type") is not None:
        params["ReportType"] = args.get("report_type")

    report_type_value = str(params.get("ReportType") or "").strip().upper()
    field_names = params.get("FieldNames")
    if report_type_value == "CUSTOM_REPORT" and isinstance(field_names, list):
        normalized_fields = {str(field).strip() for field in field_names if str(field).strip()}
        if "Keyword" in normalized_fields:
            raise ValueError(
                "FieldNames.Keyword is not valid for CUSTOM_REPORT. "
                "Use Criterion instead (and optionally CriterionId, CriterionType)."
            )

    # Safe defaults: reduce UX friction for common report calls.
    # Direct report API expects these parameters even when they are "obvious".
    date_range_type = args.get("date_range_type")
    if date_range_type is None and isinstance(params.get("SelectionCriteria"), dict):
        selection = params.get("SelectionCriteria") or {}
        if selection.get("DateFrom") or selection.get("DateTo"):
            date_range_type = "CUSTOM_DATE"
    if date_range_type is not None:
        params["DateRangeType"] = date_range_type

    fmt = args.get("format") or "TSV"
    params["Format"] = fmt

    include_vat = args.get("include_vat") or "YES"
    params["IncludeVAT"] = include_vat

    include_discount = args.get("include_discount") or "NO"
    params["IncludeDiscount"] = include_discount

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


def _wordstat_int_list(value: Any) -> list[int] | None:
    if value is None:
        return None
    if isinstance(value, list):
        out: list[int] = []
        for item in value:
            try:
                out.append(int(item))
            except Exception:
                continue
        return out or None
    try:
        return [int(value)]
    except Exception:
        return None


def _wordstat_str_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        out = [str(x).strip() for x in value if str(x).strip()]
        return out or None
    s = str(value).strip()
    return [s] if s else None


def _wordstat_normalize_period(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    aliases = {
        "MONTH": "PERIOD_MONTHLY",
        "MONTHLY": "PERIOD_MONTHLY",
        "PERIOD_MONTHLY": "PERIOD_MONTHLY",
        "WEEK": "PERIOD_WEEKLY",
        "WEEKLY": "PERIOD_WEEKLY",
        "PERIOD_WEEKLY": "PERIOD_WEEKLY",
        "DAY": "PERIOD_DAILY",
        "DAILY": "PERIOD_DAILY",
        "PERIOD_DAILY": "PERIOD_DAILY",
    }
    return aliases.get(normalized, normalized)


def _wordstat_normalize_region_type(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    aliases = {
        "ALL": "REGION_ALL",
        "REGION_ALL": "REGION_ALL",
        "CITIES": "REGION_CITIES",
        "CITY": "REGION_CITIES",
        "REGION_CITIES": "REGION_CITIES",
        "REGIONS": "REGION_REGIONS",
        "REGION": "REGION_REGIONS",
        "REGION_REGIONS": "REGION_REGIONS",
    }
    out = aliases.get(normalized)
    if not out:
        raise ValueError("region_type must be one of all, cities, regions, REGION_ALL, REGION_CITIES, REGION_REGIONS")
    return out


def _wordstat_ymd(value: str) -> date | None:
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return None
    try:
        return date(int(value[:4]), int(value[5:7]), int(value[8:10]))
    except Exception:
        return None


def _wordstat_month_last_day(day: date) -> date:
    if day.month == 12:
        return date(day.year + 1, 1, 1) - timedelta(days=1)
    return date(day.year, day.month + 1, 1) - timedelta(days=1)


def _wordstat_date_time(value: Any, *, end: bool = False) -> str:
    s = str(value or "").strip()
    if not s:
        return s
    if "T" in s:
        return s
    if len(s) == 7 and s[4] == "-":
        if end:
            year = int(s[:4])
            month = int(s[5:7])
            if month == 12:
                next_month = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                next_month = datetime(year, month + 1, 1, tzinfo=timezone.utc)
            return (next_month - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return f"{s}-01T00:00:00Z"
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        if end:
            return f"{s}T23:59:59Z"
        return f"{s}T00:00:00Z"
    return s


def _wordstat_dynamics_to_date(value: Any, *, period: str | None) -> str:
    s = str(value or "").strip()
    if not s:
        return s
    normalized_period = _wordstat_normalize_period(period) if period else ""
    if len(s) == 7 and s[4] == "-":
        if normalized_period and normalized_period != "PERIOD_MONTHLY":
            raise ValueError("YYYY-MM to_date is only supported for monthly Wordstat dynamics.")
        return _wordstat_date_time(s, end=True)
    day = _wordstat_ymd(s)
    if normalized_period == "PERIOD_MONTHLY" and day is not None and day != _wordstat_month_last_day(day):
        raise ValueError("Monthly Wordstat dynamics to_date must be YYYY-MM or the last day of the month.")
    if normalized_period == "PERIOD_WEEKLY" and day is not None:
        raise ValueError(
            "Weekly Wordstat dynamics to_date must use the provider's week-end boundary. "
            "Because the boundary is provider-specific, pass raw params with a confirmed toDate or use daily/monthly."
        )
    return _wordstat_date_time(s, end=True)


def _build_wordstat_top_requests_payload(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("params"):
        return args["params"]

    phrase = args.get("phrase")
    phrases = args.get("phrases")
    payload: dict[str, Any] = {}

    if phrase is not None and str(phrase).strip():
        payload["phrase"] = str(phrase).strip()
    if phrases is not None:
        resolved = _wordstat_str_list(phrases)
        if not resolved:
            raise ValueError("phrases must be a non-empty array when provided")
        if len(resolved) > 128:
            raise ValueError("phrases must contain at most 128 items")
        payload["phrases"] = resolved

    if "phrase" in payload and "phrases" in payload:
        raise ValueError("Provide exactly one of phrase or phrases")
    if "phrase" not in payload and "phrases" not in payload:
        raise ValueError("phrase or phrases is required")

    regions = _wordstat_int_list(args.get("regions"))
    if regions:
        payload["regions"] = regions
    devices = _wordstat_str_list(args.get("devices"))
    if devices:
        payload["devices"] = devices

    num_phrases = args.get("num_phrases")
    if num_phrases is not None:
        n = int(num_phrases)
        if n <= 0 or n > 2000:
            raise ValueError("num_phrases must be between 1 and 2000")
        payload["numPhrases"] = n

    return payload


def _build_wordstat_dynamics_payload(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("params"):
        return args["params"]

    phrase = str(args.get("phrase") or "").strip()
    if not phrase:
        raise ValueError("phrase is required")
    from_date = _wordstat_date_time(args.get("from_date"))
    if not from_date:
        raise ValueError("from_date is required")

    payload: dict[str, Any] = {"phrase": phrase, "fromDate": from_date}

    period = args.get("period")
    normalized_period = ""
    if period is not None and str(period).strip():
        normalized_period = _wordstat_normalize_period(period)
        if normalized_period not in {"PERIOD_MONTHLY", "PERIOD_WEEKLY", "PERIOD_DAILY"}:
            raise ValueError("period must be monthly, weekly, daily, PERIOD_MONTHLY, PERIOD_WEEKLY, or PERIOD_DAILY")
        payload["period"] = str(period).strip()

    to_date = args.get("to_date")
    if to_date is not None and str(to_date).strip():
        payload["toDate"] = _wordstat_dynamics_to_date(to_date, period=normalized_period)

    regions = _wordstat_int_list(args.get("regions"))
    if regions:
        payload["regions"] = regions
    devices = _wordstat_str_list(args.get("devices"))
    if devices:
        payload["devices"] = devices

    return payload


def _build_wordstat_regions_payload(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("params"):
        return args["params"]

    phrase = str(args.get("phrase") or "").strip()
    if not phrase:
        raise ValueError("phrase is required")

    payload: dict[str, Any] = {"phrase": phrase}
    region_type = args.get("region_type")
    if region_type is not None and str(region_type).strip():
        payload["region"] = _wordstat_normalize_region_type(region_type)
    devices = _wordstat_str_list(args.get("devices"))
    if devices:
        payload["devices"] = devices
    return payload


def _wordstat_top_requests_with_fallback(ctx: AppContext, payload: dict[str, Any]) -> dict[str, Any]:
    phrases = payload.get("phrases")
    if not isinstance(phrases, list) or len(phrases) <= 1:
        if isinstance(phrases, list) and len(phrases) == 1:
            payload = dict(payload)
            payload.pop("phrases", None)
            payload["phrase"] = str(phrases[0])
        return _wordstat_post(ctx, "topRequests", payload)

    per_phrase: list[dict[str, Any]] = []
    for phrase in phrases:
        single_payload = dict(payload)
        single_payload.pop("phrases", None)
        single_payload["phrase"] = str(phrase)
        resp = _wordstat_post(ctx, "topRequests", single_payload)
        per_phrase.append({"phrase": str(phrase), "topRequests": resp.get("results", []), "raw": resp})
    return {
        "topRequestsByPhrase": per_phrase,
        "fallback": {
            "mode": "single_phrase_loop",
            "reason": "Yandex Search API Wordstat accepts one phrase per topRequests call.",
            "requested_phrases": [str(phrase) for phrase in phrases],
        },
    }


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

    audience_tokens: TokenManager | None = None
    if getattr(config, "audience_enabled", False):
        audience_tokens = TokenManager(
            config,
            access_token=config.audience_access_token,
            refresh_token=config.audience_refresh_token,
            client_id=config.audience_client_id,
            client_secret=config.audience_client_secret,
            provider="audience",
        )

    cache: TTLCache | None = None
    if config.cache_enabled and config.cache_ttl_seconds > 0:
        cache = TTLCache(config.cache_ttl_seconds)

    yield AppContext(
        config=config,
        tokens=tokens,
        audience_tokens=audience_tokens,
        wordstat_tokens=None,
        clients=clients,
        cache=cache,
        direct_rate_limiter=RateLimiter(config.direct_rate_limit_rps),
        metrica_rate_limiter=RateLimiter(config.metrica_rate_limit_rps),
        audience_rate_limiter=RateLimiter(getattr(config, "audience_rate_limit_rps", 0)),
        wordstat_rate_limiter=RateLimiter(getattr(config, "wordstat_rate_limit_rps", 0)),
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

    if name.startswith("auth."):
        try:
            if getattr(ctx.config, "public_readonly", False):
                raise WriteGuardError(
                    "public",
                    "Auth tools are disabled in public read-only mode.",
                    "Use the pro edition.",
                )
            if not getattr(ctx.config, "auth_tools_enabled", False):
                raise WriteGuardError(
                    "auth",
                    "Auth tools are disabled.",
                    "Set MCP_AUTH_TOOLS_ENABLED=true to enable auth.* tools.",
                )

            from .oauth import build_authorize_url, exchange_code_for_tokens

            def _purpose(p: Any) -> str:
                value = str(p or "direct_metrica").strip().lower()
                if value in {"direct", "direct_metrica", "direct+metrica", "main"}:
                    return "direct_metrica"
                if value in {"audience"}:
                    return "audience"
                if value in {"wordstat"}:
                    raise ValueError(
                        "Wordstat credentials are not managed by auth.*; configure "
                        "YANDEX_SEARCH_API_FOLDER_ID and YANDEX_SEARCH_API_API_KEY "
                        "or YANDEX_SEARCH_API_IAM_TOKEN."
                    )
                raise ValueError("purpose must be one of: direct_metrica | audience")

            def _env_for(purpose: str) -> dict[str, str]:
                if purpose == "audience":
                    return {
                        "client_id": "YANDEX_AUDIENCE_CLIENT_ID",
                        "client_secret": "YANDEX_AUDIENCE_CLIENT_SECRET",
                        "access_token": "YANDEX_AUDIENCE_ACCESS_TOKEN",
                        "refresh_token": "YANDEX_AUDIENCE_REFRESH_TOKEN",
                        "redirect_uri": "YANDEX_AUDIENCE_REDIRECT_URI",
                        "scopes": "YANDEX_AUDIENCE_SCOPES",
                    }
                return {
                    "client_id": "YANDEX_CLIENT_ID",
                    "client_secret": "YANDEX_CLIENT_SECRET",
                    "access_token": "YANDEX_ACCESS_TOKEN",
                    "refresh_token": "YANDEX_REFRESH_TOKEN",
                    "redirect_uri": "YANDEX_REDIRECT_URI",
                    "scopes": "YANDEX_SCOPES",
                }

            if name == "auth.start":
                purpose = _purpose(args.get("purpose"))
                env = _env_for(purpose)
                client_id = str(args.get("client_id") or os.getenv(env["client_id"]) or "").strip()
                if not client_id:
                    raise ValueError(f"{env['client_id']} is required (or pass client_id).")

                redirect_uri = str(
                    args.get("redirect_uri")
                    or os.getenv(env["redirect_uri"])
                    or os.getenv("YANDEX_REDIRECT_URI")
                    or "https://oauth.yandex.ru/verification_code"
                ).strip()

                scopes_arg = args.get("scopes")
                scopes_env = os.getenv(env["scopes"]) or os.getenv("YANDEX_SCOPES") or ""
                scopes_list: list[str]
                if isinstance(scopes_arg, list):
                    scopes_list = [str(s).strip() for s in scopes_arg if str(s).strip()]
                else:
                    scopes_list = [s.strip() for s in scopes_env.split(" ") if s.strip()]

                state = secrets.token_urlsafe(24)
                authorize_url = build_authorize_url(
                    client_id=client_id,
                    redirect_uri=redirect_uri,
                    scopes=scopes_list or None,
                    state=state,
                )
                return _ok_result(
                    ctx,
                    name,
                    {
                        "status": "ok",
                        "result": {
                            "purpose": purpose,
                            "authorize_url": authorize_url,
                            "state": state,
                            "redirect_uri": redirect_uri,
                            "scopes": scopes_list,
                            "env_keys": env,
                        },
                    },
                )

            if name == "auth.exchange_code":
                purpose = _purpose(args.get("purpose"))
                env = _env_for(purpose)
                code = str(args.get("code") or "").strip()
                if not code:
                    raise ValueError("code is required")

                client_id = str(args.get("client_id") or os.getenv(env["client_id"]) or "").strip()
                client_secret = str(args.get("client_secret") or os.getenv(env["client_secret"]) or "").strip()
                if not client_id:
                    raise ValueError(f"{env['client_id']} is required (or pass client_id).")
                if not client_secret:
                    raise ValueError(f"{env['client_secret']} is required (or pass client_secret).")

                redirect_uri = str(
                    args.get("redirect_uri")
                    or os.getenv(env["redirect_uri"])
                    or os.getenv("YANDEX_REDIRECT_URI")
                    or "https://oauth.yandex.ru/verification_code"
                ).strip()

                tokens = exchange_code_for_tokens(
                    code=code,
                    client_id=client_id,
                    client_secret=client_secret,
                    redirect_uri=redirect_uri,
                )
                refresh = tokens.refresh_token or ""
                env_block = "\n".join(
                    [
                        "# OAuth",
                        f"{env['client_id']}={client_id}",
                        f"{env['client_secret']}={client_secret}",
                        f"{env['access_token']}={tokens.access_token}",
                        f"{env['refresh_token']}={refresh}",
                        f"{env['redirect_uri']}={redirect_uri}",
                    ]
                )
                warnings: list[str] = []
                if not tokens.access_token:
                    warnings.append("access_token is empty")
                if not tokens.refresh_token:
                    warnings.append("refresh_token is empty (may be expected depending on OAuth app settings)")
                return _ok_result(
                    ctx,
                    name,
                    {
                        "status": "ok",
                        "result": {
                            "purpose": purpose,
                            "tokens": {
                                "access_token": tokens.access_token,
                                "refresh_token": tokens.refresh_token,
                                "expires_in": tokens.expires_in,
                                "token_type": tokens.token_type,
                            },
                            "env_block": env_block,
                            "warnings": warnings,
                        },
                    },
                )

            raise ValueError(f"Unknown auth tool: {name}")
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "write.confirm":
        try:
            if getattr(ctx.config, "public_readonly", False):
                raise WriteGuardError(
                    "public",
                    "Two-phase write confirm is disabled in public read-only mode.",
                    "Use the pro edition.",
                )
            if not getattr(ctx.config, "two_phase_writes_enabled", False):
                raise WriteGuardError(
                    "pro",
                    "Two-phase writes are disabled.",
                    "Set MCP_TWO_PHASE_WRITES=true to enable write.confirm.",
                )
            confirm_token = str(args.get("confirm_token") or "").strip()
            if not confirm_token:
                raise ValueError("confirm_token is required")

            action = _pending_write_pop(ctx, confirm_token=confirm_token)
            if action is None:
                raise ValueError("Unknown or expired confirm_token")

            token = _TWO_PHASE_BYPASS.set(True)
            try:
                out = await call_tool(action.tool, action.args)
            finally:
                _TWO_PHASE_BYPASS.reset(token)

            structured: Any = None
            if isinstance(out, tuple) and len(out) == 2:
                structured = out[1]
            payload = {
                "status": "ok",
                "result": {
                    "executed_tool": action.tool,
                    "executed_args_keys": sorted([str(k) for k in (action.args or {}).keys()]),
                    "output": structured if structured is not None else {"raw": out},
                },
            }
            return _ok_result(ctx, name, payload)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    allowed_tools = {t.name for t in tool_definitions(ctx.config)}
    if name not in allowed_tools:
        hint = "Call tools/list to see the available tools for this build."
        if name.startswith(("dashboard.schema", "dashboard.dataset.", "dashboard.sync.")):
            hint = "This tool is provided by the PRO BI plugin. Install the plugin and restart the server."
        elif getattr(ctx.config, "public_readonly", False):
            hint = "This tool is not part of the public read-only surface. Use the pro edition."
        return _error_response(name, ToolNotAvailableError(name, "Tool is not available.", hint))

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
            if name in {"accounts.upsert", "accounts.delete"} and getattr(ctx.config, "public_readonly", False):
                raise WriteGuardError(
                    "public",
                    "Accounts registry write operations are disabled in public read-only mode.",
                    "Use the pro edition or run without MCP_PUBLIC_READONLY=true.",
                )
            if name in {"accounts.upsert", "accounts.delete"} and not ctx.config.accounts_write_enabled:
                raise WriteGuardError(
                    "accounts",
                    "Accounts registry write operations are disabled.",
                    "Set MCP_ACCOUNTS_WRITE_ENABLED=true to allow accounts.* write operations.",
                )
            if name == "accounts.upsert":
                if (
                    getattr(ctx.config, "two_phase_writes_enabled", False)
                    and not _TWO_PHASE_BYPASS.get()
                ):
                    token, ttl = _pending_write_put(ctx, tool=name, args=args)
                    planned = _two_phase_planned_payload(name, confirm_token=token, args=args, ttl_seconds=ttl)
                    return _ok_result(ctx, name, planned)
                result = upsert_account(
                    ctx.config.accounts_file,
                    account_id=str(args.get("account_id") or ""),
                    patch=args,
                    replace=bool(args.get("replace") or False),
                )
                _refresh_accounts_registry(ctx, force=True)
                return _ok_result(ctx, name, {"result": result})
            if name == "accounts.delete":
                if (
                    getattr(ctx.config, "two_phase_writes_enabled", False)
                    and not _TWO_PHASE_BYPASS.get()
                ):
                    token, ttl = _pending_write_put(ctx, tool=name, args=args)
                    planned = _two_phase_planned_payload(name, confirm_token=token, args=args, ttl_seconds=ttl)
                    return _ok_result(ctx, name, planned)
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
    if name.startswith("audience."):
        if not getattr(ctx.config, "audience_enabled", False):
            return _error_response(
                name, MissingClientError("audience", "Audience is disabled (MCP_AUDIENCE_ENABLED=false).")
            )
        if ctx.audience_tokens is None or not ctx.audience_tokens.get_access_token():
            return _error_response(name, MissingClientError("audience", "Audience client not configured."))
    if name.startswith("wordstat."):
        if not getattr(ctx.config, "wordstat_enabled", False):
            return _error_response(
                name, MissingClientError("wordstat", "Wordstat is disabled (MCP_WORDSTAT_ENABLED=false).")
            )
        if not getattr(ctx.config, "wordstat_search_api_folder_id", None) or not (
            getattr(ctx.config, "wordstat_search_api_api_key", None)
            or getattr(ctx.config, "wordstat_search_api_iam_token", None)
        ):
            return _error_response(
                name,
                MissingClientError(
                    "wordstat",
                    "Wordstat Search API credentials are not configured. Set YANDEX_SEARCH_API_FOLDER_ID and YANDEX_SEARCH_API_API_KEY or YANDEX_SEARCH_API_IAM_TOKEN.",
                ),
            )
    if name == "search_serp":
        if not getattr(ctx.config, "search_api_enabled", True):
            return _error_response(
                name, MissingClientError("search_api", "Search API tools are disabled (MCP_SEARCH_API_ENABLED=false).")
            )
        if not getattr(ctx.config, "wordstat_search_api_folder_id", None) or not (
            getattr(ctx.config, "wordstat_search_api_api_key", None)
            or getattr(ctx.config, "wordstat_search_api_iam_token", None)
        ):
            return _error_response(
                name,
                MissingClientError(
                    "search_api",
                    "Search API credentials are not configured. Set YANDEX_SEARCH_API_FOLDER_ID and YANDEX_SEARCH_API_API_KEY or YANDEX_SEARCH_API_IAM_TOKEN.",
                ),
            )

    try:
        args = _resolve_account_overrides(ctx, name, args)
    except Exception as exc:  # pragma: no cover - runtime safety
        return _error_response(name, exc)
    try:
        _enforce_write_guard(ctx.config, name, args)
    except Exception as exc:  # pragma: no cover - runtime safety
        return _error_response(name, exc)

    if (
        getattr(ctx.config, "two_phase_writes_enabled", False)
        and not _TWO_PHASE_BYPASS.get()
        and _is_write_tool(name, args)
    ):
        token, ttl = _pending_write_put(ctx, tool=name, args=args)
        planned = _two_phase_planned_payload(name, confirm_token=token, args=args, ttl_seconds=ttl)
        return _ok_result(ctx, name, planned)

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

    if name.startswith("wordstat.hf."):
        try:
            data = hf_wordstat_handle(name, ctx, args)
            return _ok_result(ctx, name, data)
        except HFError as exc:
            return _text_response(hf_payload(tool=name, status="error", message=str(exc)))
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name.startswith("audience.hf."):
        try:
            data = hf_audience_handle(name, ctx, args)
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

    if name == "dashboard.generate_pro_html":
        try:
            data = _dashboard_generate_pro_html(ctx, args)
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "wordstat.user_info":
        try:
            access_check = _wordstat_post(ctx, "getRegionsTree", args.get("params") or None)
            data = {
                "api": "yandex_search_api_wordstat",
                "baseUrl": getattr(ctx.config, "wordstat_api_base_url", None) or WORDSTAT_API_BASE,
                "folderId": getattr(ctx.config, "wordstat_search_api_folder_id", None),
                "auth": "api_key" if getattr(ctx.config, "wordstat_search_api_api_key", None) else "iam_token",
                "access_check": "getRegionsTree",
                "available": True,
                "raw": access_check,
            }
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "search_serp":
        try:
            data = _search_serp(ctx, args)
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "audience.user_info":
        try:
            data = ctx._audience_call("GET", "/user/info")
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "audience.segments.list":
        try:
            params = {k: v for k, v in (args or {}).items() if k in {"limit", "offset", "types", "statuses", "fields"} and v is not None}
            data = ctx._audience_call("GET", "/segments", params=params)
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "audience.segments.get":
        try:
            seg_id = str(args.get("segment_id") or "")
            if not seg_id:
                raise ValueError("segment_id is required")
            params = {}
            if args.get("fields") is not None:
                params["fields"] = args.get("fields")
            data = ctx._audience_call("GET", f"/segments/{seg_id}", params=params or None)
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "audience.segments.stats":
        try:
            seg_id = str(args.get("segment_id") or "")
            if not seg_id:
                raise ValueError("segment_id is required")
            params = {}
            if args.get("fields") is not None:
                params["fields"] = args.get("fields")
            # Best effort: API may not expose a dedicated stats endpoint; try /stats then fallback to /segments/{id}.
            try:
                data = ctx._audience_call("GET", f"/segments/{seg_id}/stats", params=params or None)
            except Exception:
                data = ctx._audience_call("GET", f"/segments/{seg_id}", params=params or None)
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "audience.segments.overlap":
        try:
            seg_ids = args.get("segment_ids")
            if not isinstance(seg_ids, list) or not seg_ids:
                raise ValueError("segment_ids is required")
            payload = {"segment_ids": [str(x) for x in seg_ids]}
            if args.get("mode") is not None:
                payload["mode"] = str(args.get("mode"))
            if args.get("limit") is not None:
                payload["limit"] = int(args.get("limit"))
            data = ctx._audience_call("POST", "/segments/overlap", payload=payload)
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "audience.pixels.list":
        try:
            params = {k: v for k, v in (args or {}).items() if k in {"limit", "offset", "fields"} and v is not None}
            data = ctx._audience_call("GET", "/pixels", params=params or None)
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "audience.pixels.get":
        try:
            pixel_id = str(args.get("pixel_id") or "")
            if not pixel_id:
                raise ValueError("pixel_id is required")
            params = {}
            if args.get("fields") is not None:
                params["fields"] = args.get("fields")
            data = ctx._audience_call("GET", f"/pixels/{pixel_id}", params=params or None)
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "audience.lookalikes.list":
        try:
            params = {k: v for k, v in (args or {}).items() if k in {"limit", "offset", "fields"} and v is not None}
            data = ctx._audience_call("GET", "/lookalikes", params=params or None)
            return _ok_result(ctx, name, data)
        except Exception as exc:
            if getattr(exc, "response", None) is not None and getattr(getattr(exc, "response", None), "status_code", None) == 404:
                return _error_response(
                    name,
                    NotSupportedError(
                        "audience",
                        "Audience lookalikes endpoints are not available (HTTP 404).",
                        hint="Use audience.segments.* tools instead, or remove lookalikes tools from the surface.",
                    ),
                )
            return _error_response(name, exc)

    if name == "audience.lookalikes.get":
        try:
            look_id = str(args.get("id") or "")
            if not look_id:
                raise ValueError("id is required")
            params = {}
            if args.get("fields") is not None:
                params["fields"] = args.get("fields")
            data = ctx._audience_call("GET", f"/lookalikes/{look_id}", params=params or None)
            return _ok_result(ctx, name, data)
        except Exception as exc:
            if getattr(exc, "response", None) is not None and getattr(getattr(exc, "response", None), "status_code", None) == 404:
                return _error_response(
                    name,
                    NotSupportedError(
                        "audience",
                        "Audience lookalikes endpoints are not available (HTTP 404).",
                        hint="Use audience.segments.* tools instead, or remove lookalikes tools from the surface.",
                    ),
                )
            return _error_response(name, exc)

    if name == "audience.segments.create":
        try:
            data = ctx._audience_call("POST", "/segments", payload=args.get("payload") or {})
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "audience.segments.update":
        try:
            seg_id = str(args.get("segment_id") or "")
            if not seg_id:
                raise ValueError("segment_id is required")
            data = ctx._audience_call("PUT", f"/segments/{seg_id}", payload=args.get("payload") or {})
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "audience.segments.delete":
        try:
            seg_id = str(args.get("segment_id") or "")
            if not seg_id:
                raise ValueError("segment_id is required")
            data = ctx._audience_call("DELETE", f"/segments/{seg_id}")
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "audience.upload.start":
        try:
            seg_id = str(args.get("segment_id") or "")
            if not seg_id:
                raise ValueError("segment_id is required")
            data = ctx._audience_call("POST", f"/segments/{seg_id}/upload", payload=args.get("payload") or {})
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "audience.upload.status":
        try:
            upload_id = str(args.get("upload_id") or "")
            if not upload_id:
                raise ValueError("upload_id is required")
            data = ctx._audience_call("GET", f"/uploads/{upload_id}")
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "audience.upload.errors":
        try:
            upload_id = str(args.get("upload_id") or "")
            if not upload_id:
                raise ValueError("upload_id is required")
            data = ctx._audience_call("GET", f"/uploads/{upload_id}/errors")
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "audience.raw_call":
        try:
            method = str(args.get("method") or "GET")
            path = str(args.get("path") or "")
            if not path:
                raise ValueError("path is required")
            data = ctx._audience_call(method, path, params=args.get("params") or None, payload=args.get("payload") or None)
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "wordstat.get_regions_tree":
        try:
            data = _wordstat_post(ctx, "getRegionsTree", args.get("params") or None)
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "wordstat.top_requests":
        try:
            payload = _build_wordstat_top_requests_payload(args)
            data = _wordstat_top_requests_with_fallback(ctx, payload)
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "wordstat.dynamics":
        try:
            payload = _build_wordstat_dynamics_payload(args)
            data = _wordstat_post(ctx, "dynamics", payload)
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "wordstat.regions":
        try:
            payload = _build_wordstat_regions_payload(args)
            data = _wordstat_post(ctx, "regions", payload)
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover - runtime safety
            return _error_response(name, exc)

    if name == "direct.list_campaigns":
        try:
            params = _build_campaigns_params(args)
            data = _direct_get(ctx, "campaigns", params, direct_client_login=args.get("direct_client_login"))
            selection = params.get("SelectionCriteria") or {}
            campaign_ids = selection.get("Ids") if isinstance(selection, dict) else None
            campaigns = ((data.get("result") or {}).get("Campaigns")) if isinstance(data, dict) else None
            if isinstance(campaign_ids, list) and campaign_ids and isinstance(campaigns, list) and not campaigns:
                scoped = _RequestScopedContext(ctx, args.get("direct_client_login"))
                special_candidates: list[dict[str, Any]] = []
                for campaign_id in campaign_ids[:20]:
                    try:
                        special = detect_special_campaign(scoped, campaign_id=int(campaign_id), counts={"adgroups": 0, "ads": 0, "keywords": 0})
                    except Exception:
                        continue
                    if special is None:
                        continue
                    special_candidates.append(
                        {
                            "Id": int(campaign_id),
                            "CampaignType": special["campaign_type"],
                            "CountsApplicable": special["counts_applicable"],
                            "PerformanceSignal": special["performance_signal"],
                            "Note": special["note"],
                        }
                    )
                if special_candidates:
                    data = dict(data)
                    result = dict(data.get("result") or {})
                    result["Campaigns"] = special_candidates
                    warnings = list(result.get("Warnings") or [])
                    warnings.append(
                        "campaigns.get returned no rows; substituted special campaign candidates based on live performance and zero structure counts."
                    )
                    result["Warnings"] = warnings
                    data["result"] = result
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
            params = _build_clients_params(args, default_fields=["ClientId", "Login"])
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

    if name == "metrica.goals.list":
        try:
            counter_id = str(args.get("counter_id") or "").strip()
            if not counter_id:
                raise ValueError("counter_id is required")
            params = args.get("params") or None
            data = _metrica_management_call(
                ctx,
                resource="goals",
                method="get",
                params=params,
                data=None,
                path_args={"counterId": counter_id},
            )
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "metrica.goals.get":
        try:
            counter_id = str(args.get("counter_id") or "").strip()
            goal_id = str(args.get("goal_id") or "").strip()
            if not counter_id:
                raise ValueError("counter_id is required")
            if not goal_id:
                raise ValueError("goal_id is required")
            params = args.get("params") or None
            data = _metrica_management_call(
                ctx,
                resource="goal",
                method="get",
                params=params,
                data=None,
                path_args={"counterId": counter_id, "goalId": goal_id},
            )
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "metrica.goals.create":
        try:
            counter_id = str(args.get("counter_id") or "").strip()
            if not counter_id:
                raise ValueError("counter_id is required")
            payload = args.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            data = _metrica_management_call(
                ctx,
                resource="goals",
                method="post",
                params=None,
                data=payload,
                path_args={"counterId": counter_id},
            )
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "metrica.goals.update":
        try:
            counter_id = str(args.get("counter_id") or "").strip()
            goal_id = str(args.get("goal_id") or "").strip()
            if not counter_id:
                raise ValueError("counter_id is required")
            if not goal_id:
                raise ValueError("goal_id is required")
            payload = args.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            data = _metrica_management_call(
                ctx,
                resource="goal",
                method="put",
                params=None,
                data=payload,
                path_args={"counterId": counter_id, "goalId": goal_id},
            )
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
            return _error_response(name, exc)

    if name == "metrica.goals.delete":
        try:
            counter_id = str(args.get("counter_id") or "").strip()
            goal_id = str(args.get("goal_id") or "").strip()
            if not counter_id:
                raise ValueError("counter_id is required")
            if not goal_id:
                raise ValueError("goal_id is required")
            data = _metrica_management_call(
                ctx,
                resource="goal",
                method="delete",
                params=None,
                data=None,
                path_args={"counterId": counter_id, "goalId": goal_id},
            )
            return _ok_result(ctx, name, data)
        except Exception as exc:  # pragma: no cover
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

    try:
        plugin_payload = plugins_try_handle(ctx, name, args)
        if plugin_payload is not None:
            return _ok_result(ctx, name, plugin_payload)
    except Exception as exc:  # pragma: no cover - defensive
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
