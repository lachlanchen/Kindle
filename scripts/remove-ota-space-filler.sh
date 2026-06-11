#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
kindle_root="${1:-}"
filler_name=".kindle-ota-space-filler.bin"

if [[ -z "$kindle_root" ]]; then
  kindle_root="$("$project_root/scripts/detect-kindle.sh")"
fi

kindle_root="$(readlink -f "$kindle_root")"
rm -f "$kindle_root/$filler_name"
sync
df -h "$kindle_root"
