#!/usr/bin/env python3
import argparse
import ipaddress
import json
import os
import re
import secrets
import string
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
ACCESS_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{8,128}$")
MAX_BODY_BYTES = 64 * 1024
COOKIE_NAME = "emby_webui_access"


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Emby Nginx Manager</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --surface: #ffffff;
      --surface-soft: #f8fafc;
      --surface-strong: #eef2f5;
      --line: #d8e0e7;
      --line-strong: #bdc9d4;
      --text: #17202a;
      --muted: #667687;
      --primary: #0f766e;
      --primary-hover: #0b5f59;
      --accent: #2563eb;
      --danger: #b42318;
      --danger-hover: #8f1d14;
      --warn: #a16207;
      --ok: #13795b;
      --shadow: 0 1px 2px rgba(16, 24, 40, .05), 0 10px 28px rgba(16, 24, 40, .08);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
    }

    header {
      min-height: 68px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px clamp(16px, 4vw, 42px);
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, .96);
      backdrop-filter: blur(8px);
      position: sticky;
      top: 0;
      z-index: 5;
    }

    h1 {
      margin: 0;
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 20px;
      font-weight: 750;
      letter-spacing: 0;
    }

    h1::before {
      content: "";
      width: 10px;
      height: 28px;
      border-radius: 3px;
      background: var(--primary);
      box-shadow: inset 0 -12px 0 rgba(37, 99, 235, .9);
      flex: 0 0 auto;
    }

    main {
      width: min(1380px, 100%);
      margin: 0 auto;
      padding: 20px clamp(14px, 3vw, 30px) 32px;
      display: grid;
      grid-template-columns: minmax(330px, 410px) minmax(0, 1fr);
      gap: 18px;
      align-items: start;
    }

    section {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    main > section:first-child {
      position: sticky;
      top: 88px;
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

    h2 {
      margin: 0;
      font-size: 14px;
      font-weight: 750;
      letter-spacing: 0;
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
      border-top: 1px solid var(--line);
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

    input[type="text"] {
      width: 100%;
      height: 39px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 11px;
      color: var(--text);
      background: #fff;
      outline: none;
      font-size: 14px;
      transition: border-color .15s ease, box-shadow .15s ease, background-color .15s ease;
    }

    input[type="text"]::placeholder {
      color: #98a5b3;
    }

    input[type="text"]:focus {
      border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(15, 118, 110, .14);
    }

    .checks {
      display: grid;
      grid-template-columns: 1fr;
      gap: 8px;
      padding: 2px 0;
    }

    .check {
      display: flex;
      align-items: center;
      gap: 9px;
      min-height: 28px;
      font-size: 13px;
      color: var(--text);
    }

    input[type="checkbox"] {
      width: 16px;
      height: 16px;
      margin: 0;
      accent-color: var(--primary);
    }

    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 9px;
    }

    button {
      min-height: 37px;
      border: 1px solid transparent;
      border-radius: 6px;
      padding: 0 13px;
      font-size: 13px;
      font-weight: 750;
      cursor: pointer;
      background: var(--surface-strong);
      color: var(--text);
      transition: transform .12s ease, background-color .15s ease, border-color .15s ease, box-shadow .15s ease;
    }

    button:hover {
      transform: translateY(-1px);
      box-shadow: 0 4px 12px rgba(16, 24, 40, .09);
    }

    button.primary {
      background: var(--primary);
      color: #fff;
    }

    button.primary:hover { background: var(--primary-hover); }

    button.danger {
      background: var(--danger);
      color: #fff;
    }

    button.danger:hover { background: var(--danger-hover); }

    button.secondary:hover { border-color: var(--line-strong); }

    button:focus-visible {
      outline: none;
      box-shadow: 0 0 0 3px rgba(37, 99, 235, .18);
    }

    button:disabled {
      opacity: .55;
      cursor: wait;
      transform: none;
      box-shadow: none;
    }

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
      min-height: 30px;
      padding: 0 11px;
      border-radius: 999px;
      border: 1px solid #b7dbc9;
      background: #ecfdf5;
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
      border-color: #bfdbfe;
      background: #eff6ff;
      color: var(--accent);
    }

    .status.is-error {
      border-color: #fecaca;
      background: #fef2f2;
      color: var(--danger);
    }

    .status.is-warn {
      border-color: #fde68a;
      background: #fffbeb;
      color: var(--warn);
    }

    .table-wrap {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
    }

    table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      min-width: 820px;
      font-size: 13px;
    }

    th, td {
      padding: 10px 12px;
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
      font-size: 12px;
      font-weight: 800;
    }

    tbody tr:hover td {
      background: #f8fbfc;
    }

    tr:last-child td { border-bottom: 0; }

    td.mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
      color: #334155;
    }

    .empty-cell {
      height: 74px;
      color: var(--muted);
      text-align: center;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      padding: 0 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: var(--surface-soft);
      color: #475569;
      font-size: 12px;
      font-weight: 800;
    }

    .badge.ok {
      border-color: #b7dbc9;
      background: #ecfdf5;
      color: var(--ok);
    }

    .badge.warn {
      border-color: #fde68a;
      background: #fffbeb;
      color: var(--warn);
    }

    .badge.danger {
      border-color: #fecaca;
      background: #fef2f2;
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
      padding: 14px;
      border-radius: 8px;
      border: 1px solid #172033;
      background: #101827;
      color: #e5edf5;
      font-size: 12px;
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .split {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }

    @media (max-width: 980px) {
      main {
        grid-template-columns: 1fr;
      }

      main > section:first-child {
        position: static;
      }
    }

    @media (max-width: 560px) {
      header {
        align-items: flex-start;
        flex-direction: column;
        position: static;
      }

      h1 {
        font-size: 18px;
      }

      main {
        padding-inline: 12px;
      }

      .panel-head {
        align-items: flex-start;
        flex-direction: column;
      }

      .split {
        grid-template-columns: 1fr;
      }

      .actions, .toolbar {
        flex-direction: column;
        width: 100%;
      }

      button {
        width: 100%;
      }
    }
  </style>
</head>
<body>
  <header>
    <h1>Emby Nginx Manager</h1>
    <div class="status" id="status">就绪</div>
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
            <input id="frontend" name="frontend" type="text" placeholder="jsq.emby.example.com" autocomplete="off">
          </div>
          <div class="field">
            <label for="backend">后端地址</label>
            <input id="backend" name="backend" type="text" placeholder="https://a.example.com" autocomplete="off">
          </div>
          <div class="split">
            <div class="field">
              <label for="cert_domain">证书域名</label>
              <input id="cert_domain" name="cert_domain" type="text" autocomplete="off">
            </div>
            <div class="field">
              <label for="dns_provider">DNS Provider</label>
              <input id="dns_provider" name="dns_provider" type="text" placeholder="cf" autocomplete="off">
            </div>
          </div>
          <div class="checks">
            <label class="check"><input id="parse_cert_domain" name="parse_cert_domain" type="checkbox"> 自动提取根域名</label>
            <label class="check"><input id="no_proxy_redirect" name="no_proxy_redirect" type="checkbox"> 禁用重定向代理</label>
            <label class="check"><input id="confirm_deploy" name="confirm_deploy" type="checkbox"> 确认写入配置</label>
          </div>
          <div class="actions">
            <button class="secondary" type="submit" value="preview">预览</button>
            <button class="primary" type="submit" value="deploy">写入</button>
          </div>
        </form>

        <form id="remove-form" class="stack">
          <div class="field">
            <label for="remove_target">删除地址</label>
            <input id="remove_target" name="remove_target" type="text" placeholder="https://jsq.emby.example.com" autocomplete="off">
          </div>
          <label class="check"><input id="confirm_remove" name="confirm_remove" type="checkbox"> 确认删除配置</label>
          <div class="actions">
            <button class="danger" type="submit">删除</button>
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
          <h2>命令输出</h2>
          <div class="toolbar">
            <button class="secondary" id="copy-output" type="button">复制</button>
            <button class="secondary" id="clear-output" type="button">清空</button>
          </div>
        </div>
        <div class="panel-body">
          <pre id="output"></pre>
        </div>
      </section>
    </div>
  </main>

  <script>
    const keyParam = new URLSearchParams(window.location.search).get('key');
    if (keyParam && window.history.replaceState) {
      window.history.replaceState({}, document.title, window.location.pathname);
    }
    const statusEl = document.getElementById('status');
    const outputEl = document.getElementById('output');
    const configBody = document.getElementById('config-body');

    function setStatus(text, state = 'ready') {
      statusEl.textContent = text;
      statusEl.className = 'status';
      if (state !== 'ready') statusEl.classList.add(`is-${state}`);
    }

    function setBusy(text) {
      setStatus(text, 'busy');
      document.querySelectorAll('button').forEach((button) => button.disabled = true);
    }

    function setReady(text = '就绪') {
      const state = /Error|失败|异常|错误/.test(text) ? 'error' : (/warn|Check failed|需要/.test(text) ? 'warn' : 'ready');
      setStatus(text, state);
      document.querySelectorAll('button').forEach((button) => button.disabled = false);
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
        'Content-Type': 'application/json'
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
      }
    }

    document.getElementById('refresh-list').addEventListener('click', () => refreshList(true));

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
      }
    });

    document.getElementById('clear-output').addEventListener('click', () => {
      outputEl.textContent = '';
      setReady('已清空');
    });

    document.getElementById('copy-output').addEventListener('click', async () => {
      const text = outputEl.textContent || '';
      if (!text) {
        setReady('空内容');
        return;
      }
      try {
        await navigator.clipboard.writeText(text);
        setReady('已复制');
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
        setReady('已复制');
      }
    });

    document.getElementById('run-doctor').addEventListener('click', async () => {
      setBusy('检查中');
      try {
        const result = await api('/api/doctor', { method: 'POST', body: '{}' });
        printOutput(result);
        setReady(result.exit_code === 0 ? '正常' : '检查失败');
      } catch (error) {
        outputEl.textContent = error.message;
        setReady('错误');
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
        no_proxy_redirect: form.no_proxy_redirect.checked,
        dry_run: mode !== 'deploy',
        confirm_deploy: form.confirm_deploy.checked
      };

      if (mode === 'deploy' && !payload.confirm_deploy) {
        outputEl.textContent = '需要勾选确认写入配置';
        setReady('需要确认');
        return;
      }

      setBusy(mode === 'deploy' ? '写入中' : '预览中');
      try {
        const result = await api('/api/deploy', { method: 'POST', body: JSON.stringify(payload) });
        printOutput(result);
        await refreshList(false);
        printOutput(result);
        setReady(result.exit_code === 0 ? '完成' : '失败');
      } catch (error) {
        outputEl.textContent = error.message;
        setReady('错误');
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
        return;
      }
      setBusy('删除中');
      try {
        const result = await api('/api/remove', { method: 'POST', body: JSON.stringify(payload) });
        printOutput(result);
        await refreshList(false);
        printOutput(result);
        setReady(result.exit_code === 0 ? '完成' : '失败');
      } catch (error) {
        outputEl.textContent = error.message;
        setReady('错误');
      }
    });

    refreshList();
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
        proc = subprocess.run(
            command,
            cwd=str(script.parent),
            text=True,
            capture_output=True,
            timeout=timeout,
            env=command_env(),
        )
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        return {
            "ok": False,
            "exit_code": 124,
            "command": shell_quote(command),
            "output": strip_ansi(output + "\nCommand timed out."),
            "duration_ms": int((time.time() - started) * 1000),
        }

    output = (proc.stdout or "") + (proc.stderr or "")
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "command": shell_quote(command),
        "output": strip_ansi(output).strip(),
        "duration_ms": int((time.time() - started) * 1000),
    }


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


