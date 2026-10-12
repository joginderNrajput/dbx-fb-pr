#!/usr/bin/env bash
# Build the one-file binary for THIS OS (PyInstaller cannot cross-compile), then smoke-test
# the BUILT binary: version, catalog check, and a discovery of tests/fixtures/mini whose
# workbook is verified by packaging/verify_workbook.py.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python}"

"$PYTHON" -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller \
    packaging/dbx_premig.spec

BIN="dist/dbx-discovery"
[ -x "$BIN" ] || { echo "binary not found: $BIN" >&2; exit 1; }
SMOKE="build/smoke"
rm -rf "$SMOKE" && mkdir -p "$SMOKE"

"$BIN" version
"$BIN" catalog-info
"$BIN" discover --input tests/fixtures/mini/snapshot.json --out "$SMOKE" --name live.xlsx
"$BIN" discover --input tests/fixtures/mini/notebooks --out "$SMOKE" --name offline.xlsx
"$PYTHON" packaging/verify_workbook.py "$SMOKE/live.xlsx" --min-assets 40
"$PYTHON" packaging/verify_workbook.py "$SMOKE/offline.xlsx" --min-assets 5
echo "OK: $BIN ($(du -h "$BIN" | cut -f1))"
