#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: detect-kindle.sh

Print the mounted Kindle storage root if exactly one candidate is found.
The Kindle is expected to appear as USB mass storage with folders such as
documents/ and system/.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

declare -a candidates=()
declare -A seen=()

add_candidate() {
  local path="$1"
  [[ -d "$path" ]] || return 0
  path="$(readlink -f "$path")"
  [[ -n "${seen[$path]:-}" ]] && return 0
  seen["$path"]=1
  candidates+=("$path")
}

looks_like_kindle_root() {
  local path="$1"
  [[ -d "$path" ]] || return 1

  case "$(basename "$path")" in
    *Kindle*|*KINDLE*|*kindle*) return 0 ;;
  esac

  [[ -d "$path/documents" && -d "$path/system" ]] && return 0
  [[ -d "$path/documents" && -d "$path/audible" ]] && return 0
  return 1
}

scan_tree() {
  local base="$1"
  [[ -d "$base" ]] || return 0
  while IFS= read -r path; do
    looks_like_kindle_root "$path" && add_candidate "$path"
  done < <(find "$base" -mindepth 1 -maxdepth 2 -type d 2>/dev/null || true) || true
}

scan_tree "/media/${SUDO_USER:-${USER:-lachlan}}"
scan_tree "/run/media/${SUDO_USER:-${USER:-lachlan}}"
scan_tree "/mnt"

while IFS= read -r target; do
  looks_like_kindle_root "$target" && add_candidate "$target"
done < <(findmnt -rn -o TARGET 2>/dev/null || true) || true

case "${#candidates[@]}" in
  0)
    cat >&2 <<'EOF'
No mounted Kindle storage was found.

Check:
- Use a data-capable USB cable, not a charge-only cable.
- The Kindle screen should show USB Drive Mode.
- If connected through RDP/VM/remote software, pass the USB device to Ubuntu.
- Reconnect the Kindle, then run this script again.
EOF
    exit 1
    ;;
  1)
    printf '%s\n' "${candidates[0]}"
    ;;
  *)
    printf 'Multiple possible Kindle mount roots found:\n' >&2
    printf '  %s\n' "${candidates[@]}" >&2
    printf 'Pass the correct path explicitly to the staging script.\n' >&2
    exit 2
    ;;
esac
