[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

[![LazyingArt banner](https://github.com/lachlanchen/lachlanchen/raw/main/figs/banner.png)](https://github.com/lachlanchen/lachlanchen/blob/main/figs/banner.png)

# Kindle

*Un espacio de trabajo reproducible para jailbreak de Kindle Paperwhite 2 y configuración de KOReader en firmware `5.12.2.2`.*

[![Website](https://img.shields.io/badge/LazyingArt-lazying.art-0EA5E9?style=for-the-badge)](https://lazying.art)
[![Device](https://img.shields.io/badge/Device-Kindle%20PW2-64748B?style=for-the-badge)](../docs/paperwhite2-5.12.2.2-koreader-jailbreak.md)
[![Workflow](https://img.shields.io/badge/Workflow-WinterBreak2%20%2B%20KOReader-16A34A?style=for-the-badge)](../docs/package-manifest.md)
[![Sponsor](https://img.shields.io/badge/Sponsor-lachlanchen-EA4AAA?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/lachlanchen)

Este repositorio documenta el flujo de Lachlan para Kindle Paperwhite 6th generation / PW2: preparación de WinterBreak2, Universal Hotfix, MRPI, KUAL, KOReader y scripts para sincronizar PDFs de LinguaLeaf. Solo se versionan scripts reproducibles, sumas de verificación y notas; los archivos descargados, paquetes extraídos, árboles de staging y copias de seguridad del dispositivo se ignoran de forma intencional.

| Donate | PayPal | Stripe |
| --- | --- | --- |
| [![Donate](https://img.shields.io/badge/Donate-LazyingArt-0EA5E9?style=for-the-badge&logo=kofi&logoColor=white)](https://chat.lazying.art/donate) | [![PayPal](https://img.shields.io/badge/PayPal-RongzhouChen-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/RongzhouChen) | [![Stripe](https://img.shields.io/badge/Stripe-Donate-635BFF?style=for-the-badge&logo=stripe&logoColor=white)](https://buy.stripe.com/aFadR8gIaflgfQV6T4fw400) |

## Estado

La preparación del lado del ordenador ya está completa. En el Kindle faltan estos pasos:

1. Instalar `Update_hotfix_universal.bin` con `Update Your Kindle`.
2. Tras reiniciar, abrir el booklet `Run Hotfix` si aparece.
3. Buscar `;log mrpi` para instalar KUAL.
4. Abrir KUAL y lanzar KOReader.

## Contenido

| Ruta | Propósito |
| --- | --- |
| `docs/paperwhite2-5.12.2.2-koreader-jailbreak.md` | Procedimiento completo de jailbreak y KOReader |
| `docs/package-manifest.md` | URLs reproducibles y sumas SHA-256 |
| `scripts/` | Ayudas de detección, staging, expulsión, verificación y sincronización |
| `references/lingualleaf-koreader-sync.md` | Notas de sincronización de PDFs y comportamiento observado |
| `firmware/` | Notas reservadas de firmware |
| `logs/downloads.sha256` | Hashes registrados de paquetes |

Las carpetas locales `downloads/`, `packages/`, `staging/` y `device-backups/` se ignoran.

## Inicio rápido

```bash
./scripts/check-downloads.sh
./scripts/build-staging.sh
./scripts/detect-kindle.sh
./scripts/stage-winterbreak2.sh
./scripts/stage-post-jailbreak.sh
```

Si conoces la raíz montada:

```bash
./scripts/stage-winterbreak2.sh /media/lachlan/Kindle
./scripts/stage-post-jailbreak.sh /media/lachlan/Kindle
```

## Sincronización LinguaLeaf

```bash
./scripts/sync-lingualleaf-books.sh --all
```

Las carpetas de origen se pueden cambiar:

```bash
LINGUALEAF_COLOR_DIR="/path/to/en-main-color" \
LINGUALEAF_BLACKWHITE_DIR="/path/to/en-main-blackwhite" \
./scripts/sync-lingualleaf-books.sh --all
```

## Validación

```bash
bash -n scripts/*.sh
git diff --check
./scripts/detect-kindle.sh --help
```

## Alcance

Este flujo sirve para ejecutar homebrew como KOReader en un Kindle propio. No es un flujo para eliminar DRM. Mantén el modo avión salvo cuando necesites Wi-Fi, evita actualizaciones OTA no deseadas y sal de KOReader antes de transferir archivos por USB.

## Cita

Si usas este espacio de trabajo en investigación o documentación, cita el repositorio. GitHub lee [CITATION.cff](../CITATION.cff) y muestra un panel **Cite this repository** en la página del repo.

```bibtex
@software{chen_kindle_2026,
  author = {Chen, Lachlan},
  title = {Kindle: Kindle Paperwhite 2 Jailbreak and KOReader Setup Workspace},
  year = {2026},
  url = {https://github.com/lachlanchen/Kindle}
}
```
