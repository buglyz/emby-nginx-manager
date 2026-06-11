#!/usr/bin/env python3
import argparse
import io
import ipaddress
import json
import os
import re
import secrets
import signal
import shutil
import string
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
ACCESS_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{8,128}$")
DOMAIN_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
DNS_PROVIDER_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")
URL_PATH_FORBIDDEN_RE = re.compile(r"[\s;{}\"'\\]")
CONFIG_PATH_FORBIDDEN_RE = re.compile(r"[\s;{}\"'\\]")
BACKUP_NAME_RE = re.compile(r"^emby-nginx-manager-(?:[0-9]{14}|[0-9]{26})\.tar\.gz$")
CERT_BACKUP_ARC_RE = re.compile(
    r"^etc/nginx/(?:certs/[^/]+/(?:cert|key)|ssl/[^/]+/(?:fullchain\.pem|privkey\.pem))$"
)
MAX_BODY_BYTES = 64 * 1024
RESTORE_MAX_MEMBER_BYTES = 1024 * 1024
RESTORE_MAX_TOTAL_BYTES = 8 * 1024 * 1024
HISTORY_LIMIT = 200
HISTORY_OUTPUT_TAIL = 4000
COOKIE_NAME = "emby_webui_access"
DEFAULT_STATE_DIR = Path(os.environ.get("EMBY_WEBUI_STATE_DIR", "/var/lib/emby-nginx-manager"))
DEFAULT_BACKUP_DIR = Path(os.environ.get("EMBY_WEBUI_BACKUP_DIR", "/var/backups/emby-nginx-manager"))
DEFAULT_NGINX_CONF_DIR = Path("/etc/nginx/conf.d")
MANAGED_CONFIG_MARKERS = (
    "nre_emby_managed=true",
    "managed_by=nginx-reverse-emby-deploy",
    "nre_webui_managed=true",
    "managed_by=emby-nginx-manager-webui",
)
WEBUI_SERVICE_MARKERS = (
    "Description=Emby Nginx Manager WebUI",
    "Environment=EMBY_WEBUI_SHOW_KEY_URL=0",
    "NoNewPrivileges=true",
    "PrivateTmp=true",
)
RESTORE_SKIP_ARCNAMES = {
    "etc/emby-nginx-webui.env",
    "etc/nginx/snippets/emby-webui-internal-key.conf",
}


def env_int(name, default, minimum=None):
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    if minimum is not None and value < minimum:
        return default
    return value


DEFAULT_BACKUP_KEEP = env_int("EMBY_WEBUI_BACKUP_KEEP", 20, minimum=1)


