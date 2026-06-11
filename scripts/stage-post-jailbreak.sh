#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
kindle_root="${1:-}"

if [[ -z "$kindle_root" ]]; then
  kindle_root="$("$project_root/scripts/detect-kindle.sh")"
fi

kindle_root="$(readlink -f "$kindle_root")"
stage_root="$project_root/staging/post-jailbreak-root"

case "$kindle_root" in
  /|/home|/home/lachlan|"$project_root")
    printf 'Refusing unsafe Kindle root: %s\n' "$kindle_root" >&2
    exit 1
    ;;
esac

[[ -d "$kindle_root" ]] || {
  printf 'Kindle root does not exist: %s\n' "$kindle_root" >&2
  exit 1
}

[[ -f "$stage_root/Update_hotfix_universal.bin" && -d "$stage_root/extensions" && -d "$stage_root/mrpackages" && -d "$stage_root/koreader" ]] || {
  "$project_root/scripts/build-staging.sh"
}

touch "$kindle_root/.codex-kindle-write-test"
rm -f "$kindle_root/.codex-kindle-write-test"

rm -f "$kindle_root/.kindle-ota-space-filler.bin"
sync

mkdir -p "$kindle_root/extensions" "$kindle_root/mrpackages"
cp -a "$stage_root/extensions/." "$kindle_root/extensions/"
cp -a "$stage_root/mrpackages/." "$kindle_root/mrpackages/"
cp -a "$stage_root/koreader" "$kindle_root/"
cp "$stage_root/Update_hotfix_universal.bin" "$kindle_root/"
sync

cat <<EOF
Copied post-jailbreak files to:
  $kindle_root

Next on the Kindle:
1. Eject from Ubuntu.
2. Install the hotfix with Menu > Settings > Menu > Update Your Kindle.
3. After reboot, open the Run Hotfix booklet if it appears.
4. Search for ;log mrpi to run MRPI and install KUAL.
5. Open KUAL, then launch KOReader.
EOF
