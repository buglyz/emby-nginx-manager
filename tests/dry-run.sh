#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

CONF_DIR="$TMP_DIR/conf.d"
MAIN_CONF="$TMP_DIR/nginx.conf"
mkdir -p "$CONF_DIR"
cat > "$MAIN_CONF" <<EOF
events {}
http {
    include $CONF_DIR/*.conf;
}
EOF

run_dry() {
    NGINX_MAIN_CONF="$MAIN_CONF" NGINX_CONF_DIR="$CONF_DIR" "$ROOT/deploy.sh" --dry-run "$@" 2>/dev/null
}

default_output=$(run_dry -y https://emby.example.com -r http://127.0.0.1:8096)
printf '%s\n' "$default_output" | grep -q 'proxy_redirect disabled'
if printf '%s\n' "$default_output" | grep -q 'location ~ \^/backstream'; then
    echo "default dry-run unexpectedly generated /backstream" >&2
    exit 1
fi

redirect_output=$(run_dry --proxy-redirect -y https://emby.example.com -r http://127.0.0.1:8096)
printf '%s\n' "$redirect_output" | grep -q 'location ~ \^/backstream'
printf '%s\n' "$redirect_output" | grep -Fq 'if ($backstream_scheme != http) { return 403; }'
printf '%s\n' "$redirect_output" | grep -Fq 'if ($backstream_host !~ ^127\.0\.0\.1(?::8096)?$) { return 403; }'

if run_dry -y 'https://bad.example.com;root=/tmp' -r http://127.0.0.1:8096 >/dev/null 2>&1; then
    echo "invalid frontend host was accepted" >&2
    exit 1
fi

http_output=$(run_dry -y http://emby.example.com -r http://127.0.0.1:8096)
printf '%s\n' "$http_output" | grep -Fq 'Block direct Emby web UI entry on HTTP-only frontends.'
printf '%s\n' "$http_output" | grep -Fq 'location ~ ^/(?:$|web(?:/.*)?)$'

http_path_output=$(run_dry -y http://emby.example.com/emby -r http://127.0.0.1:8096/base)
printf '%s\n' "$http_path_output" | grep -Fq 'location ~ ^/emby(?:$|/web(?:/.*)?)$'
printf '%s\n' "$http_path_output" | grep -Fq 'rewrite ^/emby(?:/(.*))?$ /base/$1 break;'