HTML = r"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>Emby Nginx Manager</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='7' fill='%230f766e'/><polygon points='12,9 24,16 12,23' fill='white'/></svg>">
  <script>
    (function () {
      try {
        var saved = localStorage.getItem('emby-webui-theme');
        var prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        var theme = saved || (prefersDark ? 'dark' : 'light');
        document.documentElement.setAttribute('data-theme', theme);
      } catch (e) {}
    })();
  </script>
  <style>
    :root {
      color-scheme: light;
      --bg: #eef1f5;
      --bg-grad: radial-gradient(1200px 600px at 100% -10%, rgba(15, 118, 110, .10), transparent 60%), radial-gradient(900px 500px at -10% 0%, rgba(37, 99, 235, .08), transparent 55%);
      --surface: #ffffff;
      --surface-soft: #f7fafc;
      --surface-strong: #eef2f6;
      --line: #dce3ea;
      --line-strong: #c4cfd9;
      --text: #131a22;
      --muted: #64748b;
      --primary: #0f766e;
      --primary-hover: #0b5f59;
      --accent: #2563eb;
      --danger: #c0392b;
      --danger-hover: #9b2c1f;
      --warn: #a16207;
      --ok: #0f7a5a;
      --code-bg: #0f1726;
      --code-text: #e6eef7;
      --code-line: #1d2940;
      --ring: rgba(15, 118, 110, .18);
      --shadow-sm: 0 1px 2px rgba(16, 24, 40, .05);
      --shadow: 0 1px 2px rgba(16, 24, 40, .05), 0 12px 30px rgba(16, 24, 40, .08);
      --shadow-pop: 0 12px 34px rgba(16, 24, 40, .16);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }

    :root[data-theme="dark"] {
      color-scheme: dark;
      --bg: #0b1118;
      --bg-grad: radial-gradient(1200px 600px at 100% -10%, rgba(13, 148, 136, .16), transparent 60%), radial-gradient(900px 500px at -10% 0%, rgba(37, 99, 235, .14), transparent 55%);
      --surface: #131b25;
      --surface-soft: #172230;
      --surface-strong: #1d2a3a;
      --line: #25323f;
      --line-strong: #34465a;
      --text: #e7eef6;
      --muted: #93a3b5;
      --primary: #2dd4bf;
      --primary-hover: #5eead4;
      --accent: #60a5fa;
      --danger: #f87171;
      --danger-hover: #fca5a5;
      --warn: #fbbf24;
      --ok: #34d399;
      --code-bg: #0a1019;
      --code-text: #dbe7f3;
      --code-line: #1a2434;
      --ring: rgba(45, 212, 191, .26);
      --shadow-sm: 0 1px 2px rgba(0, 0, 0, .4);
      --shadow: 0 1px 2px rgba(0, 0, 0, .4), 0 14px 34px rgba(0, 0, 0, .45);
      --shadow-pop: 0 14px 38px rgba(0, 0, 0, .55);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      background-image: var(--bg-grad);
      background-attachment: fixed;
      color: var(--text);
      font-size: 14px;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
      transition: background-color .25s ease, color .25s ease;
    }

    header {
      min-height: 68px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 14px clamp(16px, 4vw, 42px);
      border-bottom: 1px solid var(--line);
      background: color-mix(in srgb, var(--surface) 86%, transparent);
      backdrop-filter: blur(10px);
      position: sticky;
      top: 0;
      z-index: 20;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }

    .brand-logo {
      width: 34px;
      height: 34px;
      border-radius: 9px;
      flex: 0 0 auto;
      display: grid;
      place-items: center;
      background: linear-gradient(135deg, var(--primary), var(--accent));
      box-shadow: 0 6px 16px var(--ring);
    }

    .brand-logo svg { width: 18px; height: 18px; display: block; }

    h1 {
      margin: 0;
      font-size: 18px;
      font-weight: 760;
      letter-spacing: .2px;
      white-space: nowrap;
    }

    .brand-sub {
      margin: 1px 0 0;
      font-size: 11.5px;
      font-weight: 600;
      color: var(--muted);
      white-space: nowrap;
    }

    .head-right {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    main {
      width: min(1380px, 100%);
      margin: 0 auto;
      padding: 22px clamp(14px, 3vw, 30px) 40px;
      display: grid;
      grid-template-columns: minmax(330px, 410px) minmax(0, 1fr);
      gap: 18px;
      align-items: start;
    }

    section {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 12px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    main > section:first-child {
      position: sticky;
      top: 92px;
    }

    .panel-head {
      min-height: 52px;
      padding: 13px 16px;
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      background: var(--surface-soft);
    }

    .panel-head h2 {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .panel-head h2::before {
      content: "";
      width: 4px;
      height: 15px;
      border-radius: 3px;
      background: var(--primary);
      flex: 0 0 auto;
    }

    h2 {
      margin: 0;
      font-size: 14px;
      font-weight: 740;
      letter-spacing: .2px;
    }

    .panel-body {
      padding: 16px;
    }

    .stack {
      display: grid;
      gap: 14px;
    }

    #remove-form {
      margin-top: 4px;
      padding-top: 16px;
      border-top: 1px dashed var(--line-strong);
    }

    .field {
      display: grid;
      gap: 7px;
    }

    label {
      font-size: 12px;
      color: var(--muted);
      font-weight: 700;
    }

    .hint {
      font-size: 11.5px;
      font-weight: 500;
      color: var(--muted);
      opacity: .85;
    }

    input[type="text"] {
      width: 100%;
      height: 40px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 12px;
      color: var(--text);
      background: var(--surface-soft);
      outline: none;
      font-size: 14px;
      transition: border-color .15s ease, box-shadow .15s ease, background-color .15s ease;
    }

    input[type="text"]::placeholder { color: var(--muted); opacity: .7; }

    input[type="text"]:focus {
      border-color: var(--primary);
      background: var(--surface);
      box-shadow: 0 0 0 3px var(--ring);
    }

    .checks {
      display: grid;
      grid-template-columns: 1fr;
      gap: 6px;
      padding: 2px 0;
    }

    .check {
      display: flex;
      align-items: center;
      gap: 10px;
      min-height: 32px;
      padding: 0 8px;
      border-radius: 8px;
      font-size: 13px;
      color: var(--text);
      cursor: pointer;
      transition: background-color .15s ease;
    }

    .check:hover { background: var(--surface-strong); }

    input[type="checkbox"] {
      width: 17px;
      height: 17px;
      margin: 0;
      accent-color: var(--primary);
      cursor: pointer;
    }

    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 9px;
    }

    button {
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0 14px;
      font-size: 13px;
      font-weight: 720;
      cursor: pointer;
      background: var(--surface-strong);
      color: var(--text);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      transition: transform .12s ease, background-color .15s ease, border-color .15s ease, box-shadow .15s ease, color .15s ease;
    }

    button svg { width: 15px; height: 15px; flex: 0 0 auto; }

    button:hover {
      transform: translateY(-1px);
      border-color: var(--line-strong);
      box-shadow: var(--shadow-sm);
    }

    button:active { transform: translateY(0); }

    button.primary {
      background: var(--primary);
      border-color: var(--primary);
      color: #fff;
    }

    button.primary:hover { background: var(--primary-hover); border-color: var(--primary-hover); }

    button.danger {
      background: var(--danger);
      border-color: var(--danger);
      color: #fff;
    }

    button.danger:hover { background: var(--danger-hover); border-color: var(--danger-hover); }

    button:focus-visible {
      outline: none;
      box-shadow: 0 0 0 3px var(--ring);
    }

    button:disabled {
      opacity: .5;
      cursor: not-allowed;
      transform: none;
      box-shadow: none;
    }

    .icon-btn {
      min-height: 38px;
      width: 38px;
      padding: 0;
      border-radius: 9px;
      background: var(--surface-strong);
    }

    .icon-btn svg { width: 17px; height: 17px; }

    .theme-toggle .sun { display: none; }
    .theme-toggle .moon { display: block; }
    :root[data-theme="dark"] .theme-toggle .sun { display: block; }
    :root[data-theme="dark"] .theme-toggle .moon { display: none; }

    .right {
      display: grid;
      gap: 18px;
      min-width: 0;
    }

    .toolbar {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }

    .status {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 32px;
      padding: 0 13px;
      border-radius: 999px;
      border: 1px solid #b7dbc9;
      background: color-mix(in srgb, var(--ok) 12%, var(--surface));
      color: var(--ok);
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }

    .status::before {
      content: "";
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: currentColor;
    }

    .status.is-busy {
      border-color: color-mix(in srgb, var(--accent) 40%, transparent);
      background: color-mix(in srgb, var(--accent) 12%, var(--surface));
      color: var(--accent);
    }

    .status.is-busy::before { animation: pulse 1s ease-in-out infinite; }

    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: .35; transform: scale(.7); }
    }

    .status.is-error {
      border-color: color-mix(in srgb, var(--danger) 40%, transparent);
      background: color-mix(in srgb, var(--danger) 12%, var(--surface));
      color: var(--danger);
    }

    .status.is-warn {
      border-color: color-mix(in srgb, var(--warn) 45%, transparent);
      background: color-mix(in srgb, var(--warn) 14%, var(--surface));
      color: var(--warn);
    }

    .table-wrap {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--surface);
    }

    table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      min-width: 760px;
      font-size: 13px;
    }

    th, td {
      padding: 11px 13px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      white-space: nowrap;
      vertical-align: middle;
    }

    th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: var(--surface-strong);
      color: var(--muted);
      font-size: 11.5px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: .4px;
    }

    tbody tr { transition: background-color .12s ease; }
    tbody tr:hover td { background: var(--surface-soft); }

    tr:last-child td { border-bottom: 0; }

    td.mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
      color: var(--text);
    }

    .empty-cell {
      height: 78px;
      color: var(--muted);
      text-align: center;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 23px;
      padding: 0 9px;
      border-radius: 999px;
      border: 1px solid var(--line-strong);
      background: var(--surface-soft);
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
    }

    .badge.ok {
      border-color: color-mix(in srgb, var(--ok) 40%, transparent);
      background: color-mix(in srgb, var(--ok) 12%, var(--surface));
      color: var(--ok);
    }

    .badge.warn {
      border-color: color-mix(in srgb, var(--warn) 45%, transparent);
      background: color-mix(in srgb, var(--warn) 14%, var(--surface));
      color: var(--warn);
    }

    .badge.danger {
      border-color: color-mix(in srgb, var(--danger) 40%, transparent);
      background: color-mix(in srgb, var(--danger) 12%, var(--surface));
      color: var(--danger);
    }

    code, pre {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
    }

    pre {
      margin: 0;
      min-height: 280px;
      max-height: 540px;
      overflow: auto;
      padding: 15px;
      border-radius: 10px;
      border: 1px solid var(--code-line);
      background: var(--code-bg);
      color: var(--code-text);
      font-size: 12.5px;
      line-height: 1.65;
      white-space: pre-wrap;
      word-break: break-word;
    }

    pre:empty::before {
      content: "暂无输出";
      color: var(--muted);
      opacity: .6;
    }

    .split {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }

    .toast-wrap {
      position: fixed;
      right: 18px;
      bottom: 18px;
      z-index: 50;
      display: flex;
      flex-direction: column;
      gap: 10px;
      max-width: min(360px, calc(100vw - 36px));
      pointer-events: none;
    }

    .toast {
      pointer-events: auto;
      display: flex;
      align-items: flex-start;
      gap: 9px;
      padding: 11px 14px;
      border-radius: 10px;
      border: 1px solid var(--line);
      border-left: 3px solid var(--muted);
      background: var(--surface);
      color: var(--text);
      box-shadow: var(--shadow-pop);
      font-size: 13px;
      font-weight: 600;
      opacity: 0;
      transform: translateY(10px);
      transition: opacity .25s ease, transform .25s ease;
      word-break: break-word;
    }

    .toast.show { opacity: 1; transform: translateY(0); }
    .toast-ok { border-left-color: var(--ok); }
    .toast-error { border-left-color: var(--danger); }
    .toast-warn { border-left-color: var(--warn); }
    .toast-info { border-left-color: var(--accent); }

    @media (max-width: 980px) {
      main { grid-template-columns: 1fr; }
      main > section:first-child { position: static; }
    }

    @media (max-width: 560px) {
      header {
        align-items: flex-start;
        flex-direction: column;
        gap: 10px;
        position: static;
      }

      .head-right { width: 100%; justify-content: space-between; }
      h1 { font-size: 17px; }
      main { padding-inline: 12px; }

      .panel-head {
        align-items: flex-start;
        flex-direction: column;
      }

      .toolbar { width: 100%; }
      .split { grid-template-columns: 1fr; }

      .actions button[type="submit"],
      .actions button.danger { flex: 1 1 auto; }

      .toast-wrap { left: 12px; right: 12px; bottom: 12px; max-width: none; }
    }

    @media (prefers-reduced-motion: reduce) {
      * { transition: none !important; animation: none !important; }
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <span class="brand-logo" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none"><path d="M8 6.5v11l9-5.5-9-5.5z" fill="#fff"/></svg>
      </span>
      <div>
        <h1>Emby Nginx Manager</h1>
        <p class="brand-sub">反向代理与证书管理</p>
      </div>
    </div>
    <div class="head-right">
      <div class="status" id="status">就绪</div>
      <button class="icon-btn theme-toggle" id="theme-toggle" type="button" data-chrome title="切换主题" aria-label="切换主题">
        <svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
        <svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
      </button>
    </div>
  </header>

  <main>
    <section>
      <div class="panel-head">
        <h2>反代配置</h2>
      </div>
      <div class="panel-body stack">
        <form id="deploy-form" class="stack">
          <div class="field">
            <label for="frontend">访问地址</label>
            <input id="frontend" name="frontend" type="text" placeholder="jsq.emby.example.com" autocomplete="off" spellcheck="false">
          </div>
          <div class="field">
            <label for="backend">后端地址</label>
            <input id="backend" name="backend" type="text" placeholder="https://a.example.com" autocomplete="off" spellcheck="false">
          </div>
          <div class="split">
            <div class="field">
              <label for="cert_domain">证书域名</label>
              <input id="cert_domain" name="cert_domain" type="text" placeholder="example.com" autocomplete="off" spellcheck="false">
            </div>
            <div class="field">
              <label for="dns_provider">DNS Provider</label>
              <input id="dns_provider" name="dns_provider" type="text" placeholder="cf" autocomplete="off" spellcheck="false">
            </div>
          </div>
          <div class="checks">
            <label class="check"><input id="parse_cert_domain" name="parse_cert_domain" type="checkbox"> 自动提取根域名</label>
            <label class="check"><input id="enable_proxy_redirect" name="enable_proxy_redirect" type="checkbox"> 启用重定向代理</label>
            <label class="check"><input id="confirm_deploy" name="confirm_deploy" type="checkbox"> 确认写入配置</label>
          </div>
          <div class="actions">
            <button class="secondary" type="submit" value="preview">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1.5 12S5 5 12 5s10.5 7 10.5 7-3.5 7-10.5 7S1.5 12 1.5 12z"/><circle cx="12" cy="12" r="3"/></svg>
              预览
            </button>
            <button class="primary" type="submit" value="deploy">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L20 7"/></svg>
              写入
            </button>
          </div>
        </form>

        <form id="remove-form" class="stack">
          <div class="field">
            <label for="remove_target">删除地址</label>
            <input id="remove_target" name="remove_target" type="text" placeholder="https://jsq.emby.example.com" autocomplete="off" spellcheck="false">
          </div>
          <label class="check"><input id="confirm_remove" name="confirm_remove" type="checkbox"> 确认删除配置</label>
          <div class="actions">
            <button class="danger" type="submit">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13"/></svg>
              删除
            </button>
          </div>
        </form>
      </div>
    </section>

    <div class="right">
      <section>
        <div class="panel-head">
          <h2>当前配置</h2>
          <div class="toolbar">
            <button class="secondary" id="refresh-list" type="button">刷新</button>
            <button class="secondary" id="run-status" type="button">状态</button>
            <button class="secondary" id="run-doctor" type="button">健康检查</button>
          </div>
        </div>
        <div class="panel-body">
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>域名</th>
                  <th>端口</th>
                  <th>TLS</th>
                  <th>证书</th>
                  <th>后端</th>
                  <th>文件</th>
                </tr>
              </thead>
              <tbody id="config-body">
                <tr><td class="empty-cell" colspan="6">加载中</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section>
        <div class="panel-head">
          <h2>备份恢复</h2>
          <div class="toolbar">
            <button class="secondary" id="refresh-backups" type="button">刷新</button>
            <button class="primary" id="create-backup" type="button">备份</button>
          </div>
        </div>
        <div class="panel-body">
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>备份</th>
                  <th>时间</th>
                  <th>大小</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody id="backup-body">
                <tr><td class="empty-cell" colspan="4">加载中</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section>
        <div class="panel-head">
          <h2>操作历史</h2>
          <div class="toolbar">
            <button class="secondary" id="refresh-history" type="button">刷新</button>
          </div>
        </div>
        <div class="panel-body">
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>操作</th>
                  <th>状态</th>
                  <th>目标</th>
                  <th>耗时</th>
                  <th>详情</th>
                </tr>
              </thead>
              <tbody id="history-body">
                <tr><td class="empty-cell" colspan="6">加载中</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section>
        <div class="panel-head">
          <h2>命令输出</h2>
          <div class="toolbar">
            <button class="secondary" id="copy-output" type="button" data-chrome>复制</button>
            <button class="secondary" id="clear-output" type="button" data-chrome>清空</button>
          </div>
        </div>
        <div class="panel-body">
          <pre id="output"></pre>
        </div>
      </section>
    </div>
  </main>

  <div class="toast-wrap" id="toast-wrap" aria-live="polite" aria-atomic="false"></div>

  <script>
    const keyParam = new URLSearchParams(window.location.search).get('key');
    if (keyParam && window.history.replaceState) {
      window.history.replaceState({}, document.title, window.location.pathname);
    }
    const statusEl = document.getElementById('status');
    const outputEl = document.getElementById('output');
    const configBody = document.getElementById('config-body');
    const backupBody = document.getElementById('backup-body');
    const historyBody = document.getElementById('history-body');
    const toastWrap = document.getElementById('toast-wrap');

    const THEME_KEY = 'emby-webui-theme';

    function applyTheme(theme) {
      document.documentElement.setAttribute('data-theme', theme === 'dark' ? 'dark' : 'light');
    }

    function currentTheme() {
      return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
    }

    document.getElementById('theme-toggle').addEventListener('click', () => {
      const next = currentTheme() === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
      showToast(next === 'dark' ? '已切换到深色主题' : '已切换到浅色主题', 'info');
    });

    function showToast(message, type = 'info') {
      if (!message) return;
      const el = document.createElement('div');
      el.className = `toast toast-${type}`;
      el.textContent = message;
      toastWrap.appendChild(el);
      requestAnimationFrame(() => el.classList.add('show'));
      window.setTimeout(() => {
        el.classList.remove('show');
        window.setTimeout(() => el.remove(), 300);
      }, 3200);
    }

    let progressTimer = null;
    let progressStarted = 0;
    let progressLabel = '';

    function tickProgress() {
      const secs = Math.floor((Date.now() - progressStarted) / 1000);
      setStatus(`${progressLabel} ${secs}s`, 'busy');
    }

    function startProgress(label) {
      stopProgress();
      progressLabel = label;
      progressStarted = Date.now();
      setStatus(label, 'busy');
      progressTimer = window.setInterval(tickProgress, 1000);
    }

    function stopProgress() {
      if (progressTimer !== null) {
        window.clearInterval(progressTimer);
        progressTimer = null;
      }
    }

    function setStatus(text, state = 'ready') {
      statusEl.textContent = text;
      statusEl.className = 'status';
      if (state !== 'ready') statusEl.classList.add(`is-${state}`);
    }

    function setActionButtonsDisabled(disabled) {
      document.querySelectorAll('button:not([data-chrome])').forEach((button) => button.disabled = disabled);
    }

    function setBusy(text, options = {}) {
      setActionButtonsDisabled(true);
      if (options.progress) {
        startProgress(text);
      } else {
        stopProgress();
        setStatus(text, 'busy');
      }
    }

    function setReady(text = '就绪') {
      stopProgress();
      const state = /Error|失败|异常|错误/.test(text) ? 'error' : (/warn|Check failed|需要/.test(text) ? 'warn' : 'ready');
      setStatus(text, state);
      setActionButtonsDisabled(false);
    }

    function printOutput(result) {
      const lines = [];
      if (typeof result.exit_code === 'number') lines.push(`exit=${result.exit_code}`);
      if (result.command) lines.push(`$ ${result.command}`);
      if (result.output) lines.push(result.output);
      outputEl.textContent = lines.join('\n\n').trim();
    }

    async function api(path, options = {}) {
      const headers = Object.assign({
        'Content-Type': 'application/json',
        'X-Requested-With': 'EmbyNginxManager'
      }, options.headers || {});
      const response = await fetch(path, Object.assign({}, options, { headers }));
      const text = await response.text();
      let data = {};
      try {
        data = text ? JSON.parse(text) : {};
      } catch (error) {
        data = { error: text || `HTTP ${response.status}` };
      }
      if (!response.ok) {
        throw new Error(data.error || data.output || `HTTP ${response.status}`);
      }
      return data;
    }

    function parseList(text) {
      return text
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter((line) => line && !line.startsWith('编号') && !line.startsWith('----'))
        .map((line) => line.split(/\s{2,}/))
        .filter((parts) => parts.length >= 7)
        .map((parts) => ({
          domain: parts[1],
          port: parts[2],
          tls: parts[3],
          cert: parts[4],
          backend: parts[5],
          file: parts.slice(6).join(' ')
        }));
    }

    function certBadgeState(value) {
      if (!value || value === '-') return '';
      const match = String(value).match(/^(-?\d+)d?$/);
      if (!match) return 'warn';
      const days = Number(match[1]);
      if (days < 0) return 'danger';
      if (days < 15) return 'danger';
      if (days < 30) return 'warn';
      return 'ok';
    }

    function formatTime(value) {
      if (!value) return '-';
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return value;
      return date.toLocaleString();
    }

    function formatBytes(value) {
      const size = Number(value || 0);
      if (size < 1024) return `${size} B`;
      if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
      return `${(size / 1024 / 1024).toFixed(1)} MB`;
    }

    function actionText(value) {
      return {
        preview: '预览',
        deploy: '写入',
        remove: '删除',
        doctor: '健康检查',
        backup: '备份',
        restore: '恢复'
      }[value] || value || '-';
    }

    function renderStatusBadge(ok, exitCode) {
      const badge = document.createElement('span');
      badge.className = `badge ${ok ? 'ok' : 'danger'}`;
      badge.textContent = ok ? '成功' : `失败${typeof exitCode === 'number' ? ` ${exitCode}` : ''}`;
      return badge;
    }

    function renderConfigs(rows) {
      if (!rows.length) {
        configBody.innerHTML = '<tr><td class="empty-cell" colspan="6">暂无脚本管理的配置</td></tr>';
        return;
      }
      configBody.replaceChildren(...rows.map((row) => {
        const tr = document.createElement('tr');
        const cells = [
          { value: row.domain, mono: true },
          { value: row.port, mono: true },
          { value: row.tls, badge: row.tls === 'yes' ? 'ok' : 'warn', text: row.tls === 'yes' ? 'TLS' : 'HTTP' },
          { value: row.cert, badge: certBadgeState(row.cert) },
          { value: row.backend, mono: true },
          { value: row.file, mono: true }
        ];
        cells.forEach((cell) => {
          const td = document.createElement('td');
          if (cell.mono) td.classList.add('mono');
          if (cell.badge) {
            const badge = document.createElement('span');
            badge.className = `badge ${cell.badge}`;
            badge.textContent = cell.text || cell.value || '-';
            td.appendChild(badge);
          } else {
            td.textContent = cell.text || cell.value || '-';
          }
          tr.appendChild(td);
        });
        return tr;
      }));
    }

    function renderBackups(rows) {
      if (!rows.length) {
        backupBody.innerHTML = '<tr><td class="empty-cell" colspan="4">暂无备份</td></tr>';
        return;
      }
      backupBody.replaceChildren(...rows.map((row) => {
        const tr = document.createElement('tr');
        [
          { value: row.name, mono: true },
          { value: formatTime(row.mtime) },
          { value: formatBytes(row.size), mono: true }
        ].forEach((cell) => {
          const td = document.createElement('td');
          if (cell.mono) td.classList.add('mono');
          td.textContent = cell.value || '-';
          tr.appendChild(td);
        });
        const actionTd = document.createElement('td');
        const button = document.createElement('button');
        button.className = 'secondary';
        button.type = 'button';
        button.textContent = '恢复';
        button.addEventListener('click', () => restoreBackup(row.name));
        actionTd.appendChild(button);
        tr.appendChild(actionTd);
        return tr;
      }));
    }

    function renderHistory(rows) {
      if (!rows.length) {
        historyBody.innerHTML = '<tr><td class="empty-cell" colspan="6">暂无历史</td></tr>';
        return;
      }
      historyBody.replaceChildren(...rows.map((row) => {
        const tr = document.createElement('tr');
        [
          { value: formatTime(row.time), mono: true },
          { value: actionText(row.action) }
        ].forEach((cell) => {
          const td = document.createElement('td');
          if (cell.mono) td.classList.add('mono');
          td.textContent = cell.value || '-';
          tr.appendChild(td);
        });
        const statusTd = document.createElement('td');
        statusTd.appendChild(renderStatusBadge(row.ok, row.exit_code));
        tr.appendChild(statusTd);

        const targetTd = document.createElement('td');
        targetTd.classList.add('mono');
        targetTd.textContent = row.target || '-';
        tr.appendChild(targetTd);

        const durationTd = document.createElement('td');
        durationTd.classList.add('mono');
        durationTd.textContent = typeof row.duration_ms === 'number' ? `${row.duration_ms} ms` : '-';
        tr.appendChild(durationTd);

        const detailTd = document.createElement('td');
        const button = document.createElement('button');
        button.className = 'secondary';
        button.type = 'button';
        button.dataset.chrome = '';
        button.textContent = '查看';
        button.addEventListener('click', () => {
          printOutput({
            ok: row.ok,
            exit_code: row.exit_code,
            command: row.command || `${actionText(row.action)} ${row.target || ''}`.trim(),
            output: row.message || ''
          });
        });
        detailTd.appendChild(button);
        tr.appendChild(detailTd);
        return tr;
      }));
    }

    async function refreshList(showOutput = true) {
      setBusy('加载中');
      try {
        const result = await api('/api/list');
        if (showOutput) printOutput(result);
        renderConfigs(result.configs || parseList(result.output || ''));
        setReady('已加载');
      } catch (error) {
        outputEl.textContent = error.message;
        configBody.innerHTML = '<tr><td class="empty-cell" colspan="6">加载失败</td></tr>';
        setReady('错误');
        showToast(error.message, 'error');
      }
    }

    async function refreshBackups(showOutput = false) {
      setBusy('加载备份');
      try {
        const result = await api('/api/backups');
        renderBackups(result.backups || []);
        if (showOutput) printOutput({ ok: true, exit_code: 0, command: 'GET /api/backups', output: JSON.stringify(result.backups || [], null, 2) });
        setReady('已加载');
      } catch (error) {
        outputEl.textContent = error.message;
        backupBody.innerHTML = '<tr><td class="empty-cell" colspan="4">加载失败</td></tr>';
        setReady('错误');
        showToast(error.message, 'error');
      }
    }

    async function refreshHistory(showOutput = false) {
      setBusy('加载历史');
      try {
        const result = await api('/api/history');
        renderHistory(result.history || []);
        if (showOutput) printOutput({ ok: true, exit_code: 0, command: 'GET /api/history', output: JSON.stringify(result.history || [], null, 2) });
        setReady('已加载');
      } catch (error) {
        outputEl.textContent = error.message;
        historyBody.innerHTML = '<tr><td class="empty-cell" colspan="6">加载失败</td></tr>';
        setReady('错误');
        showToast(error.message, 'error');
      }
    }

    async function restoreBackup(name) {
      try {
        setBusy('预览恢复');
        const preview = await api('/api/restore-preview', {
          method: 'POST',
          body: JSON.stringify({ name })
        });
        const files = preview.files || [];
        printOutput({
          ok: true,
          exit_code: 0,
          command: `restore preview ${name}`,
          output: files.map((file) => file.path).join('\n') || '无可恢复文件'
        });
        setReady('待确认');
        if (!window.confirm(`确认恢复备份 ${name}？将恢复 ${files.length} 个文件。`)) {
          showToast('已取消恢复', 'info');
          return;
        }
        setBusy('恢复中', { progress: true });
        const result = await api('/api/restore', {
          method: 'POST',
          body: JSON.stringify({ name, confirm_restore: true })
        });
        printOutput(result);
        await refreshList(false);
        await refreshHistory(false);
        setReady(result.ok ? '完成' : '失败');
        showToast(result.ok ? '恢复完成' : '恢复失败', result.ok ? 'ok' : 'error');
      } catch (error) {
        outputEl.textContent = error.message;
        await refreshHistory(false);
        setReady('错误');
        showToast(error.message, 'error');
      }
    }

    document.getElementById('refresh-list').addEventListener('click', () => refreshList(true));
    document.getElementById('refresh-backups').addEventListener('click', () => refreshBackups(true));
    document.getElementById('refresh-history').addEventListener('click', () => refreshHistory(true));

    document.getElementById('create-backup').addEventListener('click', async () => {
      setBusy('备份中', { progress: true });
      try {
        const result = await api('/api/backup', { method: 'POST', body: '{}' });
        printOutput(result);
        await refreshBackups(false);
        await refreshHistory(false);
        setReady('完成');
        showToast('备份完成', 'ok');
      } catch (error) {
        outputEl.textContent = error.message;
        await refreshHistory(false);
        setReady('错误');
        showToast(error.message, 'error');
      }
    });

    document.getElementById('run-status').addEventListener('click', async () => {
      setBusy('检查中');
      try {
        const result = await api('/api/status');
        printOutput({
          ok: true,
          exit_code: 0,
          command: 'GET /api/status',
          output: JSON.stringify(result, null, 2)
        });
        setReady('正常');
      } catch (error) {
        outputEl.textContent = error.message;
        setReady('错误');
        showToast(error.message, 'error');
      }
    });

    document.getElementById('clear-output').addEventListener('click', () => {
      outputEl.textContent = '';
      showToast('已清空输出', 'info');
    });

    document.getElementById('copy-output').addEventListener('click', async () => {
      const text = outputEl.textContent || '';
      if (!text) {
        showToast('没有可复制的内容', 'warn');
        return;
      }
      try {
        await navigator.clipboard.writeText(text);
        showToast('已复制到剪贴板', 'ok');
      } catch (error) {
        const area = document.createElement('textarea');
        area.value = text;
        area.style.position = 'fixed';
        area.style.left = '-9999px';
        document.body.appendChild(area);
        area.focus();
        area.select();
        document.execCommand('copy');
        area.remove();
        showToast('已复制到剪贴板', 'ok');
      }
    });

    document.getElementById('run-doctor').addEventListener('click', async () => {
      setBusy('检查中', { progress: true });
      try {
        const result = await api('/api/doctor', { method: 'POST', body: '{}' });
        printOutput(result);
        await refreshHistory(false);
        setReady(result.exit_code === 0 ? '正常' : '检查失败');
        showToast(result.exit_code === 0 ? '健康检查通过' : '健康检查发现问题', result.exit_code === 0 ? 'ok' : 'warn');
      } catch (error) {
        outputEl.textContent = error.message;
        await refreshHistory(false);
        setReady('错误');
        showToast(error.message, 'error');
      }
    });

    document.getElementById('deploy-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const mode = event.submitter ? event.submitter.value : 'preview';
      const form = event.currentTarget;
      const data = Object.fromEntries(new FormData(form).entries());
      const payload = {
        frontend: data.frontend || '',
        backend: data.backend || '',
        cert_domain: data.cert_domain || '',
        dns_provider: data.dns_provider || '',
        parse_cert_domain: form.parse_cert_domain.checked,
        enable_proxy_redirect: form.enable_proxy_redirect.checked,
        dry_run: mode !== 'deploy',
        confirm_deploy: form.confirm_deploy.checked
      };

      if (mode === 'deploy' && !payload.confirm_deploy) {
        outputEl.textContent = '需要勾选确认写入配置';
        setReady('需要确认');
        showToast('请先勾选“确认写入配置”', 'warn');
        return;
      }

      setBusy(mode === 'deploy' ? '写入中' : '预览中', { progress: true });
      try {
        const result = await api('/api/deploy', { method: 'POST', body: JSON.stringify(payload) });
        printOutput(result);
        await refreshList(false);
        await refreshHistory(false);
        setReady(result.exit_code === 0 ? '完成' : '失败');
        if (result.exit_code === 0) {
          showToast(mode === 'deploy' ? '配置已写入' : '预览完成', 'ok');
        } else {
          showToast(mode === 'deploy' ? '写入失败' : '预览失败', 'error');
        }
      } catch (error) {
        outputEl.textContent = error.message;
        await refreshHistory(false);
        setReady('错误');
        showToast(error.message, 'error');
      }
    });

    document.getElementById('remove-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const data = Object.fromEntries(new FormData(form).entries());
      const payload = {
        target: data.remove_target || '',
        confirm_remove: form.confirm_remove.checked
      };
      if (!payload.confirm_remove) {
        outputEl.textContent = '需要勾选确认删除配置';
        setReady('需要确认');
        showToast('请先勾选“确认删除配置”', 'warn');
        return;
      }
      if (!window.confirm(`确认删除配置 ${payload.target || ''}？该操作不可撤销。`)) {
        showToast('已取消删除', 'info');
        return;
      }
      setBusy('删除中', { progress: true });
      try {
        const result = await api('/api/remove', { method: 'POST', body: JSON.stringify(payload) });
        printOutput(result);
        await refreshList(false);
        await refreshHistory(false);
        setReady(result.exit_code === 0 ? '完成' : '失败');
        showToast(result.exit_code === 0 ? '配置已删除' : '删除失败', result.exit_code === 0 ? 'ok' : 'error');
      } catch (error) {
        outputEl.textContent = error.message;
        await refreshHistory(false);
        setReady('错误');
        showToast(error.message, 'error');
      }
    });

    refreshList();
    refreshBackups();
    refreshHistory();
  </script>
