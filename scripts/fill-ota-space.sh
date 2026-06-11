#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
kindle_root="${1:-}"
leave_mib="${LEAVE_MIB:-80}"
filler_name=".kindle-ota-space-filler.bin"

if [[ -z "$kindle_root" ]]; then
  kindle_root="$("$project_root/scripts/detect-kindle.sh")"
fi

kindle_root="$(readlink -f "$kindle_root")"
filler="$kindle_root/$filler_name"

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

rm -f "$filler"
sync

avail_bytes="$(df --output=avail -B1 "$kindle_root" | tail -n 1 | tr -dc '0-9')"
leave_bytes="$((leave_mib * 1024 * 1024))"

if (( avail_bytes <= leave_bytes )); then
  printf 'Available space is already <= %s MiB; no filler needed.\n' "$leave_mib"
  df -h "$kindle_root"
  exit 0
fi

filler_bytes="$((avail_bytes - leave_bytes))"
filler_mib="$((filler_bytes / 1024 / 1024))"

if (( filler_mib <= 0 )); then
  printf 'Computed filler is too small; no filler written.\n'
  df -h "$kindle_root"
  exit 0
fi

printf 'Writing OTA space filler: %s MiB at %s\n' "$filler_mib" "$filler"
dd if=/dev/zero of="$filler" bs=1M count="$filler_mib" status=progress conv=fsync
sync
df -h "$kindle_root"
