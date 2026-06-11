#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
kindle_root="${1:-}"

if [[ -z "$kindle_root" ]]; then
  kindle_root="$("$project_root/scripts/detect-kindle.sh")"
fi

kindle_root="$(readlink -f "$kindle_root")"
stage_root="$project_root/staging/winterbreak2-root"

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

[[ -f "$stage_root/jb.sh" && -f "$stage_root/patchedUks.sqsh" && -d "$stage_root/winterbreak2" ]] || {
  "$project_root/scripts/build-staging.sh"
}

touch "$kindle_root/.codex-kindle-write-test"
rm -f "$kindle_root/.codex-kindle-write-test"

cp -a "$stage_root/." "$kindle_root/"
sync

cat <<EOF
Copied WinterBreak2 to:
  $kindle_root

The Kindle root should now contain:
  jb.sh
  patchedUks.sqsh
  winterbreak2/

Next:
1. Safely eject the Kindle from Ubuntu.
2. On the Kindle, connect to Wi-Fi.
3. Open Experimental Browser.
4. Go to https://winterbreak2.now.sh/
5. Press Jailbreak and wait for it to finish.
6. Reconnect the Kindle and run stage-post-jailbreak.sh.
EOF
