[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

[![LazyingArt banner](https://github.com/lachlanchen/lachlanchen/raw/main/figs/banner.png)](https://github.com/lachlanchen/lachlanchen/blob/main/figs/banner.png)

# Kindle

*펌웨어 `5.12.2.2`용 Kindle Paperwhite 2 jailbreak 및 KOReader 설정을 재현하기 위한 작업 저장소입니다.*

[![Website](https://img.shields.io/badge/LazyingArt-lazying.art-0EA5E9?style=for-the-badge)](https://lazying.art)
[![Device](https://img.shields.io/badge/Device-Kindle%20PW2-64748B?style=for-the-badge)](../docs/paperwhite2-5.12.2.2-koreader-jailbreak.md)
[![Workflow](https://img.shields.io/badge/Workflow-WinterBreak2%20%2B%20KOReader-16A34A?style=for-the-badge)](../docs/package-manifest.md)
[![Sponsor](https://img.shields.io/badge/Sponsor-lachlanchen-EA4AAA?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/lachlanchen)

이 저장소는 Lachlan의 Kindle Paperwhite 6세대 / PW2 작업 흐름을 기록합니다. WinterBreak2 staging, Universal Hotfix, MRPI, KUAL, KOReader, LinguaLeaf PDF 동기화 도구가 포함됩니다. 재현 가능한 스크립트, 체크섬, 문서만 추적하며 다운로드한 아카이브, 압축 해제 패키지, staging tree, 장치 백업은 의도적으로 제외합니다.

| Donate | PayPal | Stripe |
| --- | --- | --- |
| [![Donate](https://img.shields.io/badge/Donate-LazyingArt-0EA5E9?style=for-the-badge&logo=kofi&logoColor=white)](https://chat.lazying.art/donate) | [![PayPal](https://img.shields.io/badge/PayPal-RongzhouChen-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/RongzhouChen) | [![Stripe](https://img.shields.io/badge/Stripe-Donate-635BFF?style=for-the-badge&logo=stripe&logoColor=white)](https://buy.stripe.com/aFadR8gIaflgfQV6T4fw400) |

## 상태

컴퓨터 쪽 staging은 완료되었습니다. Kindle에서 남은 작업은 다음과 같습니다.

1. `Update Your Kindle`로 `Update_hotfix_universal.bin`을 설치합니다.
2. 재부팅 후 `Run Hotfix` booklet이 보이면 엽니다.
3. `;log mrpi`를 검색해 KUAL을 설치합니다.
4. KUAL을 열고 KOReader를 실행합니다.

## 구성

| 경로 | 목적 |
| --- | --- |
| `docs/paperwhite2-5.12.2.2-koreader-jailbreak.md` | jailbreak 및 KOReader 전체 절차 |
| `docs/package-manifest.md` | 재현 가능한 패키지 URL과 SHA-256 체크섬 |
| `scripts/` | 감지, staging, eject, 체크섬, LinguaLeaf 동기화 도구 |
| `references/lingualleaf-koreader-sync.md` | KOReader PDF 동기화 메모와 관찰된 장치 동작 |
| `firmware/` | firmware 메모용 예약 공간 |
| `logs/downloads.sha256` | 기록된 패키지 해시 |

로컬 `downloads/`, `packages/`, `staging/`, `device-backups/` 폴더는 무시됩니다.

## 빠른 시작

```bash
./scripts/check-downloads.sh
./scripts/build-staging.sh
./scripts/detect-kindle.sh
./scripts/stage-winterbreak2.sh
./scripts/stage-post-jailbreak.sh
```

마운트 경로를 알고 있다면:

```bash
./scripts/stage-winterbreak2.sh /media/lachlan/Kindle
./scripts/stage-post-jailbreak.sh /media/lachlan/Kindle
```

## LinguaLeaf 동기화

```bash
./scripts/sync-lingualleaf-books.sh --all
```

소스 폴더는 환경 변수로 바꿀 수 있습니다.

```bash
LINGUALEAF_COLOR_DIR="/path/to/en-main-color" \
LINGUALEAF_BLACKWHITE_DIR="/path/to/en-main-blackwhite" \
./scripts/sync-lingualleaf-books.sh --all
```

## 검증

```bash
bash -n scripts/*.sh
git diff --check
./scripts/detect-kindle.sh --help
```

## 범위

이 작업 흐름은 개인 소유 Kindle에서 KOReader 같은 homebrew를 실행하기 위한 것입니다. DRM 제거 절차가 아닙니다. Wi-Fi가 필요하지 않으면 Airplane Mode를 유지하고, 의도하지 않은 OTA 업데이트를 피하며, USB 파일 전송 전 KOReader를 종료하세요.

## 인용

연구나 문서에서 이 작업 저장소를 사용한다면 저장소를 인용해 주세요. GitHub는 [CITATION.cff](../CITATION.cff)를 읽고 저장소 페이지에 **Cite this repository** 패널을 표시합니다.

```bibtex
@software{chen_kindle_2026,
  author = {Chen, Lachlan},
  title = {Kindle: Kindle Paperwhite 2 Jailbreak and KOReader Setup Workspace},
  year = {2026},
  url = {https://github.com/lachlanchen/Kindle}
}
```
