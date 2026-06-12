[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

[![LazyingArt banner](https://github.com/lachlanchen/lachlanchen/raw/main/figs/banner.png)](https://github.com/lachlanchen/lachlanchen/blob/main/figs/banner.png)

# Kindle

*Un espace de travail reproductible pour le jailbreak d'un Kindle Paperwhite 2 et l'installation de KOReader sur le firmware `5.12.2.2`.*

[![Website](https://img.shields.io/badge/LazyingArt-lazying.art-0EA5E9?style=for-the-badge)](https://lazying.art)
[![Device](https://img.shields.io/badge/Device-Kindle%20PW2-64748B?style=for-the-badge)](../docs/paperwhite2-5.12.2.2-koreader-jailbreak.md)
[![Workflow](https://img.shields.io/badge/Workflow-WinterBreak2%20%2B%20KOReader-16A34A?style=for-the-badge)](../docs/package-manifest.md)
[![Sponsor](https://img.shields.io/badge/Sponsor-lachlanchen-EA4AAA?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/lachlanchen)

Ce dépôt consigne le flux de travail de Lachlan pour Kindle Paperwhite 6th generation / PW2 : préparation WinterBreak2, Universal Hotfix, MRPI, KUAL, KOReader et scripts de synchronisation PDF LinguaLeaf. Il suit les scripts reproductibles, les sommes de contrôle et les notes; les archives téléchargées, paquets extraits, arbres de staging et sauvegardes de l'appareil sont volontairement ignorés.

| Donate | PayPal | Stripe |
| --- | --- | --- |
| [![Donate](https://img.shields.io/badge/Donate-LazyingArt-0EA5E9?style=for-the-badge&logo=kofi&logoColor=white)](https://chat.lazying.art/donate) | [![PayPal](https://img.shields.io/badge/PayPal-RongzhouChen-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/RongzhouChen) | [![Stripe](https://img.shields.io/badge/Stripe-Donate-635BFF?style=for-the-badge&logo=stripe&logoColor=white)](https://buy.stripe.com/aFadR8gIaflgfQV6T4fw400) |

## État

La préparation côté ordinateur est terminée. Les actions restantes sur le Kindle sont :

1. Installer `Update_hotfix_universal.bin` avec `Update Your Kindle`.
2. Après redémarrage, ouvrir le livret `Run Hotfix` s'il apparaît.
3. Rechercher `;log mrpi` pour installer KUAL.
4. Ouvrir KUAL et lancer KOReader.

## Contenu

| Chemin | Rôle |
| --- | --- |
| `docs/paperwhite2-5.12.2.2-koreader-jailbreak.md` | Procédure complète jailbreak et KOReader |
| `docs/package-manifest.md` | URLs reproductibles et SHA-256 |
| `scripts/` | Aides de détection, staging, éjection, vérification et synchronisation |
| `references/lingualleaf-koreader-sync.md` | Notes de synchronisation PDF et comportement observé |
| `firmware/` | Notes firmware réservées |
| `logs/downloads.sha256` | Hashes de paquets enregistrés |

Les dossiers locaux `downloads/`, `packages/`, `staging/` et `device-backups/` sont ignorés.

## Démarrage rapide

```bash
./scripts/check-downloads.sh
./scripts/build-staging.sh
./scripts/detect-kindle.sh
./scripts/stage-winterbreak2.sh
./scripts/stage-post-jailbreak.sh
```

Si le point de montage est connu :

```bash
./scripts/stage-winterbreak2.sh /media/lachlan/Kindle
./scripts/stage-post-jailbreak.sh /media/lachlan/Kindle
```

## Synchronisation LinguaLeaf

```bash
./scripts/sync-lingualleaf-books.sh --all
```

Les dossiers source peuvent être remplacés :

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

## Portée

Ce flux sert à exécuter des logiciels homebrew comme KOReader sur un Kindle personnel. Ce n'est pas une procédure de suppression de DRM. Gardez le mode avion sauf besoin de Wi-Fi, évitez les mises à jour OTA non voulues et quittez KOReader avant un transfert USB.

## Citation

Si vous utilisez cet espace de travail dans une recherche ou une documentation, citez le dépôt. GitHub lit [CITATION.cff](../CITATION.cff) et affiche un panneau **Cite this repository** sur la page du dépôt.

```bibtex
@software{chen_kindle_2026,
  author = {Chen, Lachlan},
  title = {Kindle: Kindle Paperwhite 2 Jailbreak and KOReader Setup Workspace},
  year = {2026},
  url = {https://github.com/lachlanchen/Kindle}
}
```
