# Emby Nginx Manager

Host-mode Emby reverse proxy management script for an existing Nginx installation.

## Quick Start

Install or update on a root shell:

```bash
tmp=$(mktemp -d) && curl -fsSL https://github.com/buglyz/emby-nginx-manager/archive/refs/heads/main.tar.gz | tar -xz -C "$tmp" && bash "$tmp"/emby-nginx-manager-main/install.sh; rm -rf "$tmp"
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

List configs created by this script:

```bash
emby --list
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
emby --dry-run -y https://emby.example.com -r http://127.0.0.1:8096
```

## Managed Config Marker

Generated Nginx config files include:

```nginx
# managed_by=nginx-reverse-emby-deploy
# nre_emby_managed=true
```

The menu and `--list` only show configs with this marker, so unrelated Nginx sites are not managed accidentally.

## Files

- `deploy.sh`: main management script
- `install.sh`: one-command installer/updater
- `conf.d/p.example.com.conf`: HTTPS Emby proxy template
- `conf.d/p.example.com.no_tls.conf`: HTTP-only Emby proxy template
- `bin/emby`: optional shortcut wrapper
