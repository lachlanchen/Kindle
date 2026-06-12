[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

[![LazyingArt banner](https://github.com/lachlanchen/lachlanchen/raw/main/figs/banner.png)](https://github.com/lachlanchen/lachlanchen/blob/main/figs/banner.png)

# Kindle

*Ein reproduzierbarer Arbeitsbereich für Kindle Paperwhite 2 Jailbreak und KOReader-Einrichtung auf Firmware `5.12.2.2`.*

[![Website](https://img.shields.io/badge/LazyingArt-lazying.art-0EA5E9?style=for-the-badge)](https://lazying.art)
[![Device](https://img.shields.io/badge/Device-Kindle%20PW2-64748B?style=for-the-badge)](../docs/paperwhite2-5.12.2.2-koreader-jailbreak.md)
[![Workflow](https://img.shields.io/badge/Workflow-WinterBreak2%20%2B%20KOReader-16A34A?style=for-the-badge)](../docs/package-manifest.md)
[![Sponsor](https://img.shields.io/badge/Sponsor-lachlanchen-EA4AAA?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/lachlanchen)

Dieses Repository dokumentiert Lachlans Workflow für Kindle Paperwhite 6th generation / PW2: WinterBreak2-Staging, Universal Hotfix, MRPI, KUAL, KOReader und LinguaLeaf-PDF-Synchronisation. Versioniert werden reproduzierbare Skripte, Prüfsummen und Notizen; heruntergeladene Archive, entpackte Pakete, Staging-Bäume und Geräte-Backups werden bewusst ignoriert.

| Donate | PayPal | Stripe |
| --- | --- | --- |
| [![Donate](https://img.shields.io/badge/Donate-LazyingArt-0EA5E9?style=for-the-badge&logo=kofi&logoColor=white)](https://chat.lazying.art/donate) | [![PayPal](https://img.shields.io/badge/PayPal-RongzhouChen-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/RongzhouChen) | [![Stripe](https://img.shields.io/badge/Stripe-Donate-635BFF?style=for-the-badge&logo=stripe&logoColor=white)](https://buy.stripe.com/aFadR8gIaflgfQV6T4fw400) |

## Status

Das computerseitige Staging ist abgeschlossen. Auf dem Kindle bleiben diese Schritte:

1. `Update_hotfix_universal.bin` mit `Update Your Kindle` installieren.
2. Nach dem Neustart das `Run Hotfix`-Booklet öffnen, falls es erscheint.
3. Nach `;log mrpi` suchen, um KUAL zu installieren.
4. KUAL öffnen und KOReader starten.

## Inhalt

| Pfad | Zweck |
| --- | --- |
| `docs/paperwhite2-5.12.2.2-koreader-jailbreak.md` | Vollständige Jailbreak- und KOReader-Anleitung |
| `docs/package-manifest.md` | Reproduzierbare Paket-URLs und SHA-256-Prüfsummen |
| `scripts/` | Helfer für Erkennung, Staging, Auswerfen, Prüfung und Synchronisation |
| `references/lingualleaf-koreader-sync.md` | PDF-Sync-Notizen und beobachtetes Geräteverhalten |
| `firmware/` | Reservierte Firmware-Notizen |
| `logs/downloads.sha256` | Aufgezeichnete Paket-Hashes |

Lokale Ordner wie `downloads/`, `packages/`, `staging/` und `device-backups/` werden ignoriert.

## Schnellstart

```bash
./scripts/check-downloads.sh
./scripts/build-staging.sh
./scripts/detect-kindle.sh
./scripts/stage-winterbreak2.sh
./scripts/stage-post-jailbreak.sh
```

Wenn der Mount-Pfad bekannt ist:

```bash
./scripts/stage-winterbreak2.sh /media/lachlan/Kindle
./scripts/stage-post-jailbreak.sh /media/lachlan/Kindle
```

## LinguaLeaf-Synchronisation

```bash
./scripts/sync-lingualleaf-books.sh --all
```

Quellordner können überschrieben werden:

```bash
LINGUALEAF_COLOR_DIR="/path/to/en-main-color" \
LINGUALEAF_BLACKWHITE_DIR="/path/to/en-main-blackwhite" \
./scripts/sync-lingualleaf-books.sh --all
```

## Validierung

```bash
bash -n scripts/*.sh
git diff --check
./scripts/detect-kindle.sh --help
```

## Umfang

Dieser Workflow dient dazu, Homebrew wie KOReader auf einem eigenen Kindle auszuführen. Er ist kein DRM-Entfernungsworkflow. Lassen Sie den Flugmodus aktiv, außer wenn Wi-Fi benötigt wird, vermeiden Sie unbeabsichtigte OTA-Updates und beenden Sie KOReader vor USB-Dateitransfers.

## Zitieren

Wenn Sie diesen Arbeitsbereich in Forschung oder Dokumentation verwenden, zitieren Sie bitte das Repository. GitHub liest [CITATION.cff](../CITATION.cff) und zeigt auf der Repository-Seite ein **Cite this repository**-Panel an.

```bibtex
@software{chen_kindle_2026,
  author = {Chen, Lachlan},
  title = {Kindle: Kindle Paperwhite 2 Jailbreak and KOReader Setup Workspace},
  year = {2026},
  url = {https://github.com/lachlanchen/Kindle}
}
```
