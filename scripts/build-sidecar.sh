#!/bin/sh
# Exécutable autonome du connecteur (PyInstaller) pour l'application de bureau Tauri.
# Usage : scripts/build-sidecar.sh <triplet-cible>   (ex. x86_64-unknown-linux-gnu)
# Résultat : desktop/src-tauri/binaries/finz-local-connector-<triplet>[.exe]
set -eu
TRIPLE=$1
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
[ -d vendor/woob-modules ] || sh scripts/fetch-modules.sh
PYTHON=${PYTHON:-.venv/bin/python}

"$PYTHON" -m PyInstaller --noconfirm --clean --onefile \
  --name finz-local-connector \
  --distpath build/sidecar --workpath build/pyinstaller --specpath build \
  --add-data "$ROOT/vendor/woob-modules:woob-modules" \
  --collect-all woob \
  --collect-submodules keyring --copy-metadata keyring \
  --collect-data pycountry --collect-data schwifty --collect-data babel \
  packaging/entry.py

EXT=""
case "$TRIPLE" in *windows*) EXT=".exe" ;; esac
mkdir -p desktop/src-tauri/binaries
cp "build/sidecar/finz-local-connector$EXT" "desktop/src-tauri/binaries/finz-local-connector-$TRIPLE$EXT"
echo "desktop/src-tauri/binaries/finz-local-connector-$TRIPLE$EXT"
