[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

[![LazyingArt banner](https://github.com/lachlanchen/lachlanchen/raw/main/figs/banner.png)](https://github.com/lachlanchen/lachlanchen/blob/main/figs/banner.png)

# Kindle

*ファームウェア `5.12.2.2` 向け Kindle Paperwhite 2 jailbreak と KOReader セットアップの再現可能な作業リポジトリ。*

[![Website](https://img.shields.io/badge/LazyingArt-lazying.art-0EA5E9?style=for-the-badge)](https://lazying.art)
[![Device](https://img.shields.io/badge/Device-Kindle%20PW2-64748B?style=for-the-badge)](../docs/paperwhite2-5.12.2.2-koreader-jailbreak.md)
[![Workflow](https://img.shields.io/badge/Workflow-WinterBreak2%20%2B%20KOReader-16A34A?style=for-the-badge)](../docs/package-manifest.md)
[![Sponsor](https://img.shields.io/badge/Sponsor-lachlanchen-EA4AAA?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/lachlanchen)

このリポジトリは、Lachlan の Kindle Paperwhite 第 6 世代 / PW2 ワークフローを記録します。内容は WinterBreak2 の staging、Universal Hotfix、MRPI、KUAL、KOReader、LinguaLeaf PDF 同期ヘルパーです。追跡するのは再現用スクリプト、チェックサム、手順書のみで、ダウンロード済みアーカイブ、展開済みパッケージ、staging tree、端末バックアップは意図的に除外しています。

| Donate | PayPal | Stripe |
| --- | --- | --- |
| [![Donate](https://img.shields.io/badge/Donate-LazyingArt-0EA5E9?style=for-the-badge&logo=kofi&logoColor=white)](https://chat.lazying.art/donate) | [![PayPal](https://img.shields.io/badge/PayPal-RongzhouChen-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/RongzhouChen) | [![Stripe](https://img.shields.io/badge/Stripe-Donate-635BFF?style=for-the-badge&logo=stripe&logoColor=white)](https://buy.stripe.com/aFadR8gIaflgfQV6T4fw400) |

## 状態

PC 側の staging は完了しています。Kindle 側で残っている作業は次の通りです。

1. `Update Your Kindle` で `Update_hotfix_universal.bin` をインストールする。
2. 再起動後に `Run Hotfix` booklet が表示されたら開く。
3. `;log mrpi` を検索して KUAL をインストールする。
4. KUAL を開き、KOReader を起動する。

## 内容

| パス | 目的 |
| --- | --- |
| `docs/paperwhite2-5.12.2.2-koreader-jailbreak.md` | jailbreak と KOReader の完全な手順 |
| `docs/package-manifest.md` | 再現可能なパッケージ URL と SHA-256 |
| `scripts/` | 検出、staging、eject、検証、LinguaLeaf 同期ヘルパー |
| `references/lingualleaf-koreader-sync.md` | KOReader PDF 同期メモと観測された端末挙動 |
| `firmware/` | firmware メモ用の予約領域 |
| `logs/downloads.sha256` | 記録済みパッケージハッシュ |

ローカルの `downloads/`、`packages/`、`staging/`、`device-backups/` は無視されます。

## クイックスタート

```bash
./scripts/check-downloads.sh
./scripts/build-staging.sh
./scripts/detect-kindle.sh
./scripts/stage-winterbreak2.sh
./scripts/stage-post-jailbreak.sh
```

マウント先が分かっている場合:

```bash
./scripts/stage-winterbreak2.sh /media/lachlan/Kindle
./scripts/stage-post-jailbreak.sh /media/lachlan/Kindle
```

## LinguaLeaf 同期

```bash
./scripts/sync-lingualleaf-books.sh --all
```

ソースフォルダは上書きできます。

```bash
LINGUALEAF_COLOR_DIR="/path/to/en-main-color" \
LINGUALEAF_BLACKWHITE_DIR="/path/to/en-main-blackwhite" \
./scripts/sync-lingualleaf-books.sh --all
```

## 検証

```bash
bash -n scripts/*.sh
git diff --check
./scripts/detect-kindle.sh --help
```

## 範囲

このワークフローは、自分が所有する Kindle で KOReader などの homebrew を動かすためのものです。DRM removal のための手順ではありません。必要な時以外は Airplane Mode を維持し、意図しない OTA update を避け、USB 転送前に KOReader を終了してください。

## 引用

研究や文書でこの作業リポジトリを使う場合は、このリポジトリを引用してください。GitHub は [CITATION.cff](../CITATION.cff) を読み取り、リポジトリページに **Cite this repository** パネルを表示します。

```bibtex
@software{chen_kindle_2026,
  author = {Chen, Lachlan},
  title = {Kindle: Kindle Paperwhite 2 Jailbreak and KOReader Setup Workspace},
  year = {2026},
  url = {https://github.com/lachlanchen/Kindle}
}
```
