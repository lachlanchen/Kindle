#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
kindle_root="${1:-}"

if [[ -z "$kindle_root" ]]; then
  kindle_root="$("$project_root/scripts/detect-kindle.sh")"
fi

sync

if command -v gio >/dev/null 2>&1; then
  gio mount -e "$kindle_root"
else
  udisksctl unmount -b "$(findmnt -rn -o SOURCE --target "$kindle_root")"
fi
