#!/bin/sh
set -eu

ARCHIVE_URL="${ARCHIVE_URL:-https://github.com/buglyz/emby-nginx-manager/archive/refs/heads/main.tar.gz}"
INSTALL_DIR="${INSTALL_DIR:-/opt/emby-nginx-manager}"
BIN_DIR="${BIN_DIR:-/usr/local/bin}"

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" 2>/dev/null && pwd || pwd)
SRC_DIR=""
TMP_DIR=""
SUDO=""

if [ "$(id -u)" -ne 0 ]; then
    if ! command -v sudo >/dev/null 2>&1; then
        echo "安装失败: 请使用 root 运行，或先安装 sudo。" >&2
        exit 1
    fi
    SUDO="sudo"
fi

for cmd in curl tar find install; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "安装失败: 缺少命令 $cmd。" >&2
        exit 1
    fi
done

validate_archive() {
    archive_path="$1"
    if ! tar -tzf "$archive_path" | while IFS= read -r member; do
        case "$member" in
            ""|/*|..|../*|*/..|*/../*)
                echo "安装失败: 归档包含不安全路径: $member" >&2
                exit 1
                ;;
        esac
    done; then
        exit 1
    fi

    if tar -tvzf "$archive_path" | while IFS= read -r line; do
        type_char=${line%"${line#?}"}
        case "$type_char" in
            -|d)
                ;;
            *)
                echo "安装失败: 归档包含不支持的特殊文件类型。" >&2
                exit 1
                ;;
        esac
    done; then
        return 0
    fi
    exit 1
}

cleanup() {
    if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
        rm -rf "$TMP_DIR"
    fi
}
trap cleanup EXIT HUP INT TERM

if [ -f "$SCRIPT_DIR/deploy.sh" ] && \
   [ -f "$SCRIPT_DIR/webui.py" ] && \
   [ -f "$SCRIPT_DIR/install.sh" ] && \
   [ -f "$SCRIPT_DIR/README.md" ] && \
   [ -f "$SCRIPT_DIR/bin/emby" ] && \
   [ -f "$SCRIPT_DIR/conf.d/p.example.com.conf" ] && \
   [ -f "$SCRIPT_DIR/conf.d/p.example.com.no_tls.conf" ]; then
    SRC_DIR="$SCRIPT_DIR"
else
    TMP_DIR=$(mktemp -d)
    archive="$TMP_DIR/source.tar.gz"
    curl -fsSL "$ARCHIVE_URL" -o "$archive"
    if [ -n "${ARCHIVE_SHA256:-}" ]; then
        if ! command -v sha256sum >/dev/null 2>&1; then
            echo "安装失败: 设置了 ARCHIVE_SHA256，但缺少 sha256sum。" >&2
            exit 1
        fi
        printf '%s  %s\n' "$ARCHIVE_SHA256" "$archive" | sha256sum -c - >/dev/null
    fi
    validate_archive "$archive"
    tar -xzf "$archive" -C "$TMP_DIR"
    SRC_DIR=$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1)
fi

if [ -z "$SRC_DIR" ] || \
   [ ! -f "$SRC_DIR/deploy.sh" ] || \
   [ ! -f "$SRC_DIR/webui.py" ] || \
   [ ! -f "$SRC_DIR/install.sh" ] || \
   [ ! -f "$SRC_DIR/README.md" ] || \
   [ ! -f "$SRC_DIR/bin/emby" ] || \
   [ ! -f "$SRC_DIR/conf.d/p.example.com.conf" ] || \
   [ ! -f "$SRC_DIR/conf.d/p.example.com.no_tls.conf" ]; then
    echo "安装失败: 未找到安装文件。" >&2
    exit 1
fi

$SUDO install -d "$INSTALL_DIR/conf.d" "$INSTALL_DIR/bin" "$BIN_DIR"
$SUDO install -m 755 "$SRC_DIR/deploy.sh" "$INSTALL_DIR/deploy.sh"
$SUDO install -m 755 "$SRC_DIR/webui.py" "$INSTALL_DIR/webui.py"
$SUDO install -m 755 "$SRC_DIR/install.sh" "$INSTALL_DIR/install.sh"
$SUDO install -m 644 "$SRC_DIR/README.md" "$INSTALL_DIR/README.md"
$SUDO install -m 644 "$SRC_DIR/conf.d/p.example.com.conf" "$INSTALL_DIR/conf.d/p.example.com.conf"
$SUDO install -m 644 "$SRC_DIR/conf.d/p.example.com.no_tls.conf" "$INSTALL_DIR/conf.d/p.example.com.no_tls.conf"
$SUDO install -m 755 "$SRC_DIR/bin/emby" "$INSTALL_DIR/bin/emby"
$SUDO install -m 755 "$SRC_DIR/bin/emby" "$BIN_DIR/emby"

echo "安装完成。"
echo "运行: emby"
echo "健康检查: emby --doctor"
echo "WebUI: emby web"
echo "安装 WebUI 后台服务: emby web-install"
echo "安装 WebUI 公网反代: emby web-proxy-install <domain>"
