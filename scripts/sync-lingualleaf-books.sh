#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
kindle_root="${1:-}"
target_rel="documents/LinguaLeaf/en-main-color"

if [[ -z "$kindle_root" ]]; then
  kindle_root="$("$project_root/scripts/detect-kindle.sh")"
fi

kindle_root="$(readlink -f "$kindle_root")"
target_dir="$kindle_root/$target_rel"

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

declare -a books=(
  "/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/Wuthering Heights（日文注）.pdf"
  "/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/One Hundred Years of Solitude（日文注）.pdf"
  "/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/The Count of Monte Cristo（日文注）.pdf"
  "/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/Les Misérables（日文注）.pdf"
  "/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/Notre-Dame de Paris（日文注）.pdf"
)

for book in "${books[@]}"; do
  [[ -f "$book" ]] || {
    printf 'Missing source book: %s\n' "$book" >&2
    exit 1
  }
done

mkdir -p "$target_dir"

for book in "${books[@]}"; do
  rsync -a --info=progress2 "$book" "$target_dir/"
done

sync

printf 'Copied LinguaLeaf books to Kindle folder:\n  %s\n\n' "$target_dir"
find "$target_dir" -maxdepth 1 -type f -name '*.pdf' -printf '%f\t%k KiB\n' | sort
