#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

FAKE_BIN="$TMP_DIR/bin"
mkdir -p "$FAKE_BIN"
cat > "$FAKE_BIN/systemctl" <<'EOF'
#!/bin/sh
echo "systemctl should not be called for invalid service names" >&2
exit 1
EOF
cat > "$FAKE_BIN/nginx" <<'EOF'
#!/bin/sh
echo "nginx should not be called for invalid config paths" >&2
exit 1
EOF
cat > "$FAKE_BIN/python3" <<'EOF'
#!/bin/sh
exit 0
EOF
chmod 755 "$FAKE_BIN/systemctl"
chmod 755 "$FAKE_BIN/nginx" "$FAKE_BIN/python3"

if PATH="$FAKE_BIN:$PATH" EMBY_NGINX_MANAGER_WEBUI_SERVICE='../bad.service' sh "$ROOT/bin/emby" web-status >/dev/null 2>"$TMP_DIR/output"; then
    echo "invalid service name was accepted" >&2
    exit 1
fi
grep -q '服务名格式无效' "$TMP_DIR/output"

if PATH="$FAKE_BIN:$PATH" EMBY_NGINX_MANAGER_WEBUI_SERVICE='bad' sh "$ROOT/bin/emby" web-status >/dev/null 2>"$TMP_DIR/output"; then
    echo "service name without suffix was accepted" >&2
    exit 1
fi
grep -q '必须以 .service 结尾' "$TMP_DIR/output"

if PATH="$FAKE_BIN:$PATH" EMBY_NGINX_MANAGER_WEBUI_HTPASSWD='/tmp/bad path' sh "$ROOT/bin/emby" web-proxy-install web.example.com >/dev/null 2>"$TMP_DIR/output"; then
    echo "invalid htpasswd path was accepted" >&2
    exit 1
fi
grep -q 'Basic Auth 文件 路径包含不支持的字符' "$TMP_DIR/output"
