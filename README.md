# Emby Nginx Manager

Host-mode Emby reverse proxy management script for an existing Nginx installation.

中文文档: [README.zh-CN.md](README.zh-CN.md)

## Quick Start

Install or update from the current `main` branch:

```bash
(
  set -e
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  curl -fsSL https://github.com/buglyz/emby-nginx-manager/archive/refs/heads/main.tar.gz | tar -xz -C "$tmp"
  bash "$tmp"/emby-nginx-manager-main/install.sh
)
```

For production use, prefer a pinned archive URL and optional checksum instead of tracking `main`. When `install.sh` is run outside a full checkout and downloads an archive, it honors these variables:

```bash
ARCHIVE_URL=https://github.com/buglyz/emby-nginx-manager/archive/<commit-or-tag>.tar.gz \
ARCHIVE_SHA256=<sha256>
```

The installer writes the project to `/opt/emby-nginx-manager` and installs the `emby` shortcut to `/usr/local/bin/emby` by default.

Run the menu:

```bash
emby
```

Preview a config without writing files, applying certificates, or reloading Nginx:

```bash
emby -y https://emby.example.com -r http://127.0.0.1:8096 --dry-run
```

Add a reverse proxy config:

```bash
emby -y https://emby.example.com -r http://127.0.0.1:8096
```

302/307 redirect proxying is disabled by default. If you explicitly need Emby upstream redirects to be proxied through the public domain, enable it:

```bash
emby -y https://emby.example.com -r http://127.0.0.1:8096 --proxy-redirect
```

When enabled, `/backstream/...` is restricted to the configured backend scheme, host, and port. Keep it disabled unless you know the backend requires it.

The scheme can be omitted for common cases:

```bash
emby -y emby.example.com -r 127.0.0.1:8096
emby -y emby.example.com -r a.example.com
emby -y emby.example.com:80 -r 127.0.0.1:8096
```

When the scheme is omitted, public names default to HTTPS, frontend port `80` defaults to HTTP, and local Emby ports such as `8096` default to HTTP.

## CLI

List configs created by this script:

```bash
emby --list
```

The list only shows managed Emby configs and includes certificate remaining days when TLS is enabled.

Run a health check:

```bash
emby --doctor
```

`--doctor` checks Nginx syntax, managed configs, certificate status, frontend reachability, and recent Nginx error logs.

Remove a managed config:

```bash
emby --remove https://emby.example.com --yes
```

Non-interactive remove requires `--yes`. The script only removes managed configs that contain its marker.

Useful environment variables:

| Variable | Purpose |
| --- | --- |
| `NGINX_CONF_DIR` | Override the managed Nginx config directory. Defaults to `/etc/nginx/conf.d`. |
| `NGINX_MAIN_CONF` | Override the main Nginx config checked for `conf.d/*.conf` includes. Defaults to `/etc/nginx/nginx.conf`. |
| `ACME_HTTP_WEBROOT` | Override the HTTP-01 webroot. Defaults to `/usr/share/nginx/html`. |
| `ACME_INSTALL_SHA256` | Optional SHA256 for the downloaded `acme.sh` installer. |
| `NRE_ALLOW_REMOTE_TEMPLATE=1` | Allow a remote `--template-domain-config` URL. Remote templates are blocked by default. |
| `NRE_LOCK_DIR` | Override the deploy/remove lock directory. Defaults to `/tmp/emby-nginx-manager.lockdir`. |

## WebUI

Start the local WebUI:

```bash
emby web
```

The foreground WebUI defaults to `127.0.0.1:8765` and prints a one-time access URL in the terminal. It can list managed configs, run `--doctor`, preview a new config, write a confirmed config, and remove a confirmed config.

To use a different bind address or port:

```bash
emby web --host 127.0.0.1 --port 8765
```

Install and manage the WebUI as a systemd service:

```bash
emby web-install
emby web-status
emby web-restart
emby web-logs
```

`web-install` writes `/etc/systemd/system/emby-nginx-webui.service`, creates `/etc/emby-nginx-webui.env` when missing, enables the service, and restarts it. The service listens on `127.0.0.1:8765` by default and keeps the internal access key out of the URL.

Publish the WebUI through Nginx:

```bash
emby web-proxy-install emby.example.com
```

