# Package Manifest

Initial package date: 2026-06-11

PW5SE set verified: 2026-08-08

This file records reproducible package sets for the archived Kindle PW2
`5.12.2.2` workflow and the current PW5SE `5.15.1` commissioning workflow. The
actual archives are intentionally not tracked in Git.

## WinterBreak2

- File: `wb2.zip`
- Version: `1.0.0`
- URL: `https://github.com/KindleModding/Winterbreak2/releases/download/v1.0.0/wb2.zip`
- SHA-256: `932ff113c414c9b0109b98d7f4b96da20815364fb4905e4483581b881b2ae2e2`
- Compatibility: firmware below `5.16.4`; used as the official no-registration
  Experimental Browser fallback for the audited PW5SE `5.15.1` as well as the
  archived PW2 record.
- Staged files:
  - `jb.sh`
  - `patchedUks.sqsh`
  - `winterbreak2/dialoger.html`
- Integrity rule: use the stock `jb.sh` from this verified archive unchanged.
  Do not replace it with a downloaded modern bootstrap or combine it with the
  Store-based WinterBreak payload.

## Universal Hotfix

- File: `Update_hotfix_universal.bin`
- Version: `2.5.0`
- URL: `https://github.com/KindleModding/Hotfix/releases/download/2.5.0/Update_hotfix_universal.bin`
- SHA-256: `94d5c05254b70c4905392515411f620168ac238db62c7dcbc48a1e31d5de6c59`
- PW5SE rule: after `winterbreak.log` confirms WB2 completion, install this file
  alone through **Update Your Kindle**, then open **Run Hotfix**, before staging
  KOReader or any other post-jailbreak package. Persistence is accepted only
  after the pinned `assets/hotfix/verify-hotfix.sh.template` (SHA-256
  `55f1fa496a001c4d8712722c4e5f214f176fa7b52b27168174b2336c7376340e`)
  is nonce-rendered by `StageHotfixProbe`, run once, and finalized by
  `VerifyHotfix` against its exact prepared result hash. If only historical
  start-log evidence is unavailable after every current state check passes,
  the same nonce-bound `START_LOG` diagnostic may instead be published as the
  explicitly limited `persistent-state-v2` proof; this does not claim the
  historical job sequence.

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

- File: `kual-mrinstaller-khf.tar.xz`
- URL: `https://fw.notmarek.com/khf/kual-mrinstaller-khf.tar.xz`
- Reason: modern MRPI package for KindleHF/newer-firmware devices.

- File: `koreader-kindlehf-v2026.03.zip`
- URL: `https://build.koreader.rocks/download/stable/2026.03/koreader-kindlehf-v2026.03.zip`
- Reason: KOReader uses the `kindlehf` package for firmware `>= 5.16.3`.

## PW5SE 5.15.1 commissioning set

Date verified: 2026-08-08

These inputs are used only by `scripts/pw5se-winterbreak.ps1`. Firmware
`5.15.1` requires KOReader `kindlepw2`; do not substitute a `kindlehf` package.

### WinterBreak

- File: `WinterBreak-v2.1.0.tar.gz`
- URL: `https://github.com/KindleModding/WinterBreak/releases/download/v2.1.0/WinterBreak.tar.gz`
- SHA-256: `dc04fff5fcb685834cba9f9e95d4818b473d4100b2d40b8bb7c598ad09eb850d`
- Required staged roots: `.active_content_sandbox`,
  `apps/tech.hackerdude.winterbreak`, and `mesquito`
- Outcome on this device: the full official LocalStorage replacement was tried
  once, but the final English-language UI still opened the ordinary Store. The
  offline audit found no jailbreak marker, no root OTA package, and no changes
  to any of the 17 staged payload files. Preserve this package and its manifests
  only as the exact failed-attempt record; do not retry the Store route.

### WinterBreak2 fallback

- File: `wb2.zip`
- Version: `1.0.0`
- URL: `https://github.com/KindleModding/Winterbreak2/releases/download/v1.0.0/wb2.zip`
- SHA-256: `932ff113c414c9b0109b98d7f4b96da20815364fb4905e4483581b881b2ae2e2`
- Required staged root entries: stock `jb.sh`, `patchedUks.sqsh`, and
  `winterbreak2/dialoger.html`
