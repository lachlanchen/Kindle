[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

[![LazyingArt banner](https://github.com/lachlanchen/lachlanchen/raw/main/figs/banner.png)](https://github.com/lachlanchen/lachlanchen/blob/main/figs/banner.png)

# Kindle

*Воспроизводимое рабочее пространство для jailbreak Kindle Paperwhite 2 и настройки KOReader на firmware `5.12.2.2`.*

[![Website](https://img.shields.io/badge/LazyingArt-lazying.art-0EA5E9?style=for-the-badge)](https://lazying.art)
[![Device](https://img.shields.io/badge/Device-Kindle%20PW2-64748B?style=for-the-badge)](../docs/paperwhite2-5.12.2.2-koreader-jailbreak.md)
[![Workflow](https://img.shields.io/badge/Workflow-WinterBreak2%20%2B%20KOReader-16A34A?style=for-the-badge)](../docs/package-manifest.md)
[![Sponsor](https://img.shields.io/badge/Sponsor-lachlanchen-EA4AAA?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/lachlanchen)

Этот репозиторий фиксирует рабочий процесс Lachlan для Kindle Paperwhite 6th generation / PW2: staging WinterBreak2, Universal Hotfix, MRPI, KUAL, KOReader и скрипты синхронизации PDF LinguaLeaf. В git хранятся только воспроизводимые скрипты, контрольные суммы и заметки; загруженные архивы, распакованные пакеты, staging-деревья и резервные копии устройства намеренно игнорируются.

| Donate | PayPal | Stripe |
| --- | --- | --- |
| [![Donate](https://img.shields.io/badge/Donate-LazyingArt-0EA5E9?style=for-the-badge&logo=kofi&logoColor=white)](https://chat.lazying.art/donate) | [![PayPal](https://img.shields.io/badge/PayPal-RongzhouChen-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/RongzhouChen) | [![Stripe](https://img.shields.io/badge/Stripe-Donate-635BFF?style=for-the-badge&logo=stripe&logoColor=white)](https://buy.stripe.com/aFadR8gIaflgfQV6T4fw400) |

## Статус

Staging на стороне компьютера завершен. На Kindle остаются шаги:

1. Установить `Update_hotfix_universal.bin` через `Update Your Kindle`.
2. После перезагрузки открыть booklet `Run Hotfix`, если он появится.
3. Найти `;log mrpi`, чтобы установить KUAL.
4. Открыть KUAL и запустить KOReader.

## Содержимое

| Путь | Назначение |
| --- | --- |
| `docs/paperwhite2-5.12.2.2-koreader-jailbreak.md` | Полная процедура jailbreak и KOReader |
| `docs/package-manifest.md` | Воспроизводимые URL пакетов и SHA-256 |
| `scripts/` | Скрипты обнаружения, staging, eject, проверки и синхронизации |
| `references/lingualleaf-koreader-sync.md` | Заметки о PDF-синхронизации и наблюдаемом поведении устройства |
| `firmware/` | Зарезервированные firmware-заметки |
| `logs/downloads.sha256` | Записанные хэши пакетов |

Локальные папки `downloads/`, `packages/`, `staging/` и `device-backups/` игнорируются.

## Быстрый старт

```bash
./scripts/check-downloads.sh
./scripts/build-staging.sh
./scripts/detect-kindle.sh
./scripts/stage-winterbreak2.sh
./scripts/stage-post-jailbreak.sh
```

Если точка монтирования известна:

```bash
./scripts/stage-winterbreak2.sh /media/lachlan/Kindle
./scripts/stage-post-jailbreak.sh /media/lachlan/Kindle
```

## Синхронизация LinguaLeaf

```bash
./scripts/sync-lingualleaf-books.sh --all
```

Исходные папки можно переопределить:

```bash
LINGUALEAF_COLOR_DIR="/path/to/en-main-color" \
LINGUALEAF_BLACKWHITE_DIR="/path/to/en-main-blackwhite" \
./scripts/sync-lingualleaf-books.sh --all
```

## Проверка

```bash
bash -n scripts/*.sh
git diff --check
./scripts/detect-kindle.sh --help
```

## Область применения

Этот workflow предназначен для запуска homebrew, например KOReader, на личном Kindle. Это не workflow для удаления DRM. Держите Airplane Mode включенным, кроме случаев, когда нужен Wi-Fi, избегайте непреднамеренных OTA-обновлений и выходите из KOReader перед передачей файлов по USB.

## Цитирование

Если вы используете это рабочее пространство в исследовании или документации, процитируйте репозиторий. GitHub читает [CITATION.cff](../CITATION.cff) и показывает панель **Cite this repository** на странице репозитория.

```bibtex
@software{chen_kindle_2026,
  author = {Chen, Lachlan},
  title = {Kindle: Kindle Paperwhite 2 Jailbreak and KOReader Setup Workspace},
  year = {2026},
  url = {https://github.com/lachlanchen/Kindle}
}
```
