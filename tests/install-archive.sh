#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

ARCHIVE="$TMP_DIR/bad.tar.gz"
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

FAKE_BIN="$TMP_DIR/bin"
mkdir -p "$FAKE_BIN"
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

RUNNER="$TMP_DIR/runner"
mkdir -p "$RUNNER"
cp "$ROOT/install.sh" "$RUNNER/install.sh"

if PATH="$FAKE_BIN:$PATH" ARCHIVE_URL=https://example.invalid/bad.tar.gz INSTALL_DIR="$TMP_DIR/install" BIN_DIR="$TMP_DIR/bin-out" sh "$RUNNER/install.sh" >/dev/null 2>"$TMP_DIR/output"; then
    echo "unsafe archive was accepted" >&2
    exit 1
fi

grep -q '归档包含不安全路径' "$TMP_DIR/output"
