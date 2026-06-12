[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

[![LazyingArt banner](https://github.com/lachlanchen/lachlanchen/raw/main/figs/banner.png)](https://github.com/lachlanchen/lachlanchen/blob/main/figs/banner.png)

# Kindle

*面向韌體 `5.12.2.2` 的 Kindle Paperwhite 2 越獄與 KOReader 可重現工作區。*

[![Website](https://img.shields.io/badge/LazyingArt-lazying.art-0EA5E9?style=for-the-badge)](https://lazying.art)
[![Device](https://img.shields.io/badge/Device-Kindle%20PW2-64748B?style=for-the-badge)](../docs/paperwhite2-5.12.2.2-koreader-jailbreak.md)
[![Workflow](https://img.shields.io/badge/Workflow-WinterBreak2%20%2B%20KOReader-16A34A?style=for-the-badge)](../docs/package-manifest.md)
[![Sponsor](https://img.shields.io/badge/Sponsor-lachlanchen-EA4AAA?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/lachlanchen)

本倉庫記錄 Lachlan 的 Kindle Paperwhite 第 6 代 / PW2 工作流程：WinterBreak2 越獄暫存、Universal Hotfix、MRPI、KUAL、KOReader，以及 LinguaLeaf PDF 同步輔助腳本。倉庫只追蹤可重現腳本、校驗和與說明；下載封包、解壓套件、暫存樹和裝置備份會被忽略。

| Donate | PayPal | Stripe |
| --- | --- | --- |
| [![Donate](https://img.shields.io/badge/Donate-LazyingArt-0EA5E9?style=for-the-badge&logo=kofi&logoColor=white)](https://chat.lazying.art/donate) | [![PayPal](https://img.shields.io/badge/PayPal-RongzhouChen-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/RongzhouChen) | [![Stripe](https://img.shields.io/badge/Stripe-Donate-635BFF?style=for-the-badge&logo=stripe&logoColor=white)](https://buy.stripe.com/aFadR8gIaflgfQV6T4fw400) |

## 狀態

電腦端暫存已完成。Kindle 上還需要執行：

1. 使用 `Update Your Kindle` 安裝 `Update_hotfix_universal.bin`。
2. 重啟後如出現 `Run Hotfix` 小冊子，請開啟它。
3. 搜尋 `;log mrpi` 安裝 KUAL。
4. 開啟 KUAL 並啟動 KOReader。

## 內容

| 路徑 | 用途 |
| --- | --- |
| `docs/paperwhite2-5.12.2.2-koreader-jailbreak.md` | 完整越獄與 KOReader 流程 |
| `docs/package-manifest.md` | 可重現的套件 URL 與 SHA-256 校驗和 |
| `scripts/` | 偵測、暫存、退出、校驗與 LinguaLeaf 同步腳本 |
| `references/lingualleaf-koreader-sync.md` | KOReader PDF 同步說明與裝置行為記錄 |
| `firmware/` | 預留韌體說明 |
| `logs/downloads.sha256` | 已記錄的套件雜湊 |

本地忽略目錄包括 `downloads/`、`packages/`、`staging/` 和 `device-backups/`。

## 快速開始

```bash
./scripts/check-downloads.sh
./scripts/build-staging.sh
./scripts/detect-kindle.sh
./scripts/stage-winterbreak2.sh
./scripts/stage-post-jailbreak.sh
```

如果自動偵測失敗但已知掛載根目錄：

```bash
./scripts/stage-winterbreak2.sh /media/lachlan/Kindle
./scripts/stage-post-jailbreak.sh /media/lachlan/Kindle
```

## LinguaLeaf 同步

```bash
./scripts/sync-lingualleaf-books.sh --all
```

可覆寫來源目錄：

```bash
LINGUALEAF_COLOR_DIR="/path/to/en-main-color" \
LINGUALEAF_BLACKWHITE_DIR="/path/to/en-main-blackwhite" \
./scripts/sync-lingualleaf-books.sh --all
```

## 驗證

```bash
bash -n scripts/*.sh
git diff --check
./scripts/detect-kindle.sh --help
```

## 範圍

此流程用於在個人擁有的 Kindle 上執行 KOReader 等 homebrew。它不是 DRM 移除流程。除非需要 Wi-Fi，否則保持飛航模式；避免意外 OTA 更新；USB 傳輸前退出 KOReader。

## 引用

如果你在研究或文件中使用本工作區，請引用此倉庫。GitHub 會讀取 [CITATION.cff](../CITATION.cff)，並在倉庫頁面顯示 **Cite this repository** 面板。

```bibtex
@software{chen_kindle_2026,
  author = {Chen, Lachlan},
  title = {Kindle: Kindle Paperwhite 2 Jailbreak and KOReader Setup Workspace},
  year = {2026},
  url = {https://github.com/lachlanchen/Kindle}
}
```
