[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

[![LazyingArt banner](https://github.com/lachlanchen/lachlanchen/raw/main/figs/banner.png)](https://github.com/lachlanchen/lachlanchen/blob/main/figs/banner.png)

# Kindle

*Không gian làm việc có thể tái lập cho jailbreak Kindle Paperwhite 2 và thiết lập KOReader trên firmware `5.12.2.2`.*

[![Website](https://img.shields.io/badge/LazyingArt-lazying.art-0EA5E9?style=for-the-badge)](https://lazying.art)
[![Device](https://img.shields.io/badge/Device-Kindle%20PW2-64748B?style=for-the-badge)](../docs/paperwhite2-5.12.2.2-koreader-jailbreak.md)
[![Workflow](https://img.shields.io/badge/Workflow-WinterBreak2%20%2B%20KOReader-16A34A?style=for-the-badge)](../docs/package-manifest.md)
[![Sponsor](https://img.shields.io/badge/Sponsor-lachlanchen-EA4AAA?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/lachlanchen)

Kho này ghi lại quy trình của Lachlan cho Kindle Paperwhite 6th generation / PW2: staging WinterBreak2, Universal Hotfix, MRPI, KUAL, KOReader và công cụ đồng bộ PDF LinguaLeaf. Kho chỉ theo dõi script có thể tái lập, checksum và ghi chú; archive tải xuống, gói đã giải nén, cây staging và bản sao lưu thiết bị được cố ý bỏ qua.

| Donate | PayPal | Stripe |
| --- | --- | --- |
| [![Donate](https://img.shields.io/badge/Donate-LazyingArt-0EA5E9?style=for-the-badge&logo=kofi&logoColor=white)](https://chat.lazying.art/donate) | [![PayPal](https://img.shields.io/badge/PayPal-RongzhouChen-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/RongzhouChen) | [![Stripe](https://img.shields.io/badge/Stripe-Donate-635BFF?style=for-the-badge&logo=stripe&logoColor=white)](https://buy.stripe.com/aFadR8gIaflgfQV6T4fw400) |

## Trạng thái

Phần staging trên máy tính đã hoàn tất. Các bước còn lại trên Kindle là:

1. Cài `Update_hotfix_universal.bin` bằng `Update Your Kindle`.
2. Sau khi khởi động lại, mở booklet `Run Hotfix` nếu nó xuất hiện.
3. Tìm `;log mrpi` để cài KUAL.
4. Mở KUAL và chạy KOReader.

## Nội dung

| Đường dẫn | Mục đích |
| --- | --- |
| `docs/paperwhite2-5.12.2.2-koreader-jailbreak.md` | Quy trình jailbreak và KOReader đầy đủ |
| `docs/package-manifest.md` | URL gói và SHA-256 có thể tái lập |
| `scripts/` | Công cụ phát hiện, staging, eject, checksum và đồng bộ |
| `references/lingualleaf-koreader-sync.md` | Ghi chú đồng bộ PDF và hành vi thiết bị đã quan sát |
| `firmware/` | Ghi chú firmware dự phòng |
| `logs/downloads.sha256` | Hash gói đã ghi lại |

Các thư mục cục bộ `downloads/`, `packages/`, `staging/` và `device-backups/` bị bỏ qua.

## Bắt đầu nhanh

```bash
./scripts/check-downloads.sh
./scripts/build-staging.sh
./scripts/detect-kindle.sh
./scripts/stage-winterbreak2.sh
./scripts/stage-post-jailbreak.sh
```

Nếu biết sẵn thư mục mount:

```bash
./scripts/stage-winterbreak2.sh /media/lachlan/Kindle
./scripts/stage-post-jailbreak.sh /media/lachlan/Kindle
```

## Đồng bộ LinguaLeaf

```bash
./scripts/sync-lingualleaf-books.sh --all
```

Có thể ghi đè thư mục nguồn:

```bash
LINGUALEAF_COLOR_DIR="/path/to/en-main-color" \
LINGUALEAF_BLACKWHITE_DIR="/path/to/en-main-blackwhite" \
./scripts/sync-lingualleaf-books.sh --all
```

## Kiểm tra

```bash
bash -n scripts/*.sh
git diff --check
./scripts/detect-kindle.sh --help
```

## Phạm vi

Quy trình này dùng để chạy homebrew như KOReader trên Kindle cá nhân. Đây không phải quy trình gỡ DRM. Giữ Airplane Mode trừ khi cần Wi-Fi, tránh OTA ngoài ý muốn và thoát KOReader trước khi truyền file qua USB.

## Trích dẫn

Nếu bạn dùng không gian làm việc này trong nghiên cứu hoặc tài liệu, hãy trích dẫn kho này. GitHub đọc [CITATION.cff](../CITATION.cff) và hiển thị bảng **Cite this repository** trên trang kho.

```bibtex
@software{chen_kindle_2026,
  author = {Chen, Lachlan},
  title = {Kindle: Kindle Paperwhite 2 Jailbreak and KOReader Setup Workspace},
  year = {2026},
  url = {https://github.com/lachlanchen/Kindle}
}
```
