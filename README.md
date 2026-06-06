# Emby Nginx Manager

Host-mode Emby reverse proxy management script for an existing Nginx installation.

## Quick Start

Install or update:

```bash
(
  set -e
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  curl -fsSL https://github.com/buglyz/emby-nginx-manager/archive/refs/heads/main.tar.gz | tar -xz -C "$tmp"
  bash "$tmp"/emby-nginx-manager-main/install.sh
)
```

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

The scheme can be omitted for common cases:

```bash
emby -y emby.example.com -r 127.0.0.1:8096
emby -y emby.example.com -r a.example.com
emby -y emby.example.com:80 -r 127.0.0.1:8096
```

When the scheme is omitted, public names default to HTTPS, frontend port `80` defaults to HTTP, and local Emby ports such as `8096` default to HTTP.

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

Start the local WebUI:

```bash
emby web
```

The WebUI defaults to `127.0.0.1:8765` and prints a one-time access URL in the terminal. It can list managed configs, run `--doctor`, preview a new config, write a confirmed config, and remove a confirmed config.

To use a different bind address or port:

```bash
emby web --host 127.0.0.1 --port 8765
```

The first successful WebUI page load stores the access code in an HttpOnly browser cookie and removes it from the address bar. If you bind WebUI to a non-local address such as `0.0.0.0`, authentication must stay enabled. When publishing the WebUI behind Nginx, keep Nginx authentication enabled and inject a private `X-Emby-Webui-Key` header to the local WebUI service.

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
emby --dry-run -y https://emby.example.com -r http://127.0.0.1:8096
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

## Files

- `deploy.sh`: main management script
- `install.sh`: one-command installer/updater
- `webui.py`: local WebUI server
- `conf.d/p.example.com.conf`: HTTPS Emby proxy template
- `conf.d/p.example.com.no_tls.conf`: HTTP-only Emby proxy template
- `bin/emby`: optional shortcut wrapper
