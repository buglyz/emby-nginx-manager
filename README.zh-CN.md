# Emby Nginx Manager

一个面向已有 Nginx 环境的 Emby 反向代理管理脚本。它不会接管整份 Nginx 主配置，只会在 `conf.d` 下写入带 marker 的托管站点配置。

English: [README.md](README.md)

## 快速开始

从当前 `main` 分支安装或更新：

```bash
(
  set -e
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  curl -fsSL https://github.com/buglyz/emby-nginx-manager/archive/refs/heads/main.tar.gz | tar -xz -C "$tmp"
  bash "$tmp"/emby-nginx-manager-main/install.sh
)
```

生产环境建议固定 commit/tag，并配合 SHA256 校验。`install.sh` 在需要下载归档时会读取这些变量：

```bash
ARCHIVE_URL=https://github.com/buglyz/emby-nginx-manager/archive/<commit-or-tag>.tar.gz \
ARCHIVE_SHA256=<sha256>
```

默认安装路径是 `/opt/emby-nginx-manager`，快捷命令安装到 `/usr/local/bin/emby`。

打开交互菜单：

```bash
emby
```

只预览配置，不写文件、不申请证书、不重载 Nginx：

```bash
emby -y https://emby.example.com -r http://127.0.0.1:8096 --dry-run
```

新增反向代理：

```bash
emby -y https://emby.example.com -r http://127.0.0.1:8096
```

公网地址和后端地址可以省略协议：

```bash
emby -y emby.example.com -r 127.0.0.1:8096
emby -y emby.example.com -r a.example.com
emby -y emby.example.com:80 -r 127.0.0.1:8096
```

省略协议时，公网域名默认按 HTTPS，前端端口 `80` 默认按 HTTP，本机 Emby 常见端口如 `8096` 默认按 HTTP。

## 重定向代理

302/307 重定向代理默认关闭。如果后端 Emby 确实需要把上游跳转也代理到公网域名下，可以显式开启：

```bash
emby -y https://emby.example.com -r http://127.0.0.1:8096 --proxy-redirect
```

开启后，`/backstream/...` 只允许访问当前配置里的后端协议、主机和端口。除非确认后端需要，否则建议保持默认关闭。

## CLI 管理

列出本脚本创建的配置：

```bash
emby --list
```

列表只显示带托管 marker 的 Emby 配置，TLS 配置会显示证书剩余天数。

运行健康检查：

```bash
emby --doctor
```

`--doctor` 会检查 Nginx 语法、托管配置、证书状态、前端可达性和近期 Nginx 错误日志。

删除托管配置：

```bash
emby --remove https://emby.example.com --yes
```

非交互删除必须加 `--yes`。脚本只会删除带 marker 的托管配置。

常用环境变量：

| 变量 | 作用 |
| --- | --- |
| `NGINX_CONF_DIR` | 覆盖托管 Nginx 配置目录，默认 `/etc/nginx/conf.d`。 |
| `NGINX_MAIN_CONF` | 覆盖要检查的 Nginx 主配置，默认 `/etc/nginx/nginx.conf`。 |
| `ACME_HTTP_WEBROOT` | 覆盖 HTTP-01 webroot，默认 `/usr/share/nginx/html`。 |
| `ACME_INSTALL_SHA256` | 可选的 `acme.sh` 安装脚本 SHA256。 |
| `NRE_ALLOW_REMOTE_TEMPLATE=1` | 允许使用远程 `--template-domain-config` URL；默认禁止远程模板。 |
| `NRE_INSTALL_NGINX=1` | 允许脚本在缺少 Nginx 时安装 Nginx。默认关闭，因为这可能修改系统软件源。 |
| `NRE_LOCK_DIR` | 覆盖部署/删除锁目录，默认 `/run/lock/emby-nginx-manager.lockdir`。 |

## WebUI

启动本地 WebUI：

```bash
emby web
```

前台 WebUI 默认监听 `127.0.0.1:8765`，启动时会在终端打印一次性访问地址。WebUI 可以列出配置、运行健康检查、预览配置、确认写入、确认删除、备份和恢复。

指定监听地址和端口：

```bash
emby web --host 127.0.0.1 --port 8765
```

安装并管理 systemd 后台服务：

```bash
emby web-install
emby web-status
emby web-restart
emby web-logs
```

`web-install` 会写入 `/etc/systemd/system/emby-nginx-webui.service`，首次创建 `/etc/emby-nginx-webui.env`，启用并重启服务。服务默认监听 `127.0.0.1:8765`，不会把内部访问密钥放到 URL 里，并启用较保守的 systemd 沙箱配置，包括 `PrivateTmp`、`ProtectHome`、内核/控制组保护和相关限制。

通过 Nginx 发布 WebUI：

```bash
emby web-proxy-install emby.example.com
```

`web-proxy-install` 会生成托管的 WebUI 反代配置，复用或创建 `/etc/nginx/.htpasswd-emby-webui`，通过 `/etc/nginx/snippets/emby-webui-internal-key.conf` 注入内部 `X-Emby-Webui-Key`，测试 Nginx 后重载。它要求已有证书位于 `/etc/nginx/ssl/<domain>/fullchain.pem` 或 `/etc/nginx/certs/<domain>/cert`。如果目标配置已存在且不是本命令托管的配置，需要确认后加 `--force`。Basic Auth 文件默认使用 `0640` 权限。

