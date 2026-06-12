[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

[![LazyingArt banner](https://github.com/lachlanchen/lachlanchen/raw/main/figs/banner.png)](https://github.com/lachlanchen/lachlanchen/blob/main/figs/banner.png)

# Kindle

*面向固件 `5.12.2.2` 的 Kindle Paperwhite 2 越狱与 KOReader 可复现工作区。*

[![Website](https://img.shields.io/badge/LazyingArt-lazying.art-0EA5E9?style=for-the-badge)](https://lazying.art)
[![Device](https://img.shields.io/badge/Device-Kindle%20PW2-64748B?style=for-the-badge)](../docs/paperwhite2-5.12.2.2-koreader-jailbreak.md)
[![Workflow](https://img.shields.io/badge/Workflow-WinterBreak2%20%2B%20KOReader-16A34A?style=for-the-badge)](../docs/package-manifest.md)
[![Sponsor](https://img.shields.io/badge/Sponsor-lachlanchen-EA4AAA?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/lachlanchen)

本仓库记录 Lachlan 的 Kindle Paperwhite 第 6 代 / PW2 工作流：WinterBreak2 越狱暂存、Universal Hotfix、MRPI、KUAL、KOReader，以及 LinguaLeaf PDF 同步辅助脚本。仓库只跟踪可复现脚本、校验和与说明；下载包、解压包、暂存树和设备备份会被忽略。

| Donate | PayPal | Stripe |
| --- | --- | --- |
| [![Donate](https://img.shields.io/badge/Donate-LazyingArt-0EA5E9?style=for-the-badge&logo=kofi&logoColor=white)](https://chat.lazying.art/donate) | [![PayPal](https://img.shields.io/badge/PayPal-RongzhouChen-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/RongzhouChen) | [![Stripe](https://img.shields.io/badge/Stripe-Donate-635BFF?style=for-the-badge&logo=stripe&logoColor=white)](https://buy.stripe.com/aFadR8gIaflgfQV6T4fw400) |

## 状态

电脑端暂存已经完成。Kindle 上还需要执行：

1. 用 `Update Your Kindle` 安装 `Update_hotfix_universal.bin`。
2. 重启后如果出现 `Run Hotfix` 小册子，请打开它。
3. 搜索 `;log mrpi` 安装 KUAL。
4. 打开 KUAL 并启动 KOReader。

## 内容

| 路径 | 用途 |
| --- | --- |
| `docs/paperwhite2-5.12.2.2-koreader-jailbreak.md` | 完整越狱与 KOReader 流程 |
| `docs/package-manifest.md` | 可复现的包 URL 与 SHA-256 校验和 |
| `scripts/` | 检测、暂存、弹出、校验和 LinguaLeaf 同步脚本 |
| `references/lingualleaf-koreader-sync.md` | KOReader PDF 同步说明与设备行为记录 |
| `firmware/` | 预留固件说明 |
| `logs/downloads.sha256` | 已记录的包哈希 |

本地忽略目录包括 `downloads/`、`packages/`、`staging/` 和 `device-backups/`。

## 快速开始

```bash
./scripts/check-downloads.sh
./scripts/build-staging.sh
./scripts/detect-kindle.sh
./scripts/stage-winterbreak2.sh
./scripts/stage-post-jailbreak.sh
```

如果自动检测失败但已知挂载根目录：

```bash
./scripts/stage-winterbreak2.sh /media/lachlan/Kindle
./scripts/stage-post-jailbreak.sh /media/lachlan/Kindle
```

## LinguaLeaf 同步

```bash
./scripts/sync-lingualleaf-books.sh --all
```

可覆盖源目录：

```bash
LINGUALEAF_COLOR_DIR="/path/to/en-main-color" \
LINGUALEAF_BLACKWHITE_DIR="/path/to/en-main-blackwhite" \
./scripts/sync-lingualleaf-books.sh --all
```

## 验证

```bash
bash -n scripts/*.sh
git diff --check
./scripts/detect-kindle.sh --help
```

## 范围

此流程用于在个人拥有的 Kindle 上运行 KOReader 等 homebrew。它不是 DRM 移除流程。除非需要 Wi-Fi，否则保持飞行模式；避免意外 OTA 更新；USB 传输前退出 KOReader。

## 引用

如果你在研究或文档中使用本工作区，请引用该仓库。GitHub 会读取 [CITATION.cff](../CITATION.cff)，并在仓库页面显示 **Cite this repository** 面板。

```bibtex
@software{chen_kindle_2026,
  author = {Chen, Lachlan},
  title = {Kindle: Kindle Paperwhite 2 Jailbreak and KOReader Setup Workspace},
  year = {2026},
  url = {https://github.com/lachlanchen/Kindle}
}
```
