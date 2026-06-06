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

cleanup() {
    if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
        rm -rf "$TMP_DIR"
    fi
}
trap cleanup EXIT HUP INT TERM

if [ -f "$SCRIPT_DIR/deploy.sh" ] && [ -f "$SCRIPT_DIR/bin/emby" ] && [ -d "$SCRIPT_DIR/conf.d" ]; then
    SRC_DIR="$SCRIPT_DIR"
else
    TMP_DIR=$(mktemp -d)
    curl -fsSL "$ARCHIVE_URL" | tar -xz -C "$TMP_DIR"
    SRC_DIR=$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1)
fi

if [ -z "$SRC_DIR" ] || [ ! -f "$SRC_DIR/deploy.sh" ]; then
    echo "安装失败: 未找到安装文件。" >&2
    exit 1
fi

$SUDO install -d "$INSTALL_DIR/conf.d" "$INSTALL_DIR/bin" "$BIN_DIR"
$SUDO install -m 755 "$SRC_DIR/deploy.sh" "$INSTALL_DIR/deploy.sh"
$SUDO install -m 644 "$SRC_DIR/conf.d/p.example.com.conf" "$INSTALL_DIR/conf.d/p.example.com.conf"
$SUDO install -m 644 "$SRC_DIR/conf.d/p.example.com.no_tls.conf" "$INSTALL_DIR/conf.d/p.example.com.no_tls.conf"
$SUDO install -m 755 "$SRC_DIR/bin/emby" "$INSTALL_DIR/bin/emby"
$SUDO install -m 755 "$SRC_DIR/bin/emby" "$BIN_DIR/emby"

echo "安装完成。"
echo "运行: emby"
echo "健康检查: emby --doctor"