def require_text(payload, key, label):
    value = clean_text_field(payload.get(key, ""), label=label, required=True)
    if not value:
        raise WebUIError(f"{label}不能为空")
    return value


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


def deploy_args(payload):
    args = [
        "-y",
        require_text(payload, "frontend", "访问地址"),
        "-r",
        require_text(payload, "backend", "后端地址"),
    ]

    cert_domain = clean_text_field(payload.get("cert_domain", ""), label="证书域名", max_len=253)
    if cert_domain:
        args.extend(["--cert-domain", cert_domain])

    dns_provider = clean_text_field(payload.get("dns_provider", ""), label="DNS Provider", max_len=32)
    if dns_provider:
        args.extend(["--dns", dns_provider])

    if payload.get("parse_cert_domain"):
        args.append("--parse-cert-domain")

    if payload.get("no_proxy_redirect"):
        args.append("--no-proxy-redirect")

    if payload.get("dry_run", True):
        args.append("--dry-run")
    elif not payload.get("confirm_deploy"):
        raise WebUIError("需要确认写入配置")

    return args


class Handler(BaseHTTPRequestHandler):
    server_version = "EmbyNginxWebUI/0.1"

    def log_message(self, fmt, *args):
        message = re.sub(r"([?&]key=)[^ &\"]+", r"\1<redacted>", fmt % args)
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
            },
        )

    def handle_doctor(self):
        if not self.authorized():
            return self.json_response(403, {"error": "forbidden"})
        try:
            self.read_json_body()
        except WebUIError as exc:
            return self.json_response(400, {"error": str(exc)})
        result = run_command(self.server.script, ["--doctor"], timeout=120)
        self.json_response(200 if result["ok"] else 500, result)

    def handle_deploy(self):
        if not self.authorized():
            return self.json_response(403, {"error": "forbidden"})
        try:
            payload = self.read_json_body()
            args = deploy_args(payload)
        except WebUIError as exc:
            return self.json_response(400, {"error": str(exc)})
        result = run_command(self.server.script, args, timeout=900)
        self.json_response(200 if result["ok"] else 500, result)

    def handle_remove(self):
        if not self.authorized():
            return self.json_response(403, {"error": "forbidden"})
        try:
            payload = self.read_json_body()
            if not payload.get("confirm_remove"):
                raise WebUIError("需要确认删除配置")
            target = require_text(payload, "target", "删除地址")
        except WebUIError as exc:
            return self.json_response(400, {"error": str(exc)})
        result = run_command(self.server.script, ["--remove", target, "--yes"], timeout=300)
        self.json_response(200 if result["ok"] else 500, result)

    def authorized(self, parsed=None):
        return bool(self.authorization_source(parsed))

    def authorization_source(self, parsed=None):
        if not self.server.access_key:
            return "disabled"
        header_key = self.headers.get("X-Emby-Webui-Key", "")
        if header_key == self.server.access_key:
            return "header"
        cookie_key = self.request_cookies().get(COOKIE_NAME, "")
        if cookie_key == self.server.access_key:
            return "cookie"
        if parsed is None:
            parsed = urlparse(self.path)
        query_key = parse_qs(parsed.query).get("key", [""])[0]
        if query_key == self.server.access_key:
            return "query"
        return ""

    def request_cookies(self):
        cookies = {}
        for part in self.headers.get("Cookie", "").split(";"):
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            cookies[name.strip()] = value.strip()
        return cookies

    def access_cookie_header(self):
        return f"{COOKIE_NAME}={self.server.access_key}; Path=/; Max-Age=43200; HttpOnly; SameSite=Strict"

    def same_origin_request(self):
        origin = self.headers.get("Origin", "")
        if not origin:
            return True
        parsed = urlparse(origin)
        return parsed.netloc == self.headers.get("Host", "")

    def read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError as exc:
            raise WebUIError("Content-Length 无效") from exc
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

    def __init__(self, server_address, handler, script, access_key):
        super().__init__(server_address, handler)
        self.script = script
        self.access_key = access_key


def parse_args():
    parser = argparse.ArgumentParser(description="Local WebUI for Emby Nginx Manager")
    parser.add_argument("--host", default=os.environ.get("EMBY_WEBUI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("EMBY_WEBUI_PORT", "8765")))
    parser.add_argument("--script", default=str(resolve_script_path()))
    parser.add_argument("--key", default=os.environ.get("EMBY_WEBUI_KEY"))
    return parser.parse_args()


def main():
    args = parse_args()
    script = Path(args.script).expanduser().resolve()
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

    server = WebUIServer((args.host, args.port), Handler, script, access_key)
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
