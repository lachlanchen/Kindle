#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
downloads="$project_root/downloads"
packages="$project_root/packages"
staging="$project_root/staging"

require_file() {
  local file="$1"
  [[ -f "$file" ]] || {
    printf 'Missing required file: %s\n' "$file" >&2
    exit 1
  }
}

require_file "$downloads/wb2.zip"
require_file "$downloads/kual-mrinstaller-khf.zip"
require_file "$downloads/koreader-kindlepw2-v2026.03.zip"
require_file "$downloads/Update_hotfix_universal.bin"
require_file "$downloads/Update_KUALBooklet_HDRepack.bin"

rm -rf \
  "$packages/winterbreak2" \
  "$packages/mrpi" \
  "$packages/koreader-kindlepw2-v2026.03" \
  "$staging/winterbreak2-root" \
  "$staging/post-jailbreak-root"

mkdir -p \
  "$packages/winterbreak2" \
  "$packages/mrpi" \
  "$packages/koreader-kindlepw2-v2026.03" \
  "$staging/winterbreak2-root" \
  "$staging/post-jailbreak-root"

unzip -q -o "$downloads/wb2.zip" -d "$packages/winterbreak2"
unzip -q -o "$downloads/kual-mrinstaller-khf.zip" -d "$packages/mrpi"
unzip -q -o "$downloads/koreader-kindlepw2-v2026.03.zip" -d "$packages/koreader-kindlepw2-v2026.03"

cp -a "$packages/winterbreak2/." "$staging/winterbreak2-root/"

cp -a "$packages/mrpi/extensions" "$staging/post-jailbreak-root/"
cp -a "$packages/mrpi/mrpackages" "$staging/post-jailbreak-root/"
cp -a "$packages/koreader-kindlepw2-v2026.03/extensions/." "$staging/post-jailbreak-root/extensions/"
cp -a "$packages/koreader-kindlepw2-v2026.03/koreader" "$staging/post-jailbreak-root/"
cp "$downloads/Update_hotfix_universal.bin" "$staging/post-jailbreak-root/"
cp "$downloads/Update_KUALBooklet_HDRepack.bin" "$staging/post-jailbreak-root/mrpackages/"

printf 'Built Kindle staging trees:\n'
printf '  %s\n' "$staging/winterbreak2-root"
printf '  %s\n' "$staging/post-jailbreak-root"
