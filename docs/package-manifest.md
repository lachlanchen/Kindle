# Package Manifest

Date downloaded: 2026-06-11

This file records the reproducible package set used for the Kindle PW2
`5.12.2.2` jailbreak and KOReader setup. The actual archives are intentionally
not tracked in git.

## WinterBreak2

- File: `wb2.zip`
- URL: `https://github.com/KindleModding/Winterbreak2/releases/download/v1.0.0/wb2.zip`
- SHA-256: `932ff113c414c9b0109b98d7f4b96da20815364fb4905e4483581b881b2ae2e2`
- Staged files:
  - `jb.sh`
  - `patchedUks.sqsh`
  - `winterbreak2/dialoger.html`

## Universal Hotfix

- File: `Update_hotfix_universal.bin`
- URL: `https://github.com/KindleModding/Hotfix/releases/latest/download/Update_hotfix_universal.bin`
- SHA-256: `94d5c05254b70c4905392515411f620168ac238db62c7dcbc48a1e31d5de6c59`

## MRPI

- File: `kual-mrinstaller-khf.zip`
- URL: `https://kindlemodding.org/jailbreaking/post-jailbreak/installing-kual-mrpi/kual-mrinstaller-khf.zip`
- SHA-256: `9974dfc2d1e7687b3fc74d68f6b5aeab2428f22d83ab82e6d600a0384c607d09`

## KUAL

- File: `Update_KUALBooklet_HDRepack.bin`
- URL: `https://kindlemodding.org/jailbreaking/post-jailbreak/installing-kual-mrpi/Update_KUALBooklet_HDRepack.bin`
- SHA-256: `a0cd1f490b2fc779457990cefa4a9ae53921fc8c2b5551f095500be3b55fc20a`

## KOReader

- File: `koreader-kindlepw2-v2026.03.zip`
- URL: `https://github.com/koreader/koreader/releases/download/v2026.03/koreader-kindlepw2-v2026.03.zip`
- SHA-256: `46e969bb13765b2630b5e14aa2e7fa2445ec551ccaa47db3efe644d0e34944b0`
- Reason: `kindlepw2` is the correct KOReader package family for PW2 and
  newer supported Kindle firmware in this workflow.

## Modern Windows Helper Downloads

These are downloaded dynamically by `scripts/kindle-jailbreak.ps1 -Action
DownloadModern` because the connected 2026-07-10 device reported firmware
`5.18.1`, which is outside the original WinterBreak2/PW2 path.

- File: `AdBreak-latest.zip`
- URL source: latest release asset from `https://github.com/KindleModding/AdBreak`
- Reason: KindleModding routes firmware `5.18.1+` to AdBreak when prerequisites
  are satisfied.

- File: `PEKI-latest.zip`
- URL source: latest release asset from `https://github.com/KindleTweaks/PEKI`
- Reason: KindleModding now recommends PEKI for K5 and newer KUAL setup by
  copying `KUAL.jar` and `KUAL.sh` into `documents/`.

- File: `koreader-kindlehf-v2026.03.zip`
- URL: `https://build.koreader.rocks/download/stable/2026.03/koreader-kindlehf-v2026.03.zip`
- Reason: KOReader uses the `kindlehf` package for firmware `>= 5.16.3`.
