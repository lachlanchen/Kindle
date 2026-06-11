#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
kindle_root=""
target_rel="documents/LinguaLeaf/en-main-color"
edition="color"

usage() {
  cat <<'EOF'
Usage: sync-lingualleaf-books.sh [--color|--blackwhite|--all] [KINDLE_ROOT]

Default edition is --color for backward compatibility.
EOF
}

while (($#)); do
  case "$1" in
    --color)
      edition="color"
      target_rel="documents/LinguaLeaf/en-main-color"
      shift
      ;;
    --blackwhite|--bw)
      edition="blackwhite"
      target_rel="documents/LinguaLeaf/en-main-blackwhite"
      shift
      ;;
    --all)
      edition="all"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [[ -z "$kindle_root" ]]; then
        kindle_root="$1"
        shift
      else
        usage >&2
        exit 2
      fi
      ;;
  esac
done

if [[ -z "$kindle_root" ]]; then
  kindle_root="$("$project_root/scripts/detect-kindle.sh")"
fi

kindle_root="$(readlink -f "$kindle_root")"

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

sync_books() {
  local rel="$1"
  shift
  local target="$kindle_root/$rel"
  local book

  for book in "$@"; do
    [[ -f "$book" ]] || {
      printf 'Missing source book: %s\n' "$book" >&2
      exit 1
    }
  done

  mkdir -p "$target"

  for book in "$@"; do
    rsync -a --info=progress2 "$book" "$target/"
  done

  sync

  printf 'Copied LinguaLeaf books to Kindle folder:\n  %s\n\n' "$target"
  find "$target" -maxdepth 1 -type f -name '*.pdf' -printf '%f\t%k KiB\n' | sort
}

declare -a color_books=(
  "/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/Wuthering Heights（日文注）.pdf"
  "/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/One Hundred Years of Solitude（日文注）.pdf"
  "/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/The Count of Monte Cristo（日文注）.pdf"
  "/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/Les Misérables（日文注）.pdf"
  "/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-color/Notre-Dame de Paris（日文注）.pdf"
)

declare -a blackwhite_books=(
  "/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-blackwhite/Wuthering Heights（日文注・黑白）.pdf"
  "/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-blackwhite/One Hundred Years of Solitude（日文注・黑白）.pdf"
  "/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-blackwhite/The Count of Monte Cristo（日文注・黑白）.pdf"
  "/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-blackwhite/Les Misérables（日文注・黑白）.pdf"
  "/home/lachlan/Nutstore Files/Projects/LinguaLeaf/books/en-main-blackwhite/Notre-Dame de Paris（日文注・黑白）.pdf"
)

case "$edition" in
  color)
    sync_books "$target_rel" "${color_books[@]}"
    ;;
  blackwhite)
    sync_books "$target_rel" "${blackwhite_books[@]}"
    ;;
  all)
    sync_books "documents/LinguaLeaf/en-main-color" "${color_books[@]}"
    sync_books "documents/LinguaLeaf/en-main-blackwhite" "${blackwhite_books[@]}"
    ;;
esac
