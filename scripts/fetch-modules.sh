#!/bin/sh
# Modules bancaires de woob à la version figée, avec nos correctifs (patches/).
# Usage : scripts/fetch-modules.sh [dossier]   (défaut : vendor/woob-modules)
set -eu
WOOB_VERSION=3.7
DEST=${1:-vendor/woob-modules}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

curl -fsSL "https://gitlab.com/woob/woob/-/archive/${WOOB_VERSION}/woob-${WOOB_VERSION}.tar.gz?path=modules" \
  -o "$TMP/modules.tar.gz"
tar -xzf "$TMP/modules.tar.gz" -C "$TMP"
SRC="$TMP/woob-${WOOB_VERSION}-modules"
for patch in "$ROOT"/patches/*.patch; do
  [ -e "$patch" ] || continue
  (cd "$SRC" && patch -p1 --forward --quiet < "$patch")
done
rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")"
mv "$SRC/modules" "$DEST"
echo "modules woob ${WOOB_VERSION} dans $DEST"
