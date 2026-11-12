#!/bin/sh
# Modules bancaires de woob au commit figé (le même que le paquet woob de pyproject.toml), avec nos correctifs (patches/).
# Usage : scripts/fetch-modules.sh [dossier]   (défaut : vendor/woob-modules)
set -eu
# Le tag 3.7 date d'octobre 2024 : ses modules ne suivent plus les sites des banques.
WOOB_VERSION=70ac33dc5b2b399b498415e009121cbe9d426692
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
