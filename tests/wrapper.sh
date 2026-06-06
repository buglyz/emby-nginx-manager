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
chmod 755 "$FAKE_BIN/systemctl"

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
