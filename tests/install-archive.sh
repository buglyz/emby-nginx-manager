#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

FAKE_BIN="$TMP_DIR/bin"
mkdir -p "$FAKE_BIN"

RUNNER="$TMP_DIR/runner"
mkdir -p "$RUNNER"
cp "$ROOT/install.sh" "$RUNNER/install.sh"

ARCHIVE="$TMP_DIR/current.tar.gz"
cat > "$FAKE_BIN/curl" <<EOF
#!/bin/sh
while [ "\$#" -gt 0 ]; do
    if [ "\$1" = "-o" ]; then
        shift
        cp "$ARCHIVE" "\$1"
        exit 0
    fi
    shift
done
exit 1
EOF
chmod 755 "$FAKE_BIN/curl"

run_bad_archive() {
    expected="$1"
    if PATH="$FAKE_BIN:$PATH" ARCHIVE_URL=https://example.invalid/bad.tar.gz INSTALL_DIR="$TMP_DIR/install" BIN_DIR="$TMP_DIR/bin-out" sh "$RUNNER/install.sh" >/dev/null 2>"$TMP_DIR/output"; then
        echo "unsafe archive was accepted" >&2
        exit 1
    fi

    grep -q "$expected" "$TMP_DIR/output"
}

python3 - "$ARCHIVE" <<'PY'
import io
import sys
import tarfile

with tarfile.open(sys.argv[1], "w:gz") as tar:
    payload = b"x\n"
    info = tarfile.TarInfo("../escape")
    info.size = len(payload)
    tar.addfile(info, io.BytesIO(payload))
PY
run_bad_archive '归档包含不安全路径'

python3 - "$ARCHIVE" <<'PY'
import sys
import tarfile

with tarfile.open(sys.argv[1], "w:gz") as tar:
    info = tarfile.TarInfo("root/link")
    info.type = tarfile.SYMTYPE
    info.linkname = "/etc/passwd"
    tar.addfile(info)
PY
run_bad_archive '归档包含不支持的特殊文件类型'

LOCAL_SRC="$TMP_DIR/local-src"
mkdir -p "$LOCAL_SRC/bin" "$LOCAL_SRC/conf.d"
cp "$ROOT/install.sh" "$LOCAL_SRC/install.sh"
touch "$LOCAL_SRC/webui.py" "$LOCAL_SRC/README.md" "$LOCAL_SRC/bin/emby"
touch "$LOCAL_SRC/conf.d/p.example.com.conf" "$LOCAL_SRC/conf.d/p.example.com.no_tls.conf"
touch "$TMP_DIR/deploy-target"
ln -s "$TMP_DIR/deploy-target" "$LOCAL_SRC/deploy.sh"
if PATH="$FAKE_BIN:$PATH" INSTALL_DIR="$TMP_DIR/install" BIN_DIR="$TMP_DIR/bin-out" sh "$LOCAL_SRC/install.sh" >/dev/null 2>"$TMP_DIR/output"; then
    echo "symlink local source was accepted" >&2
    exit 1
fi
grep -q '安装源包含符号链接或非普通文件' "$TMP_DIR/output"