`web-proxy-install` generates a managed Nginx reverse proxy for the local WebUI, keeps or creates `/etc/nginx/.htpasswd-emby-webui`, injects the private WebUI key through `/etc/nginx/snippets/emby-webui-internal-key.conf`, tests Nginx, and reloads it. It requires an existing certificate at `/etc/nginx/ssl/<domain>/fullchain.pem` or `/etc/nginx/certs/<domain>/cert`. If the target Nginx config already exists and is not managed by this command, add `--force` after checking the existing file.

The first successful WebUI page load stores the access code in an HttpOnly browser cookie and removes it from the address bar. If you bind WebUI to a non-local address such as `0.0.0.0`, authentication must stay enabled. When publishing the WebUI behind Nginx, keep Nginx authentication enabled and inject a private `X-Emby-Webui-Key` header to the local WebUI service.

WebUI environment variables:

| Variable | Purpose |
| --- | --- |
| `EMBY_WEBUI_HOST` | Bind address. Defaults to `127.0.0.1`. |
| `EMBY_WEBUI_PORT` | Bind port. Defaults to `8765`. |
| `EMBY_WEBUI_KEY` | WebUI access key. Service install creates this in `/etc/emby-nginx-webui.env`. |
| `EMBY_WEBUI_BACKUP_KEEP` | Number of backup archives to keep. Defaults to `20`. |
| `EMBY_WEBUI_BACKUP_DIR` | Backup directory. Defaults to `/var/backups/emby-nginx-manager`. |
| `EMBY_WEBUI_HISTORY_FILE` | Operation history file. Defaults under `/var/lib/emby-nginx-manager`. |

The WebUI records recent preview, deploy, remove, doctor, backup, and restore operations. Long-running operations are serialized so multiple browser sessions cannot write Nginx at the same time. Backups are stored under `/var/backups/emby-nginx-manager` and cover managed Emby Nginx configs plus WebUI service/proxy files. Backups do not include the internal WebUI access key. Restore actions preview the file list before applying changes, and old backups are pruned after the newest 20 by default. Set `EMBY_WEBUI_BACKUP_KEEP` to change the retention count.

Backups also include certificate files referenced from managed configs when they are under `/etc/nginx/certs/<domain>/cert`, `/etc/nginx/certs/<domain>/key`, `/etc/nginx/ssl/<domain>/fullchain.pem`, or `/etc/nginx/ssl/<domain>/privkey.pem`. Backup archives are mode `600`; protect them because they may contain TLS private keys.

Quick WebUI self-check:

```bash
curl -b cookie.txt http://127.0.0.1:8765/api/status
```

## SSH Shortcut

The installer creates the shortcut command:

```bash
emby
```

Manual shortcut install from a cloned checkout:

```bash
install -m 755 bin/emby /usr/local/bin/emby
```

Arguments are passed through:

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

## Managed Config Marker

Generated Nginx config files include:

```nginx
# managed_by=nginx-reverse-emby-deploy
# nre_emby_managed=true
```

The menu and `--list` only show configs with this marker, so unrelated Nginx sites are not managed accidentally.

## Safe Access Logs

Managed configs write access logs to:

```text
/var/log/nginx/emby-nginx-manager-access.log
```

The script also installs a managed `nre_emby_safe` log format under Nginx `conf.d`. It logs the request path without query strings and does not log Referer, reducing sensitive data in access logs.

## Safety Notes

- The WebUI service performs privileged Nginx operations. Keep it bound to `127.0.0.1` unless it is protected by HTTPS, Basic Auth, and the internal `X-Emby-Webui-Key` header.
- Redirect proxying is disabled by default. Only enable `--proxy-redirect` when the backend requires it.
- Remote Nginx templates are blocked by default because templates are rendered into live Nginx config.
- The installer can download from `main`; use pinned archives and checksums for production hosts.
- Backup archives can include TLS private keys. Store and transfer them as secrets.

## Development

Run the local checks:

```bash
scripts/self-check.sh
```

The self-check compiles `webui.py`, runs Python unit tests, validates shell syntax, and performs dry-run render tests with a temporary Nginx config.

GitHub Actions runs the same check on push and pull request.

## Files

- `deploy.sh`: main management script
- `install.sh`: one-command installer/updater
- `webui.py`: local WebUI server
- `conf.d/p.example.com.conf`: HTTPS Emby proxy template
- `conf.d/p.example.com.no_tls.conf`: HTTP-only Emby proxy template
- `bin/emby`: optional shortcut wrapper
- `scripts/self-check.sh`: local validation entrypoint
- `tests/`: unit and dry-run tests