</body>
</html>
"""


class WebUIError(Exception):
    pass


def strip_ansi(value):
    return ANSI_RE.sub("", value)


def resolve_script_path():
    env_path = os.environ.get("EMBY_NGINX_MANAGER_SCRIPT")
    if env_path:
        return Path(env_path)

    local_script = Path(__file__).resolve().with_name("deploy.sh")
    if local_script.is_file():
        return local_script

    return Path("/opt/emby-nginx-manager/deploy.sh")


def command_env():
    env = os.environ.copy()
    env.setdefault("LC_ALL", "C.UTF-8")
    env.setdefault("LANG", "C.UTF-8")
    return env


def run_command(script, args, timeout):
    command = ["bash", str(script), *args]
    started = time.time()
    try:
        proc = subprocess.Popen(
            command,
            cwd=str(script.parent),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=command_env(),
            start_new_session=True,
        )
    except OSError as exc:
        return {
            "ok": False,
            "exit_code": 127,
            "command": shell_quote(command),
            "output": redact_sensitive_text(strip_ansi(str(exc))),
            "duration_ms": int((time.time() - started) * 1000),
        }

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
        output = (stdout or "") + (stderr or "")
        if not output and exc.output:
            output = str(exc.output)
        return {
            "ok": False,
            "exit_code": 124,
            "command": shell_quote(command),
            "output": redact_sensitive_text(strip_ansi(output + "\nCommand timed out.")),
            "duration_ms": int((time.time() - started) * 1000),
        }

    output = (stdout or "") + (stderr or "")
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "command": shell_quote(command),
        "output": redact_sensitive_text(strip_ansi(output)).strip(),
        "duration_ms": int((time.time() - started) * 1000),
    }


def run_system_command(command, timeout=60):
    started = time.time()
    try:
        proc = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=command_env(),
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "command": shell_quote(command),
            "output": redact_sensitive_text(strip_ansi(output)).strip(),
            "duration_ms": int((time.time() - started) * 1000),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        output = ""
        if isinstance(exc, subprocess.TimeoutExpired):
            output = (exc.stdout or "") + (exc.stderr or "")
            exit_code = 124
        else:
            output = str(exc)
            exit_code = 127
        return {
            "ok": False,
            "exit_code": exit_code,
            "command": shell_quote(command),
            "output": redact_sensitive_text(strip_ansi(output)).strip(),
            "duration_ms": int((time.time() - started) * 1000),
        }


def utc_timestamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def redact_sensitive_text(value):
    text = str(value or "")
    text = re.sub(
        r"([?&](?:key|token|password|secret|access_key)=)[^ &\"\n]+",
        r"\1<redacted>",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"((?:^|\s)--(?:key|token|password|secret|access[-_]?key|webui[-_]?key)(?:=|\s+))\S+",
        r"\1<redacted>",
        text,
        flags=re.I,
    )
    text = re.sub(r"(X-Emby-Webui-Key:\s*)\S+", r"\1<redacted>", text, flags=re.I)
    text = re.sub(
        r"\b([A-Za-z0-9_.-]*(?:TOKEN|PASSWORD|SECRET|ACCESS_KEY|WEBUI_KEY)[A-Za-z0-9_.-]*=)\S+",
        r"\1<redacted>",
        text,
        flags=re.I,
    )
    text = re.sub(
        r'("?[A-Za-z0-9_.-]*(?:token|password|secret|access_key|webui_key)[A-Za-z0-9_.-]*"?\s*:\s*")[^"]*(")',
        r"\1<redacted>\2",
        text,
        flags=re.I,
    )
    return text


def safe_output_tail(output):
    text = redact_sensitive_text(strip_ansi(str(output or ""))).strip()
    if len(text) > HISTORY_OUTPUT_TAIL:
        text = text[-HISTORY_OUTPUT_TAIL:]
    return text


def safe_history_text(value, max_len=512):
    text = redact_sensitive_text(value).strip()
    text = "".join(ch if ord(ch) >= 32 and ord(ch) != 127 else " " for ch in text)
    text = re.sub(r"\s+", " ", text)
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text


def action_target(action, payload):
    payload = payload or {}
    if action in {"deploy", "preview"}:
        frontend = safe_history_text(payload.get("frontend", ""), max_len=253)
        backend = safe_history_text(payload.get("backend", ""), max_len=512)
        if frontend and backend:
            return f"{frontend} -> {backend}"
        return frontend or backend
    if action == "remove":
        return safe_history_text(payload.get("target", ""), max_len=512)
    if action == "restore":
        return safe_history_text(payload.get("name", ""), max_len=128)
    return ""


def history_entry(action, result, payload=None):
    return {
        "time": utc_timestamp(),
        "action": action,
        "ok": bool(result.get("ok")),
        "exit_code": result.get("exit_code"),
        "duration_ms": result.get("duration_ms", 0),
        "target": action_target(action, payload),
        "command": safe_history_text(result.get("command", ""), max_len=512),
        "message": safe_output_tail(result.get("output", "")),
    }


def read_history(history_file):
    if not history_file.is_file():
        return []
    rows = []
    with history_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows[-HISTORY_LIMIT:]


def append_history(history_file, lock, entry):
    with lock:
        history_file.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        rows = read_history(history_file)
        rows.append(entry)
        rows = rows[-HISTORY_LIMIT:]
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                prefix=f".{history_file.name}.",
                suffix=".tmp",
                dir=history_file.parent,
                delete=False,
            ) as handle:
                tmp = Path(handle.name)
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            os.chmod(tmp, 0o600)
            os.replace(tmp, history_file)
        finally:
            if tmp is not None:
                try:
                    tmp.unlink()
                except FileNotFoundError:
                    pass


def parse_config_rows(output):
    rows = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("编号") or line.startswith("----") or line.startswith("["):
            continue
        parts = re.split(r"\s{2,}", line)
        if len(parts) < 7 or not parts[0].isdigit():
            continue
        rows.append(
            {
                "index": int(parts[0]),
                "domain": parts[1],
                "port": parts[2],
                "tls": parts[3],
                "cert": parts[4],
                "backend": parts[5],
                "file": " ".join(parts[6:]),
            }
        )
    return rows


def file_has_any_marker(path, markers):
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return any(marker in text for marker in markers)


def cert_backup_arcname_allowed(arcname):
    if arcname.startswith("/") or ".." in Path(arcname).parts:
        return False
    return bool(CERT_BACKUP_ARC_RE.fullmatch(arcname))


def configured_nginx_conf_dir():
    value = str(os.environ.get("NGINX_CONF_DIR", str(DEFAULT_NGINX_CONF_DIR))).strip()
    if not value:
        value = str(DEFAULT_NGINX_CONF_DIR)
    if CONFIG_PATH_FORBIDDEN_RE.search(value) or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise WebUIError("Nginx 配置目录包含不支持的字符")
    path = Path(value)
    if not path.is_absolute() or path == Path("/") or ".." in path.parts:
        raise WebUIError("Nginx 配置目录必须是安全的绝对路径")
    return path


def managed_nginx_config_arc_dirs():
    return {
        backup_arcname(DEFAULT_NGINX_CONF_DIR),
        backup_arcname(configured_nginx_conf_dir()),
    }


def managed_nginx_config_arcname_allowed(arcname):
    if arcname.startswith("/") or ".." in Path(arcname).parts:
        return False
    path = Path(arcname)
    return path.suffix == ".conf" and str(path.parent) in managed_nginx_config_arc_dirs()


def webui_service_restore_allowed(text):
    if not all(marker in text for marker in WEBUI_SERVICE_MARKERS):
        return False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith("ExecStart="):
            continue
        command = line.split("=", 1)[1]
        return "webui.py" in command and re.search(r"(^|\s)--script(\s|=|$)", command) is not None
    return False


def restore_member_content_allowed(arcname, data):
    if managed_nginx_config_arcname_allowed(arcname):
        text = data.decode("utf-8", errors="ignore")
        return any(marker in text for marker in MANAGED_CONFIG_MARKERS)
    if arcname == "etc/systemd/system/emby-nginx-webui.service":
        text = data.decode("utf-8", errors="ignore")
        return webui_service_restore_allowed(text)
    if arcname == "etc/nginx/.htpasswd-emby-webui":
        return b"\n" not in data.rstrip(b"\n") and b":" in data
    if cert_backup_arcname_allowed(arcname):
        return bool(data)
    return True


def config_certificate_arcnames_from_data(data):
    text = data.decode("utf-8", errors="ignore")
    certs = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"ssl_certificate(?:_key)?\s+([^;\s]+)", line)
        if not match:
            continue
        value = match.group(1)
        if value.startswith("$"):
            continue
        path = Path(value)
        if path.is_absolute() and cert_backup_path_allowed(path):
            certs.add(backup_arcname(path))
    return certs


def validate_restore_member(member, data=None):
    if member.isdir() or member.name == "manifest.json" or member.name in RESTORE_SKIP_ARCNAMES:
        return
    if not member.isfile() or not restore_allowed_path(member.name):
        raise WebUIError(f"备份包含不允许恢复的路径: {member.name}")
    if member.size < 0 or member.size > RESTORE_MAX_MEMBER_BYTES:
        raise WebUIError(f"备份文件过大或大小无效: {member.name}")
    if data is not None and not restore_member_content_allowed(member.name, data):
        raise WebUIError(f"备份文件内容缺少托管标记或格式无效: {member.name}")


def read_restore_member_data(tar, member):
    handle = tar.extractfile(member)
    if handle is None:
        raise WebUIError(f"无法读取备份文件: {member.name}")
    data = handle.read(RESTORE_MAX_MEMBER_BYTES + 1)
    if len(data) != member.size:
        raise WebUIError(f"备份文件大小不一致: {member.name}")
    validate_restore_member(member, data)
    return data


def load_restore_archive_members(tar):
    items = []
    skipped = []
    cert_refs = set()
    total_size = 0

    for member in tar.getmembers():
        if member.isdir() or member.name == "manifest.json":
            continue
        if member.name in RESTORE_SKIP_ARCNAMES:
            skipped.append(member.name)
            continue
        validate_restore_member(member)
        total_size += member.size
        if total_size > RESTORE_MAX_TOTAL_BYTES:
            raise WebUIError("备份文件总大小过大")
        data = read_restore_member_data(tar, member)
        if managed_nginx_config_arcname_allowed(member.name):
            cert_refs.update(config_certificate_arcnames_from_data(data))
        items.append((member, data))

    for member, _data in items:
        if cert_backup_arcname_allowed(member.name) and member.name not in cert_refs:
            raise WebUIError(f"备份证书文件未被托管配置引用: {member.name}")

    return items, skipped


def cert_backup_path_allowed(path):
    if not path.is_absolute():
        return False
    return cert_backup_arcname_allowed(backup_arcname(path))


def backup_source_file_allowed(path):
    return path.is_file() and not path.is_symlink()


def config_certificate_paths(path):
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    certs = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"ssl_certificate(?:_key)?\s+([^;\s]+)", line)
        if not match:
            continue
        value = match.group(1)
        if value.startswith("$"):
            continue
        cert_path = Path(value)
        if cert_backup_path_allowed(cert_path) and backup_source_file_allowed(cert_path):
            certs.append(cert_path)
    return certs


def collect_backup_files():
    files = []
    conf_dir = configured_nginx_conf_dir()
    if conf_dir.is_dir():
        for path in sorted(conf_dir.glob("*.conf")):
            if backup_source_file_allowed(path) and file_has_any_marker(path, MANAGED_CONFIG_MARKERS):
                files.append(path)
                files.extend(config_certificate_paths(path))

    for path in (
        Path("/etc/nginx/.htpasswd-emby-webui"),
        Path("/etc/systemd/system/emby-nginx-webui.service"),
    ):
        if backup_source_file_allowed(path):
            files.append(path)

    unique = []
    seen = set()
    for path in files:
        resolved = str(path)
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def backup_arcname(path):
    return str(path).lstrip("/")


def normalize_tar_info(info, mode=None):
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    if mode is not None:
        info.mode = mode
    return info


def add_backup_file(tar, path):
    if not backup_source_file_allowed(path):
        return
    arcname = backup_arcname(path)
    info = tar.gettarinfo(str(path), arcname=arcname)
    normalize_tar_info(info, mode=restore_mode_for_arcname(arcname))
    with path.open("rb") as handle:
        tar.addfile(info, handle)


def next_backup_archive_path(backup_dir):
    now_ns = time.time_ns()
    seconds = now_ns // 1_000_000_000
    subsecond = now_ns % 1_000_000_000
    prefix = time.strftime("%Y%m%d%H%M%S", time.localtime(seconds))
    prefix = f"{prefix}{subsecond:09d}"
    for counter in range(1000):
        name = f"emby-nginx-manager-{prefix}{counter:03d}.tar.gz"
        path = backup_dir / name
        if not path.exists():
            return name, path
    raise WebUIError("无法生成唯一备份文件名")


def create_backup_archive(backup_dir, keep=DEFAULT_BACKUP_KEEP):
    backup_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    name, final_path = next_backup_archive_path(backup_dir)
    tmp_path = None
    files = collect_backup_files()
    manifest = {
        "created_at": utc_timestamp(),
        "files": [str(path) for path in files],
    }
    manifest_data = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")

    try:
        with tempfile.NamedTemporaryFile(prefix=f".{name}.", suffix=".tmp", dir=backup_dir, delete=False) as handle:
            tmp_path = Path(handle.name)
        with tarfile.open(tmp_path, "w:gz") as tar:
            info = tarfile.TarInfo("manifest.json")
            info.size = len(manifest_data)
            info.mtime = int(time.time())
            normalize_tar_info(info, mode=0o600)
            tar.addfile(info, io.BytesIO(manifest_data))
            for path in files:
                add_backup_file(tar, path)

        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, final_path)
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
    prune_backup_archives(backup_dir, keep)
    return {
        "ok": True,
        "exit_code": 0,
        "command": "create backup",
        "output": f"备份完成: {final_path}\n文件数量: {len(files)}",
        "duration_ms": 0,
        "name": name,
        "path": str(final_path),
        "files": [str(path) for path in files],
    }


def list_backup_archives(backup_dir):
    if not backup_dir.is_dir():
        return []
    rows = []
    for path in sorted(backup_dir.glob("emby-nginx-manager-*.tar.gz"), reverse=True):
        if not BACKUP_NAME_RE.fullmatch(path.name):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
            }
        )
    return rows


def prune_backup_archives(backup_dir, keep):
    try:
        keep = int(keep)
    except (TypeError, ValueError):
        keep = DEFAULT_BACKUP_KEEP
    if keep <= 0 or not backup_dir.is_dir():
        return
    backups = [backup_dir / row["name"] for row in list_backup_archives(backup_dir)]
    for path in backups[keep:]:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def preview_backup_archive(backup_dir, name):
    name = clean_text_field(name, label="备份名称", required=True, max_len=128)
    if not BACKUP_NAME_RE.fullmatch(name):
        raise WebUIError("备份名称无效")
    archive = backup_dir / name
    if not archive.is_file():
        raise WebUIError("备份不存在")

    files = []
    with tarfile.open(archive, "r:gz") as tar:
        items, skipped = load_restore_archive_members(tar)
        for member, _data in items:
            files.append({"path": "/" + member.name, "size": member.size})
    return {"ok": True, "name": name, "files": files, "skipped": skipped}


def restore_allowed_path(arcname):
    if arcname.startswith("/") or ".." in Path(arcname).parts:
        return False
    if arcname == "manifest.json":
        return False
    allowed_exact = {
        "etc/nginx/snippets/emby-webui-internal-key.conf",
        "etc/nginx/.htpasswd-emby-webui",
        "etc/systemd/system/emby-nginx-webui.service",
        "etc/emby-nginx-webui.env",
    }
    if arcname in allowed_exact:
        return True
    if cert_backup_arcname_allowed(arcname):
        return True
    if managed_nginx_config_arcname_allowed(arcname):
        return True
    return False


def restore_mode_for_arcname(arcname):
    if arcname in {
        "etc/emby-nginx-webui.env",
        "etc/nginx/snippets/emby-webui-internal-key.conf",
    }:
        return 0o600
    if cert_backup_arcname_allowed(arcname):
        if arcname.endswith("/key") or arcname.endswith("/privkey.pem"):
            return 0o600
        return 0o644
    if arcname == "etc/nginx/.htpasswd-emby-webui":
        return 0o640
    if arcname == "etc/systemd/system/emby-nginx-webui.service":
        return 0o644
    if managed_nginx_config_arcname_allowed(arcname):
        return 0o640
    return 0o600


def replace_regular_file(src, dest, mode):
    tmp_dest = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent, delete=False) as handle:
            tmp_dest = Path(handle.name)
            with src.open("rb") as source:
                shutil.copyfileobj(source, handle)
        os.chmod(tmp_dest, mode)
        os.replace(tmp_dest, dest)
    finally:
        if tmp_dest is not None:
            try:
                tmp_dest.unlink()
            except FileNotFoundError:
                pass


def ensure_regular_parent_dir(path):
    parent = path.parent
    existing = []
    current = parent
    while not current.exists() and current != current.parent:
        existing.append(current)
        current = current.parent
    if current.is_symlink() or not current.is_dir():
        raise WebUIError(f"恢复目标父目录不是普通目录: {current}")
    for part in reversed(existing):
        if part.exists() or part.is_symlink():
            if part.is_symlink() or not part.is_dir():
                raise WebUIError(f"恢复目标父目录不是普通目录: {part}")
            continue
        part.mkdir()


def rollback_restored_files(rollback, created):
    for dest, old in reversed(rollback):
        replace_regular_file(old, dest, restore_mode_for_arcname(backup_arcname(dest)))
    for dest in reversed(created):
        try:
            if dest.is_symlink() or not dest.is_file():
                continue
            dest.unlink()
        except FileNotFoundError:
            pass


def restore_backup_archive(backup_dir, name):
    name = clean_text_field(name, label="备份名称", required=True, max_len=128)
    if not BACKUP_NAME_RE.fullmatch(name):
        raise WebUIError("备份名称无效")
    archive = backup_dir / name
    if not archive.is_file():
        raise WebUIError("备份不存在")

    started = time.time()
    restored = []
    rollback = []
    created = []
    with tempfile.TemporaryDirectory(prefix="emby-nginx-restore-") as tmp_root:
        tmp_root_path = Path(tmp_root)
        with tarfile.open(archive, "r:gz") as tar:
            items, _skipped = load_restore_archive_members(tar)
            for member, data in items:
                src = tmp_root_path / member.name
                src.parent.mkdir(parents=True, exist_ok=True)
                with src.open("wb") as output:
                    output.write(data)
                os.chmod(src, restore_mode_for_arcname(member.name))

        backup_existing = tmp_root_path / "existing"
        try:
            for member, _data in sorted(items, key=lambda item: item[0].name):
                src = tmp_root_path / member.name
                rel = Path(member.name)
                dest = Path("/") / rel
                ensure_regular_parent_dir(dest)
                if dest.exists() or dest.is_symlink():
                    if dest.is_symlink() or not dest.is_file():
                        raise WebUIError(f"恢复目标不是普通文件: {dest}")
                    old = backup_existing / rel
                    old.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dest, old)
                    rollback.append((dest, old))
                else:
                    created.append(dest)
                replace_regular_file(src, dest, restore_mode_for_arcname(member.name))
                restored.append(str(dest))
        except (OSError, WebUIError):
            rollback_restored_files(rollback, created)
            raise

        test_result = run_system_command(["nginx", "-t"], timeout=60)
        if not test_result["ok"]:
            rollback_restored_files(rollback, created)
            raise WebUIError("恢复后的 Nginx 配置测试失败，已回滚: " + test_result.get("output", ""))

    reload_result = run_system_command(["nginx", "-s", "reload"], timeout=60)
    daemon_result = run_system_command(["systemctl", "daemon-reload"], timeout=60)
    output = [f"恢复完成: {name}", f"文件数量: {len(restored)}"]
    if reload_result.get("output"):
        output.append(reload_result["output"])
    if daemon_result.get("output"):
        output.append(daemon_result["output"])
    ok = reload_result["ok"] and daemon_result["ok"]
    return {
        "ok": ok,
        "exit_code": 0 if ok else 1,
        "command": f"restore backup {name}",
        "output": "\n".join(output),
        "duration_ms": int((time.time() - started) * 1000),
        "name": name,
        "files": restored,
    }


def shell_quote(parts):
    quoted = []
    for part in parts:
        if re.fullmatch(r"[A-Za-z0-9_./:=@,+-]+", part):
            quoted.append(part)
        else:
            quoted.append("'" + part.replace("'", "'\\''") + "'")
    return " ".join(quoted)


def make_access_key(length=24):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def validate_access_key(value):
    if value == "":
        return value
    if not ACCESS_KEY_RE.fullmatch(value):
        raise WebUIError("访问码只能包含 8-128 位字母、数字、点、下划线或短横线")
    return value


def host_is_loopback(host):
    if host in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def clean_text_field(value, label, required=False, max_len=512):
    value = str(value or "").strip()
    if not value:
        if required:
            raise WebUIError(f"{label}不能为空")
        return ""
    if len(value) > max_len:
        raise WebUIError(f"{label}过长")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise WebUIError(f"{label}包含不支持的控制字符")
    return value


def input_url_port(value):
    host_port = value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if host_port.startswith("["):
        end = host_port.find("]")
        if end != -1:
            rest = host_port[end + 1 :]
            if rest.startswith(":") and rest[1:].isdigit():
                return rest[1:]
            return ""
    if host_port.count(":") == 1:
        port = host_port.rsplit(":", 1)[1]
        if port.isdigit():
            return port
    return ""


def backend_should_default_http(value):
    host_port = value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if host_port == "localhost" or host_port.startswith("localhost:"):
        return True
    if host_port.startswith("127."):
        return True
    if host_port == "[::1]" or host_port.startswith("[::1]:"):
        return True
    return input_url_port(value) in {"80", "8096", "8097"}


def normalize_url_for_validation(value, role):
    if re.match(r"^https?://", value):
        return value
    if "://" in value:
        raise WebUIError("地址只支持 http:// 或 https://")
    port = input_url_port(value)
    if role == "frontend" and port == "80":
        return f"http://{value}"
    if role == "backend" and backend_should_default_http(value):
        return f"http://{value}"
    return f"https://{value}"


def validate_hostname(host, label):
    host = host.strip("[]")
    if not host:
        raise WebUIError(f"{label}缺少主机名")
    if "%" in host:
        raise WebUIError(f"{label}不支持带 zone id 的 IPv6 地址")
    try:
        ipaddress.ip_address(host)
        return
    except ValueError:
        pass
    if len(host) > 253:
        raise WebUIError(f"{label}主机名过长")
    labels = host.rstrip(".").split(".")
    if not labels or any(not DOMAIN_LABEL_RE.fullmatch(part) for part in labels):
        raise WebUIError(f"{label}主机名格式无效")


def validate_url_field(value, label, role):
    value = clean_text_field(value, label=label, required=True)
    if re.search(r"\s", value):
        raise WebUIError(f"{label}不能包含空白字符")
    normalized = normalize_url_for_validation(value, role)
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WebUIError(f"{label}格式无效")
    if parsed.username or parsed.password:
        raise WebUIError(f"{label}不支持用户名或密码")
    if parsed.query or parsed.fragment or parsed.params:
        raise WebUIError(f"{label}不能包含查询参数或锚点")
    try:
        port = parsed.port
    except ValueError as exc:
        raise WebUIError(f"{label}端口无效") from exc
    if port is not None and not 1 <= port <= 65535:
        raise WebUIError(f"{label}端口必须在 1-65535 之间")
    validate_hostname(parsed.hostname or "", label)
    path = parsed.path or "/"
    if URL_PATH_FORBIDDEN_RE.search(path):
        raise WebUIError(f"{label}路径包含 Nginx 配置不支持的字符")
    return value


def validate_cert_domain(value):
    value = clean_text_field(value, label="证书域名", max_len=253)
    if not value:
        return ""
    if value.startswith("*."):
        raise WebUIError("证书域名请输入根域名，不要包含 *.")
    validate_hostname(value, "证书域名")
    return value


def validate_dns_provider(value):
    value = clean_text_field(value, label="DNS Provider", max_len=32)
    if not value:
        return ""
    if value.startswith("dns_"):
        value = value[4:]
    if not DNS_PROVIDER_RE.fullmatch(value):
        raise WebUIError("DNS Provider 只能包含字母、数字或下划线")
    return value


def deploy_args(payload):
    frontend = validate_url_field(payload.get("frontend", ""), "访问地址", "frontend")
    backend = validate_url_field(payload.get("backend", ""), "后端地址", "backend")
    args = [
        "-y",
        frontend,
        "-r",
        backend,
    ]

    cert_domain = validate_cert_domain(payload.get("cert_domain", ""))
    if cert_domain:
        args.extend(["--cert-domain", cert_domain])

    dns_provider = validate_dns_provider(payload.get("dns_provider", ""))
    if dns_provider:
        args.extend(["--dns", dns_provider])

    if payload.get("parse_cert_domain"):
        args.append("--parse-cert-domain")

    if payload.get("enable_proxy_redirect"):
        args.append("--proxy-redirect")
    elif payload.get("no_proxy_redirect"):
        args.append("--no-proxy-redirect")

    if payload.get("dry_run", True):
        args.append("--dry-run")
    elif not payload.get("confirm_deploy"):
        raise WebUIError("需要确认写入配置")

    return args


class Handler(BaseHTTPRequestHandler):
    server_version = "EmbyNginxWebUI/0.1"

    def log_message(self, fmt, *args):
        message = redact_sensitive_text(fmt % args)
        sys.stderr.write("%s - %s\n" % (self.address_string(), message))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self.handle_index(parsed)
        if parsed.path == "/favicon.ico":
            return self.handle_favicon()
        if parsed.path == "/api/status":
            return self.handle_status()
        if parsed.path == "/api/list":
            return self.handle_list()
        if parsed.path == "/api/history":
            return self.handle_history()
        if parsed.path == "/api/backups":
            return self.handle_backups()
        if parsed.path == "/api/operation":
            return self.handle_operation()
        return self.not_found()

    def do_POST(self):
        if not self.same_origin_request():
            return self.json_response(403, {"error": "forbidden"})
        parsed = urlparse(self.path)
        if parsed.path == "/api/doctor":
            return self.handle_doctor()
        if parsed.path == "/api/deploy":
            return self.handle_deploy()
        if parsed.path == "/api/remove":
            return self.handle_remove()
        if parsed.path == "/api/backup":
            return self.handle_backup()
        if parsed.path == "/api/restore":
            return self.handle_restore()
        if parsed.path == "/api/restore-preview":
            return self.handle_restore_preview()
        return self.not_found()

    def handle_index(self, parsed):
        auth_source = self.authorization_source(parsed)
        if not auth_source:
            return self.forbidden_page()
        body = HTML.replace("__WEBUI_KEY__", json.dumps(""))
        headers = {}
        if auth_source == "query":
            headers["Set-Cookie"] = self.access_cookie_header()
        self.send_bytes(200, body.encode("utf-8"), "text/html; charset=utf-8", headers=headers)

    def handle_favicon(self):
        self.send_bytes(204, b"", "image/x-icon")

    def handle_list(self):
        if not self.authorized():
            return self.json_response(403, {"error": "forbidden"})
        result = run_command(self.server.script, ["--list"], timeout=60)
        result["configs"] = parse_config_rows(result.get("output", ""))
        self.json_response(200, result)

    def handle_status(self):
        if not self.authorized():
            return self.json_response(403, {"error": "forbidden"})
        self.json_response(
            200,
            {
                "ok": True,
                "webui": self.server_version,
                "script": str(self.server.script),
                "script_exists": self.server.script.is_file(),
                "auth_enabled": bool(self.server.access_key),
                "bind": "%s:%s" % self.server.server_address[:2],
                "operation": self.current_operation(),
            },
        )

    def handle_doctor(self):
        if not self.authorized():
            return self.json_response(403, {"error": "forbidden"})
        try:
            self.read_json_body()
        except WebUIError as exc:
            self.record_history("doctor", {"ok": False, "exit_code": 400, "output": str(exc), "duration_ms": 0})
            return self.json_response(400, {"error": str(exc)})
        if not self.acquire_operation("doctor"):
            return self.operation_busy_response()
        try:
            result = run_command(self.server.script, ["--doctor"], timeout=120)
            self.record_history("doctor", result)
            self.json_response(200 if result["ok"] else 500, result)
        finally:
            self.release_operation()

    def handle_deploy(self):
        if not self.authorized():
            return self.json_response(403, {"error": "forbidden"})
        payload = {}
        try:
            payload = self.read_json_body()
            args = deploy_args(payload)
        except WebUIError as exc:
            action = "preview" if payload.get("dry_run", True) else "deploy"
            self.record_history(action, {"ok": False, "exit_code": 400, "output": str(exc), "duration_ms": 0}, payload)
            return self.json_response(400, {"error": str(exc)})
        action = "preview" if payload.get("dry_run", True) else "deploy"
        if not self.acquire_operation(action):
            return self.operation_busy_response()
        try:
            result = run_command(self.server.script, args, timeout=900)
            self.record_history(action, result, payload)
            self.json_response(200 if result["ok"] else 500, result)
        finally:
            self.release_operation()

    def handle_remove(self):
        if not self.authorized():
            return self.json_response(403, {"error": "forbidden"})
        payload = {}
        try:
            payload = self.read_json_body()
            if not payload.get("confirm_remove"):
                raise WebUIError("需要确认删除配置")
            target = validate_url_field(payload.get("target", ""), "删除地址", "frontend")
        except WebUIError as exc:
            self.record_history("remove", {"ok": False, "exit_code": 400, "output": str(exc), "duration_ms": 0}, payload)
            return self.json_response(400, {"error": str(exc)})
        if not self.acquire_operation("remove"):
            return self.operation_busy_response()
        try:
            result = run_command(self.server.script, ["--remove", target, "--yes"], timeout=300)
            self.record_history("remove", result, payload)
            self.json_response(200 if result["ok"] else 500, result)
        finally:
            self.release_operation()

    def handle_history(self):
        if not self.authorized():
            return self.json_response(403, {"error": "forbidden"})
        self.json_response(200, {"ok": True, "history": read_history(self.server.history_file)[::-1]})

    def handle_backups(self):
        if not self.authorized():
            return self.json_response(403, {"error": "forbidden"})
        self.json_response(200, {"ok": True, "backups": list_backup_archives(self.server.backup_dir)})

    def handle_operation(self):
        if not self.authorized():
            return self.json_response(403, {"error": "forbidden"})
        self.json_response(200, {"ok": True, "operation": self.current_operation()})

    def handle_backup(self):
        if not self.authorized():
            return self.json_response(403, {"error": "forbidden"})
        if not self.acquire_operation("backup"):
            return self.operation_busy_response()
        try:
            try:
                self.read_json_body()
                result = create_backup_archive(self.server.backup_dir, self.server.backup_keep)
                status = 200
            except WebUIError as exc:
                result = {"ok": False, "exit_code": 400, "output": str(exc), "duration_ms": 0}
                status = 400
            except OSError as exc:
                result = {"ok": False, "exit_code": 1, "output": str(exc), "duration_ms": 0}
                status = 500
            self.record_history("backup", result)
            self.json_response(status, result if status != 400 else {"error": result["output"]})
        finally:
            self.release_operation()

    def handle_restore_preview(self):
        if not self.authorized():
            return self.json_response(403, {"error": "forbidden"})
        try:
            payload = self.read_json_body()
            result = preview_backup_archive(self.server.backup_dir, payload.get("name", ""))
        except (WebUIError, OSError, tarfile.TarError) as exc:
            return self.json_response(400, {"error": str(exc)})
        self.json_response(200, result)

    def handle_restore(self):
        if not self.authorized():
            return self.json_response(403, {"error": "forbidden"})
        payload = {}
        acquired = False
        try:
            payload = self.read_json_body()
            if not payload.get("confirm_restore"):
                raise WebUIError("需要确认恢复备份")
            if not self.acquire_operation("restore"):
                return self.operation_busy_response()
            acquired = True
            result = restore_backup_archive(self.server.backup_dir, payload.get("name", ""))
            status = 200 if result["ok"] else 500
        except WebUIError as exc:
            result = {"ok": False, "exit_code": 400, "output": str(exc), "duration_ms": 0}
            self.record_history("restore", result, payload)
            status = 400
            response = {"error": str(exc)}
        except (OSError, tarfile.TarError) as exc:
            result = {"ok": False, "exit_code": 1, "output": str(exc), "duration_ms": 0}
            self.record_history("restore", result, payload)
            status = 500
            response = result
        else:
            self.record_history("restore", result, payload)
            response = result
        finally:
            if acquired:
                self.release_operation()
        self.json_response(status, response)

    def record_history(self, action, result, payload=None):
        append_history(self.server.history_file, self.server.history_lock, history_entry(action, result, payload))

    def acquire_operation(self, action):
        if not self.server.operation_lock.acquire(blocking=False):
            return False
        self.server.operation_name = action
        self.server.operation_started = utc_timestamp()
        return True

    def release_operation(self):
        self.server.operation_name = ""
        self.server.operation_started = ""
        try:
            self.server.operation_lock.release()
        except RuntimeError:
            pass

    def current_operation(self):
        return {
            "busy": bool(self.server.operation_name),
            "action": self.server.operation_name,
            "started_at": self.server.operation_started,
        }

    def operation_busy_response(self):
        op = self.current_operation()
        return self.json_response(409, {"error": f"已有操作正在运行: {op.get('action') or 'unknown'}", "operation": op})

    def authorized(self, parsed=None):
        return bool(self.authorization_source(parsed))

    def authorization_source(self, parsed=None):
        if not self.server.access_key:
            return "disabled"
        header_key = self.headers.get("X-Emby-Webui-Key", "")
        if self.access_key_matches(header_key):
            return "header"
        cookie_key = self.request_cookies().get(COOKIE_NAME, "")
        if self.access_key_matches(cookie_key):
            return "cookie"
        if parsed is None:
            parsed = urlparse(self.path)
        query_key = parse_qs(parsed.query).get("key", [""])[0]
        if self.access_key_matches(query_key):
            return "query"
        return ""

    def access_key_matches(self, value):
        return bool(
            self.server.access_key
            and isinstance(value, str)
            and secrets.compare_digest(value, self.server.access_key)
        )

    def request_cookies(self):
        cookies = {}
        for part in self.headers.get("Cookie", "").split(";"):
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            cookies[name.strip()] = value.strip()
        return cookies

    def access_cookie_header(self):
        parts = [
            f"{COOKIE_NAME}={self.server.access_key}",
            "Path=/",
            "Max-Age=43200",
            "HttpOnly",
            "SameSite=Strict",
        ]
        if self.headers.get("X-Forwarded-Proto", "") == "https":
            parts.append("Secure")
        return "; ".join(parts)

    def same_origin_request(self):
        origin = self.headers.get("Origin", "")
        if origin:
            parsed = urlparse(origin)
            host = self.headers.get("Host", "")
            forwarded_proto = self.headers.get("X-Forwarded-Proto", "")
            if host and parsed.netloc == host and (not forwarded_proto or parsed.scheme == forwarded_proto):
                return True
            forwarded_host = self.headers.get("X-Forwarded-Host", "")
            origin_host = parsed.netloc
            if forwarded_host and origin_host == forwarded_host and (
                not forwarded_proto or parsed.scheme == forwarded_proto
            ):
                return True
            forwarded_port = self.headers.get("X-Forwarded-Port", "")
            if forwarded_host and forwarded_proto:
                expected = forwarded_host
                if forwarded_port and ":" not in forwarded_host:
                    default_port = "443" if forwarded_proto == "https" else "80"
                    if forwarded_port != default_port:
                        expected = f"{forwarded_host}:{forwarded_port}"
                return parsed.scheme == forwarded_proto and origin_host == expected
            return False
        fetch_site = self.headers.get("Sec-Fetch-Site", "")
        if fetch_site and fetch_site not in {"same-origin", "same-site", "none"}:
            return False
        if self.headers.get("X-Requested-With", "") == "EmbyNginxManager":
            return True
        header_key = self.headers.get("X-Emby-Webui-Key", "")
        return self.access_key_matches(header_key)

    def read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError as exc:
            raise WebUIError("Content-Length 无效") from exc
        if length < 0:
            raise WebUIError("Content-Length 无效")
        if length > MAX_BODY_BYTES:
            raise WebUIError("请求体过大")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise WebUIError(f"JSON 无效: {exc}") from exc
        if not isinstance(payload, dict):
            raise WebUIError("JSON 必须是对象")
        return payload

    def forbidden_page(self):
        body = (
            "<!doctype html><meta charset='utf-8'>"
            "<title>Emby Nginx Manager</title>"
            "<body style='font-family: system-ui; padding: 32px'>"
            "<h1>Emby Nginx Manager</h1>"
            "<p>请使用启动终端中显示的完整访问地址。</p>"
            "</body>"
        )
        self.send_bytes(403, body.encode("utf-8"), "text/html; charset=utf-8")

    def not_found(self):
        self.json_response(404, {"error": "not found"})

    def json_response(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_bytes(status, data, "application/json; charset=utf-8")

    def send_bytes(self, status, data, content_type, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)


class WebUIServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, handler, script, access_key, history_file, backup_dir, backup_keep):
        super().__init__(server_address, handler)
        self.script = script
        self.access_key = access_key
        self.history_file = history_file
        self.backup_dir = backup_dir
        self.backup_keep = backup_keep
        self.history_lock = threading.Lock()
        self.operation_lock = threading.Lock()
        self.operation_name = ""
        self.operation_started = ""


def parse_args():
    parser = argparse.ArgumentParser(description="Local WebUI for Emby Nginx Manager")
    parser.add_argument("--host", default=os.environ.get("EMBY_WEBUI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=env_int("EMBY_WEBUI_PORT", 8765, minimum=1))
    parser.add_argument("--script", default=str(resolve_script_path()))
    parser.add_argument("--key", default=os.environ.get("EMBY_WEBUI_KEY"))
    parser.add_argument("--history-file", default=os.environ.get("EMBY_WEBUI_HISTORY_FILE", str(DEFAULT_STATE_DIR / "history.jsonl")))
    parser.add_argument("--backup-dir", default=os.environ.get("EMBY_WEBUI_BACKUP_DIR", str(DEFAULT_BACKUP_DIR)))
    parser.add_argument("--backup-keep", type=int, default=DEFAULT_BACKUP_KEEP)
    return parser.parse_args()


def main():
    args = parse_args()
    if args.port < 1 or args.port > 65535:
        print("错误: WebUI 端口必须在 1-65535 之间。", file=sys.stderr)
        return 1
    script_arg = Path(args.script).expanduser()
    if script_arg.is_symlink():
        print(f"错误: 管理脚本不能是符号链接: {script_arg}", file=sys.stderr)
        return 1
    script = script_arg.resolve()
    if not script.is_file():
        print(f"错误: 找不到管理脚本: {script}", file=sys.stderr)
        return 1

    access_key = args.key
    if access_key is None:
        access_key = make_access_key()
    else:
        try:
            access_key = validate_access_key(access_key)
        except WebUIError as exc:
            print(f"错误: {exc}", file=sys.stderr)
            return 1

    if not access_key and not host_is_loopback(args.host):
        print("错误: 非本机监听地址必须启用访问码。", file=sys.stderr)
        return 1

    history_file = Path(args.history_file).expanduser().resolve()
    backup_dir = Path(args.backup_dir).expanduser().resolve()
    server = WebUIServer((args.host, args.port), Handler, script, access_key, history_file, backup_dir, args.backup_keep)
    url = f"http://{args.host}:{args.port}/"
    show_key_url = os.environ.get("EMBY_WEBUI_SHOW_KEY_URL", "1").lower() not in {"0", "false", "no", "off"}
    if access_key and show_key_url:
        url = f"{url}?key={access_key}"

    print("Emby Nginx Manager WebUI", flush=True)
    print(f"Script: {script}", flush=True)
    print(f"URL: {url}", flush=True)
    if access_key and not show_key_url:
        print("Auth: enabled", flush=True)
    if not host_is_loopback(args.host):
        print("Warning: WebUI is listening on a non-loopback address.", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
