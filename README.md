[English](README.md) · [العربية](i18n/README.ar.md) · [Español](i18n/README.es.md) · [Français](i18n/README.fr.md) · [日本語](i18n/README.ja.md) · [한국어](i18n/README.ko.md) · [Tiếng Việt](i18n/README.vi.md) · [中文 (简体)](i18n/README.zh-Hans.md) · [中文（繁體）](i18n/README.zh-Hant.md) · [Deutsch](i18n/README.de.md) · [Русский](i18n/README.ru.md)

[![LazyingArt banner](https://github.com/lachlanchen/lachlanchen/raw/main/figs/banner.png)](https://github.com/lachlanchen/lachlanchen/blob/main/figs/banner.png)

# Kindle

*Reproducible, device-gated Kindle jailbreak, KOReader, secure SSH, and book-sync workflows.*

[![Website](https://img.shields.io/badge/LazyingArt-lazying.art-0EA5E9?style=for-the-badge)](https://lazying.art)
[![Book Sender](https://img.shields.io/badge/Kindle%20Book%20Sender-Download-0D5C4B?style=for-the-badge)](https://lachlanchen.github.io/Kindle/)
[![Device](https://img.shields.io/badge/Current-PW5SE%205.15.1-64748B?style=for-the-badge)](docs/paperwhite5-5.15.1-winterbreak-koreader.md)
[![Workflow](https://img.shields.io/badge/Workflow-WinterBreak2%20%2B%20Hotfix%20%2B%20KOReader-16A34A?style=for-the-badge)](docs/package-manifest.md)
[![Sponsor](https://img.shields.io/badge/Sponsor-lachlanchen-EA4AAA?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/lachlanchen)

This repository records separate, compatibility-gated workflows for several
personally owned Kindles. The current route is a Paperwhite 11th generation /
PW5SE on firmware `5.15.1`. Its Store-based WinterBreak attempt ended cleanly
without execution, so the active route is official stock WinterBreak2 `1.0.0`,
Universal Hotfix `2.5.0`, KOReader `kindlepw2`, key-only SSH, guarded one-shot
KOReader autostart, and hash-verified PDF sync. Older PW2 and PW4 records remain
for those exact devices only. Downloaded archives, staging trees, unpublished
or device-specific credentials, and device backups are intentionally excluded.
The already-published Kindle-only shared sender identity is the documented
exception; it is not a recovery or general-purpose computer identity.

| Donate | PayPal | Stripe |
| --- | --- | --- |
| [![Donate](https://img.shields.io/badge/Donate-LazyingArt-0EA5E9?style=for-the-badge&logo=kofi&logoColor=white)](https://chat.lazying.art/donate) | [![PayPal](https://img.shields.io/badge/PayPal-RongzhouChen-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/RongzhouChen) | [![Stripe](https://img.shields.io/badge/Stripe-Donate-635BFF?style=for-the-badge&logo=stripe&logoColor=white)](https://buy.stripe.com/aFadR8gIaflgfQV6T4fw400) |

## Status

The current Kindle is audited and backed up. The Store/LocalStorage route
failed cleanly and is closed. Official WinterBreak2 `1.0.0` then executed
successfully. Universal Hotfix `2.5.0` passed all current persistence checks,
and its unavailable
historical start log was recorded without claiming full history under the
explicit `persistent-state-v2` proof mode. KOReader `kindlepw2` v2026.07.1 is
staged and independently verified: 1,034 files match exactly, and the owned OTA
filler and root update artifacts are absent. The initial 249-book Nutstore
snapshot is complete and its idempotent confirmation resumed all 249 entries
without a new copy. A later LinguaLeaf addition brings the current desired
corpus to 250 and remains pending until its transfer is confirmed. The manual
KOReader launch and both managed SSH identities work. The
selected portable GUI/PDF key is intentionally published and restricted to
these Kindles; the fresh PW5 key remains as recovery.

The exact owned PW5SE autostart job is installed, registered, enabled, and
accepted. Its SHA-256 is
`2de0232b971926b7e70d913a27ba76168ed69760504ae2a90947e4402e7e5828`.
An enabled reboot with USB data disconnected produced the trace `started` ->
`native-ready` -> `launching`; the job was `start/running`, KOReader was
running, and Wi-Fi/SSH returned. The regular parked marker
`_DISABLE_KOREADER_AUTOSTART` is present and the active
`DISABLE_KOREADER_AUTOSTART` marker is absent. Disable by atomically renaming
the parked marker to the active name; enable only through the audited manager,
which performs the reverse rename after checking the exact job hash. Do not
delete either marker. `/` is read-only, `preventScreenSaver=0`, and
`/mnt/us/emergency.sh` remains absent. An independent exit test left the job
`stop/waiting` with no reader process after at least 45 seconds, proving there
is no respawn.

Boot acceptance requires USB **data** to be disconnected. No cable, a wall
charger, or a charge-only cable is safe; a computer data cable can enter USB
Drive Mode and export/make unavailable `/mnt/us`, where the launcher and marker
live.

## Contents

| Path | Purpose |
| --- | --- |
| `docs/paperwhite5-5.15.1-winterbreak-koreader.md` | Current PW5SE Store-attempt audit, guarded WinterBreak2/hotfix fallback, KOReader, managed portable SSH, and recovery runbook |
| `docs/pw5se-koreader-autostart-design.md` | Firmware-specific guarded autostart design, accepted live evidence, rename-only recovery marker, and USB boot boundary |
| `docs/paperwhite2-5.12.2.2-koreader-jailbreak.md` | Full jailbreak and KOReader procedure notes |
| `docs/package-manifest.md` | Reproducible package URLs and SHA-256 checksums |
| `scripts/` | Detection, staging, eject, checksum, and LinguaLeaf sync helpers |
| `tests/` | Isolated rollback and Store-sandbox safety regression checks |
| `skills/kindle-pw5se-commission/` | Reusable guarded commissioning skill |
| `references/lingualleaf-koreader-sync.md` | KOReader PDF sync notes and observed device behavior |
| `firmware/` | Reserved firmware notes |
| `logs/downloads.sha256` | Recorded package hashes |

Ignored local folders include `downloads/`, `packages/`, `staging/`, and `device-backups/`.

## Quick Start

Windows fast path:

```powershell
cd C:\Users\Administrator\Projects\Kindle
powershell -ExecutionPolicy Bypass -File .\scripts\pw5se-winterbreak.ps1 -Action Diagnose
powershell -ExecutionPolicy Bypass -File .\scripts\pw5se-winterbreak.ps1 -Action Download
```

The dedicated script requires a separate confirmation after saved-Wi-Fi,
Airplane Mode, restart, and USB reconnection. See the
[current PW5SE runbook](docs/paperwhite5-5.15.1-winterbreak-koreader.md).
Do not use the archived generic `StageWinterBreak2` or `StagePostJailbreak`
actions below for the current PW5SE; its dedicated script enforces the device,
stock-payload, rollback, and free-space gates.

The commands below are the archived PW2/Linux workflow and must not be used on
the current PW5SE.

Verify downloaded package hashes:

```bash
./scripts/check-downloads.sh
```

Rebuild extracted package cache and copy-ready staging trees:

```bash
./scripts/build-staging.sh
```

Detect a mounted Kindle:

```bash
./scripts/detect-kindle.sh
```

Stage WinterBreak2 before the on-device jailbreak:

```bash
./scripts/stage-winterbreak2.sh
```

After WinterBreak2 succeeds, stage Hotfix, MRPI, KUAL, and KOReader:

```bash
./scripts/stage-post-jailbreak.sh
```

If auto-detection fails but the mount root is known:

```bash
./scripts/stage-winterbreak2.sh /media/lachlan/Kindle
./scripts/stage-post-jailbreak.sh /media/lachlan/Kindle
```

## Kindle Book Sender

Download the native Windows, Ubuntu/Linux, Intel Mac, or Apple Silicon app:

https://lachlanchen.github.io/Kindle/

The current portable build uses the intentionally published Kindle-only
Handoff/PDF identity instead of generating a different identity per computer.
Its pinned fingerprint is
`SHA256:Q/RgMY4wzHjQYuC3sfHDykwp8ejp9C7wyfAZLE8OMJE`. Pair it with
`scripts/pair-kindle-book-sender.ps1`; the separate PW5SE recovery key remains
authorized as an administrative fallback.

This convenience has a deliberate security cost: the private half is
distributed with the app/repository/handoff material, so anyone holding it can
authenticate whenever KOReader SSH is reachable on a paired Kindle. Never
authorize this identity on a computer, router, server, or unrelated device, and
never print its contents. After pairing, put both devices on the same Wi-Fi,
start KOReader's SSH server, click **Find my Kindle**, drag in books, and send.
Discovery, IP selection, SFTP/SCP fallback, and the destination folder are
automatic.

## LinguaLeaf Sync

The initial completed PW5SE snapshot took all book bytes from Nutstore: 239 PDFs
from `Nutstore\1\Share\LinguaLeaf\blackwhite` and 10 PDFs from
`Nutstore\1\Share\PocketPolished`. The old PW2 contributes only the logical
folder mapping and optional checksum-compatible `.sdr` reading state; it never
supplies a PDF or limits which Nutstore books are copied.

Preview the no-mutation plan, then explicitly apply it:

```powershell
python .\scripts\migrate-kindle-library.py
python .\scripts\migrate-kindle-library.py --apply
```

The transfer is one-book-at-a-time, atomic, SHA-256 verified, and resumable. It
created no backup copies on the new PW5SE. The final guarded apply reported
`bookCount=249`, zero copied PDFs, 249 resumed PDFs, 10 copied `.sdr` trees, and
239 skipped sidecar attempts. The sidecar classifications were 10 `copied`, one
`skipped-destination-exists`, 161 `not-inspected`, 68 absent or ambiguous, and
nine checksum/current-PDF mismatches. An independent audit matched every file
in all 10 copied sidecar trees to the PW2 source by size and SHA-256 and found
no owned temporary files. Both keep-awake guards captured
`preventScreenSaver=0` and restored it to `0`.

The 11 eligible candidates were established using current PDF size and
KOReader partial MD5, not the stale checksum stored in sidecar metadata.
*Zizhi Tongjian, Part 1* was the one existing-destination skip and was **not**
overwritten: the PW5SE sidecar records `last_page=11` while the PW2 records
`last_page=4651`; both report `doc_pages=18079`, and the complete PDF SHA-256
matches Nutstore, PW2, and PW5SE. Preserving PW5SE state is the safe default. A
transactional explicit-replacement path is implemented and tested but has not run;
replacement must wait until the book is closed in KOReader/file browser and an
explicit guarded run is requested. Differently named/edition *Shiji* sidecars
remain deliberately unmapped and were not copied. The two misplaced
`A Brief History of Time` root copies were absent. Later source drift detected
one new `Giving Up the Gun...｜黑白.pdf` at timestamp 2026-08-09 17:07. That
book is not part of the completed snapshot and is not yet claimed transferred;
the current desired inventory is 240 LinguaLeaf plus 10 PocketPolished PDFs
(250 total).
The exact seven-folder audit and sidecar rules are in
[`references/lingualleaf-koreader-sync.md`](references/lingualleaf-koreader-sync.md).

The following shell workflow is the earlier small USB sync and remains for its
historical source layout.

Sync LinguaLeaf PDFs into a KOReader-friendly folder:

```bash
./scripts/sync-lingualleaf-books.sh --all
```

The default targets are:

```text
documents/LinguaLeaf/en-main-color/
documents/LinguaLeaf/en-main-blackwhite/
```

Source folders can be overridden:

```bash
LINGUALEAF_COLOR_DIR="/path/to/en-main-color" \
LINGUALEAF_BLACKWHITE_DIR="/path/to/en-main-blackwhite" \
./scripts/sync-lingualleaf-books.sh --all
```

## Validation

```bash
bash -n scripts/*.sh
git diff --check
./scripts/detect-kindle.sh --help
```

## Scope

This workflow is for running homebrew such as KOReader on a personally owned Kindle. It is not a DRM-removal workflow. Keep Airplane Mode on unless Wi-Fi is needed, avoid unintended OTA updates, and exit KOReader before USB file transfer.

## Citation

If you use this workspace in research or documentation, cite the repository. GitHub reads [CITATION.cff](CITATION.cff) and shows a **Cite this repository** panel on the repo page.

```bibtex
@software{chen_kindle_2026,
  author = {Chen, Lachlan},
  title = {Kindle: Reproducible Jailbreak, KOReader, and Book Sync Workflows},
  year = {2026},
  url = {https://github.com/lachlanchen/Kindle}
}
```
