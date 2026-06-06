#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

CONF_DIR="$TMP_DIR/conf.d"
MAIN_CONF="$TMP_DIR/nginx.conf"
FAKE_BIN="$TMP_DIR/bin"
mkdir -p "$CONF_DIR"
mkdir -p "$FAKE_BIN"
cat > "$MAIN_CONF" <<EOF
events {}
http {
    include $CONF_DIR/*.conf;
}
EOF

cat > "$FAKE_BIN/nginx" <<'EOF'
#!/bin/sh
case "${1:-}" in
    -t|-s)
        exit 0
        ;;
esac
echo "unexpected nginx invocation: $*" >&2
exit 1
EOF
cat > "$FAKE_BIN/pgrep" <<'EOF'
#!/bin/sh
exit 0
EOF
cat > "$FAKE_BIN/ss" <<'EOF'
#!/bin/sh
exit 1
EOF
chmod 755 "$FAKE_BIN/nginx" "$FAKE_BIN/pgrep" "$FAKE_BIN/ss"

run_dry() {
    NGINX_MAIN_CONF="$MAIN_CONF" NGINX_CONF_DIR="$CONF_DIR" "$ROOT/deploy.sh" --dry-run "$@" 2>/dev/null
}

run_fake_deploy() {
    PATH="$FAKE_BIN:$PATH" NGINX_MAIN_CONF="$MAIN_CONF" NGINX_CONF_DIR="$CONF_DIR" "$ROOT/deploy.sh" "$@"
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
if run_dry -y 'https://emby.example.com/path?token=abc' -r http://127.0.0.1:8096 >/dev/null 2>&1; then
    echo "frontend URL query was accepted" >&2
    exit 1
fi
if run_dry -y https://emby.example.com -r 'http://127.0.0.1:8096/path?token=abc' >/dev/null 2>&1; then
    echo "backend URL query was accepted" >&2
    exit 1
fi
run_dry -y https://emby.example.com -r 'http://[::1]:8096' >/dev/null
if run_dry -y https://emby.example.com -r 'http://[::::]:8096' >/dev/null 2>&1; then
    echo "invalid IPv6 backend was accepted" >&2
    exit 1
fi
touch "$TMP_DIR/outside.conf"
ln -s "$TMP_DIR/outside.conf" "$CONF_DIR/symlink.example.com-443.conf"
if run_dry -y https://symlink.example.com -r http://127.0.0.1:8096 >/dev/null 2>&1; then
    echo "symlink config target was accepted" >&2
    exit 1
fi

touch "$TMP_DIR/support-outside.conf"
ln -s "$TMP_DIR/support-outside.conf" "$CONF_DIR/00-nre-emby-log-format.conf"
if run_fake_deploy -y http://support-symlink.example.com -r http://127.0.0.1:8096 >/dev/null 2>"$TMP_DIR/output"; then
    echo "symlink support config target was accepted" >&2
    exit 1
fi
grep -q '拒绝写入非普通 Nginx 配置文件' "$TMP_DIR/output"
rm -f "$CONF_DIR/00-nre-emby-log-format.conf"

http_output=$(run_dry -y http://emby.example.com -r http://127.0.0.1:8096)
printf '%s\n' "$http_output" | grep -Fq 'Block direct Emby web UI entry on HTTP-only frontends.'
printf '%s\n' "$http_output" | grep -Fq 'location ~ ^/(?:$|web(?:/.*)?)$'

http_path_output=$(run_dry -y http://emby.example.com/emby -r http://127.0.0.1:8096/base)
printf '%s\n' "$http_path_output" | grep -Fq 'location ~ ^/emby(?:$|/web(?:/.*)?)$'
printf '%s\n' "$http_path_output" | grep -Fq 'rewrite ^/emby(?:/(.*))?$ /base/$1 break;'