- Reason: official Experimental Browser route for firmware below `5.16.4`; it
  does not require Amazon registration. The dedicated PW5SE action must retain
  50-90 MiB free and keep a separate reversible stage manifest.
- Success evidence: `winterbreak.log` must show developer keys installed,
  developer mode enabled, `mntus` execution enabled, jailbreak completion, and
  the prompt to install the hotfix.

### Universal Hotfix

- File: `Update_hotfix_universal.bin`
- Version: `2.5.0`
- URL: `https://github.com/KindleModding/Hotfix/releases/download/2.5.0/Update_hotfix_universal.bin`
- SHA-256: `94d5c05254b70c4905392515411f620168ac238db62c7dcbc48a1e31d5de6c59`
- Required sequence: verify WB2 log, return to Airplane Mode, remove a root
  `update.bin.tmp.partial` if present, stage this package alone with the
  dedicated `StageHotfix -ConfirmedAirplaneMode` action, run **Update Your
  Kindle**, then open **Run Hotfix**. With Airplane Mode restored, use
  `StageHotfixProbe`, run its single document, and use `VerifyHotfix`. On this
  device all current persistent-state checks passed, while the historical start
  line was unavailable; the exact same-record diagnostic was therefore accepted
  as `persistent-state-v2` without a full-history claim. The owned OTA filler
  remained intact until the later proof-gated KOReader stage recorded its own
  durable removal authorization.

### KOReader

- File: `koreader-kindlepw2-v2026.07.1.zip`
- URL: `https://github.com/koreader/koreader/releases/download/v2026.07.1/koreader-kindlepw2-v2026.07.1.zip`
- SHA-256: `ea1f575c54492a2c679d128b7f3210fd7d6a87e5f5a1ff1f7a7fe2080ff68f86`
- Document launcher SHA-256:
  `619e707a1dee8c36c1107af195a41c2c3f7f0d9b622b4e4cb5fbfcdae9c64e25`
- Reason: KOReader's `kindlepw2` family is correct for firmware `5.15.1`.
  The current KPM catalog exposes KOReader only for `kindlehf`, so this repo
  installs the official archive directly and adds a small shell-integration
  launcher.

### Managed PW5SE overlays (2026-08-13)

These are repository-authored, firmware-gated overlays rather than downloaded
packages:

- Upstart job: `assets/koreader-lazy/lazying-koreader-autostart.conf`
  - SHA-256:
    `87381c8cb810b3e8606c97b5ad913a1be5f49c7a4ba6f46f66b6ae3e28e95dbd`
  - Adds fail-closed native, standard `--asap`, and lower-memory
    `--framework_stop` marker modes.
- KOReader ambient-brightness patch:
  `assets/koreader-lazy/2-lazying-art-ambient-brightness.lua`
  - SHA-256:
    `b762305949d6c06cd3bd1415a689e058959ed502ebcff9c69b91810c0302fb0c`
  - Defaults Amazon ambient auto brightness to manual at KOReader startup and
    resume; the exact regular root marker `ENABLE_AMAZON_AUTO_BRIGHTNESS` opts
    in.
- Gesture-stability manager:
  `assets/koreader-lazy/manage-koreader-stability.sh`
  - Repository SHA-256:
    `dec93aa616d09587328af68e87efcd0d17e6119d8313186d51690128b5f93706`
  - Pins upstream source SHA-256
    `3a2d733a66f94e5cb1cc003c7ba736a03006e7c9242211adc243d74bc2c67db8`
    and guarded source SHA-256
    `8abc677d5eee22ae59f5454530eb79831f0e0f96717536edb76589de40f84ad5`.
  - Resumes each owned rollback transaction state, refuses foreign directory
    entries, and succeeds only at exact restored-original/no-rollback state.
- Autostart manager: `assets/koreader-lazy/manage-koreader-autostart.sh`
  - Repository SHA-256:
    `453e7b368e270bdf7e540c9242538c0dfd43b1cfe854672944b124eed94493ff`
  - Preserves the deployed v2 job hash while making malformed legacy-marker
    upgrades fail closed through the v1-visible active stop path.

The exact deployment and acceptance boundary are documented in
`docs/pw5se-koreader-stability-and-lighting.md`.
