#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
downloads="$project_root/downloads"

cd "$downloads"

sha256sum -c <<'EOF'
932ff113c414c9b0109b98d7f4b96da20815364fb4905e4483581b881b2ae2e2  wb2.zip
46e969bb13765b2630b5e14aa2e7fa2445ec551ccaa47db3efe644d0e34944b0  koreader-kindlepw2-v2026.03.zip
EOF

sha256sum \
  Update_KUALBooklet_HDRepack.bin \
  Update_hotfix_universal.bin \
  kual-mrinstaller-khf.zip \
  wb2.zip \
  koreader-kindlepw2-v2026.03.zip \
  | tee "$project_root/logs/downloads.sha256"
