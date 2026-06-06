#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP_DIR=$(mktemp -d)
CERT_DOMAIN="wrapper-test.invalid"
SSL_DIR="/etc/nginx/ssl/$CERT_DOMAIN"
SSL_CREATED="no"

cleanup() {
    rm -rf "$TMP_DIR"
    if [ "$SSL_CREATED" = "yes" ]; then
        rm -rf "$SSL_DIR"
    fi
}

trap cleanup EXIT

FAKE_BIN="$TMP_DIR/bin"
mkdir -p "$FAKE_BIN"
cat > "$FAKE_BIN/systemctl" <<'EOF'
#!/bin/sh
echo "systemctl should not be called for invalid service names" >&2
exit 1
EOF
cat > "$FAKE_BIN/nginx" <<'EOF'
#!/bin/sh
case "${1:-}" in
    -t)
        exit 0
        ;;
    -s)
        exit 0
        ;;
esac
echo "unexpected nginx invocation: $*" >&2
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

if PATH="$FAKE_BIN:$PATH" NGINX_CONF_DIR='/tmp/bad path' sh "$ROOT/bin/emby" web-proxy-install web.example.com >/dev/null 2>"$TMP_DIR/output"; then
    echo "invalid nginx conf dir was accepted" >&2
    exit 1
fi
grep -q 'Nginx 配置目录 路径包含不支持的字符' "$TMP_DIR/output"

ENV_FILE="$TMP_DIR/webui.env"
printf 'EMBY_WEBUI_KEY=abcdefgh\n' > "$ENV_FILE"
if PATH="$FAKE_BIN:$PATH" EMBY_NGINX_MANAGER_WEBUI_ENV="$ENV_FILE" EMBY_NGINX_MANAGER_WEBUI_HTPASSWD="$TMP_DIR/htpasswd" sh "$ROOT/bin/emby" web-proxy-install web.example.com --password-file "$TMP_DIR/missing-password" >/dev/null 2>"$TMP_DIR/output"; then
    echo "missing password file was accepted" >&2
    exit 1
fi
grep -q '密码文件不存在或不是普通文件' "$TMP_DIR/output"

REAL_PASSWORD="$TMP_DIR/password"
LINK_PASSWORD="$TMP_DIR/link-password"
printf 'secret\n' > "$REAL_PASSWORD"
ln -s "$REAL_PASSWORD" "$LINK_PASSWORD"
if PATH="$FAKE_BIN:$PATH" EMBY_NGINX_MANAGER_WEBUI_ENV="$ENV_FILE" EMBY_NGINX_MANAGER_WEBUI_HTPASSWD="$TMP_DIR/htpasswd" sh "$ROOT/bin/emby" web-proxy-install web.example.com --password-file "$LINK_PASSWORD" >/dev/null 2>"$TMP_DIR/output"; then
    echo "symlink password file was accepted" >&2
    exit 1
fi
grep -q '密码文件不能是符号链接' "$TMP_DIR/output"

if [ -e "$SSL_DIR" ]; then
    echo "test certificate directory already exists: $SSL_DIR" >&2
    exit 1
fi
mkdir -p "$SSL_DIR"
SSL_CREATED="yes"
touch "$SSL_DIR/fullchain.pem" "$SSL_DIR/privkey.pem"
CONF_DIR="$TMP_DIR/conf.d"
SNIPPET_DIR="$TMP_DIR/snippets"
mkdir -p "$CONF_DIR" "$SNIPPET_DIR"

REAL_HTPASSWD="$TMP_DIR/real-htpasswd"
LINK_HTPASSWD="$TMP_DIR/link-htpasswd"
touch "$REAL_HTPASSWD"
ln -s "$REAL_HTPASSWD" "$LINK_HTPASSWD"
if PATH="$FAKE_BIN:$PATH" NGINX_CONF_DIR="$CONF_DIR" EMBY_NGINX_MANAGER_WEBUI_ENV="$ENV_FILE" EMBY_NGINX_MANAGER_WEBUI_HTPASSWD="$LINK_HTPASSWD" EMBY_NGINX_MANAGER_WEBUI_KEY_SNIPPET="$SNIPPET_DIR/key.conf" EMBY_WEBUI_BASIC_PASSWORD=secret sh "$ROOT/bin/emby" web-proxy-install "$CERT_DOMAIN" >/dev/null 2>"$TMP_DIR/output"; then
    echo "symlink htpasswd target was accepted" >&2
    exit 1
fi
grep -q 'Basic Auth 文件 不能是符号链接' "$TMP_DIR/output"

REAL_SNIPPET="$TMP_DIR/real-snippet"
LINK_SNIPPET="$SNIPPET_DIR/key.conf"
touch "$REAL_SNIPPET"
ln -s "$REAL_SNIPPET" "$LINK_SNIPPET"
if PATH="$FAKE_BIN:$PATH" NGINX_CONF_DIR="$CONF_DIR" EMBY_NGINX_MANAGER_WEBUI_ENV="$ENV_FILE" EMBY_NGINX_MANAGER_WEBUI_HTPASSWD="$TMP_DIR/new-htpasswd" EMBY_NGINX_MANAGER_WEBUI_KEY_SNIPPET="$LINK_SNIPPET" EMBY_WEBUI_BASIC_PASSWORD=secret sh "$ROOT/bin/emby" web-proxy-install "$CERT_DOMAIN" >/dev/null 2>"$TMP_DIR/output"; then
    echo "symlink key snippet target was accepted" >&2
    exit 1
fi
grep -q '内部密钥 snippet 不能是符号链接' "$TMP_DIR/output"

REAL_CONF="$TMP_DIR/real.conf"
LINK_CONF="$CONF_DIR/$CERT_DOMAIN-443.conf"
touch "$REAL_CONF"
ln -s "$REAL_CONF" "$LINK_CONF"
rm -f "$LINK_SNIPPET"
if PATH="$FAKE_BIN:$PATH" NGINX_CONF_DIR="$CONF_DIR" EMBY_NGINX_MANAGER_WEBUI_ENV="$ENV_FILE" EMBY_NGINX_MANAGER_WEBUI_HTPASSWD="$TMP_DIR/new-htpasswd" EMBY_NGINX_MANAGER_WEBUI_KEY_SNIPPET="$SNIPPET_DIR/key.conf" EMBY_WEBUI_BASIC_PASSWORD=secret sh "$ROOT/bin/emby" web-proxy-install "$CERT_DOMAIN" >/dev/null 2>"$TMP_DIR/output"; then
    echo "symlink webui nginx config target was accepted" >&2
    exit 1
fi
grep -q 'WebUI Nginx 配置文件 不能是符号链接' "$TMP_DIR/output"
