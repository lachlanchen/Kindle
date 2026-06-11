#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
kindle_root="${1:-}"

if [[ -z "$kindle_root" ]]; then
  kindle_root="$("$project_root/scripts/detect-kindle.sh")"
fi

sync

if command -v gio >/dev/null 2>&1 && gio mount -e "$kindle_root"; then
  exit 0
fi

source_device="$(findmnt -rn -o SOURCE --target "$kindle_root" || true)"
if [[ -n "$source_device" ]]; then
  udisksctl unmount -b "$source_device" || gio mount -u "$kindle_root"
else
  printf 'No active mount found for %s\n' "$kindle_root"
fi