首次成功打开 WebUI 后，访问码会写入 HttpOnly cookie，并从地址栏移除。如果 WebUI 监听非本机地址，例如 `0.0.0.0`，必须启用访问码。公网发布时，请保留 Nginx Basic Auth，并通过私有 header 注入内部访问密钥。会修改状态的 WebUI API 请求必须是同源请求、带内部密钥 header，或带 WebUI 前端请求 header。

WebUI 环境变量：

| 变量 | 作用 |
| --- | --- |
| `EMBY_WEBUI_HOST` | 监听地址，默认 `127.0.0.1`。 |
| `EMBY_WEBUI_PORT` | 监听端口，默认 `8765`。 |
| `EMBY_WEBUI_KEY` | WebUI 访问密钥。服务安装会写入 `/etc/emby-nginx-webui.env`。 |
| `EMBY_WEBUI_BACKUP_KEEP` | 保留的备份数量，默认 `20`。 |
| `EMBY_WEBUI_BACKUP_DIR` | 备份目录，默认 `/var/backups/emby-nginx-manager`。 |
| `EMBY_WEBUI_HISTORY_FILE` | 操作历史文件，默认位于 `/var/lib/emby-nginx-manager` 下。 |

快速检查 WebUI：

```bash
curl -b cookie.txt http://127.0.0.1:8765/api/status
```

## 备份与恢复

WebUI 会记录最近的预览、部署、删除、健康检查、备份和恢复操作。长耗时操作会串行执行，避免多个浏览器会话同时写 Nginx。

备份默认保存在 `/var/backups/emby-nginx-manager`。备份覆盖：

- 带 marker 的 Emby Nginx 配置。
- WebUI systemd 服务和 WebUI 反代相关文件。
- 托管配置引用的证书文件：`/etc/nginx/certs/<domain>/cert`、`/etc/nginx/certs/<domain>/key`、`/etc/nginx/ssl/<domain>/fullchain.pem`、`/etc/nginx/ssl/<domain>/privkey.pem`。

备份不包含内部 WebUI 访问密钥。恢复前会预览文件列表并校验内容，只有带托管 marker 的 `conf.d/*.conf` 会被恢复；恢复后会执行 `nginx -t`，失败时回滚。备份归档权限为 `600`，其中可能包含 TLS 私钥，请按密钥文件处理。恢复时不会信任归档内的文件权限，而是按路径强制设置权限，例如私钥和内部密钥文件使用 `0600`。

## SSH 快捷命令

安装器会创建快捷命令：

```bash
emby
```

从克隆目录手动安装快捷命令：

```bash
install -m 755 bin/emby /usr/local/bin/emby
```

参数会原样传给管理脚本：

```bash
emby --list
emby --doctor
emby web
emby web-install
emby web-status
emby web-proxy-install emby.example.com
emby --dry-run -y https://emby.example.com -r http://127.0.0.1:8096
emby --dry-run -y https://emby.example.com -r http://127.0.0.1:8096 --proxy-redirect
```

## 托管配置 Marker

生成的 Nginx 配置包含：

```nginx
# managed_by=nginx-reverse-emby-deploy
# nre_emby_managed=true
```

菜单和 `--list` 只显示带 marker 的配置，避免误管理其他站点。

## 安全访问日志

托管配置会把访问日志写到：

```text
/var/log/nginx/emby-nginx-manager-access.log
```

脚本还会在 Nginx `conf.d` 下安装托管的 `nre_emby_safe` 日志格式。它记录不带 query string 的请求路径，并且不记录 Referer，减少敏感信息进入访问日志。

## 安全注意事项

- WebUI 服务会执行有权限的 Nginx 操作。除非通过 HTTPS、Basic Auth 和内部 `X-Emby-Webui-Key` 保护，否则请保持监听 `127.0.0.1`。
- 重定向代理默认关闭。只有后端确实需要时才启用 `--proxy-redirect`。
- 远程 Nginx 模板默认禁止，因为模板会被渲染成线上 Nginx 配置。
- 恢复功能只接受白名单路径，并要求 Nginx 配置文件带有本项目托管 marker。
- 默认不会自动安装 Nginx。只有确认允许脚本修改软件源时，才设置 `NRE_INSTALL_NGINX=1`。
- 安装器可以从 `main` 下载代码；生产环境请固定 tag/commit 并使用 checksum。
- 备份归档可能包含 TLS 私钥，应按密钥文件存储和传输。

## 开发与测试

运行本地检查：

```bash
scripts/self-check.sh
```

检查内容包括 `webui.py` 编译、Python 单元测试、Shell 语法检查，以及使用临时 Nginx 配置的 dry-run 渲染测试。

GitHub Actions 会在 push 和 pull request 时运行同一套检查。

## 文件说明

- `deploy.sh`: 主管理脚本。
- `install.sh`: 一键安装/更新脚本。
- `webui.py`: 本地 WebUI 服务。
- `conf.d/p.example.com.conf`: HTTPS Emby 反代模板。
- `conf.d/p.example.com.no_tls.conf`: HTTP-only Emby 反代模板。
- `bin/emby`: 快捷命令包装脚本。
- `scripts/self-check.sh`: 本地验证入口。
- `tests/`: 单元测试和 dry-run 测试。
