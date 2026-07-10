[English](README.md) · [العربية](i18n/README.ar.md) · [Español](i18n/README.es.md) · [Français](i18n/README.fr.md) · [日本語](i18n/README.ja.md) · [한국어](i18n/README.ko.md) · [Tiếng Việt](i18n/README.vi.md) · [中文 (简体)](i18n/README.zh-Hans.md) · [中文（繁體）](i18n/README.zh-Hant.md) · [Deutsch](i18n/README.de.md) · [Русский](i18n/README.ru.md)

[![LazyingArt banner](https://github.com/lachlanchen/lachlanchen/raw/main/figs/banner.png)](https://github.com/lachlanchen/lachlanchen/blob/main/figs/banner.png)

# Kindle

*A reproducible Kindle Paperwhite 2 jailbreak and KOReader setup workspace for firmware `5.12.2.2`.*

[![Website](https://img.shields.io/badge/LazyingArt-lazying.art-0EA5E9?style=for-the-badge)](https://lazying.art)
[![Device](https://img.shields.io/badge/Device-Kindle%20PW2-64748B?style=for-the-badge)](docs/paperwhite2-5.12.2.2-koreader-jailbreak.md)
[![Workflow](https://img.shields.io/badge/Workflow-WinterBreak2%20%2B%20KOReader-16A34A?style=for-the-badge)](docs/package-manifest.md)
[![Sponsor](https://img.shields.io/badge/Sponsor-lachlanchen-EA4AAA?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/lachlanchen)

This repository records Lachlan's Kindle Paperwhite 6th generation / PW2 workflow: WinterBreak2 jailbreak staging, Universal Hotfix, MRPI, KUAL, KOReader, and LinguaLeaf PDF sync helpers. It tracks repeatable scripts, checksums, and notes; downloaded archives, extracted packages, staging trees, and device backups are intentionally ignored.

| Donate | PayPal | Stripe |
| --- | --- | --- |
| [![Donate](https://img.shields.io/badge/Donate-LazyingArt-0EA5E9?style=for-the-badge&logo=kofi&logoColor=white)](https://chat.lazying.art/donate) | [![PayPal](https://img.shields.io/badge/PayPal-RongzhouChen-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/RongzhouChen) | [![Stripe](https://img.shields.io/badge/Stripe-Donate-635BFF?style=for-the-badge&logo=stripe&logoColor=white)](https://buy.stripe.com/aFadR8gIaflgfQV6T4fw400) |

## Status

Computer-side staging is complete. The remaining Kindle-side actions are:

1. Install `Update_hotfix_universal.bin` with `Update Your Kindle`.
2. After reboot, open the `Run Hotfix` booklet if it appears.
3. Search for `;log mrpi` to install KUAL.
4. Open KUAL and launch KOReader.

## Contents

| Path | Purpose |
| --- | --- |
| `docs/paperwhite2-5.12.2.2-koreader-jailbreak.md` | Full jailbreak and KOReader procedure notes |
| `docs/package-manifest.md` | Reproducible package URLs and SHA-256 checksums |
| `scripts/` | Detection, staging, eject, checksum, and LinguaLeaf sync helpers |
| `references/lingualleaf-koreader-sync.md` | KOReader PDF sync notes and observed device behavior |
| `firmware/` | Reserved firmware notes |
| `logs/downloads.sha256` | Recorded package hashes |

Ignored local folders include `downloads/`, `packages/`, `staging/`, and `device-backups/`.

## Quick Start

Windows fast path:

```powershell
cd C:\Users\Administrator\Projects\Kindle
powershell -ExecutionPolicy Bypass -File .\scripts\kindle-jailbreak.ps1 -Action Diagnose
powershell -ExecutionPolicy Bypass -File .\scripts\kindle-jailbreak.ps1 -Action DownloadModern
```

The Windows script detects the mounted Kindle, reads `system/version.txt`, and
blocks unsafe method mismatches. See
[docs/windows-fast-jailbreak-runbook.md](docs/windows-fast-jailbreak-runbook.md)
for the direct next-time workflow.

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

## LinguaLeaf Sync

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
  title = {Kindle: Kindle Paperwhite 2 Jailbreak and KOReader Setup Workspace},
  year = {2026},
  url = {https://github.com/lachlanchen/Kindle}
}
```
