[English](../README.md) · [العربية](README.ar.md) · [Español](README.es.md) · [Français](README.fr.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Tiếng Việt](README.vi.md) · [中文 (简体)](README.zh-Hans.md) · [中文（繁體）](README.zh-Hant.md) · [Deutsch](README.de.md) · [Русский](README.ru.md)

[![LazyingArt banner](https://github.com/lachlanchen/lachlanchen/raw/main/figs/banner.png)](https://github.com/lachlanchen/lachlanchen/blob/main/figs/banner.png)

# Kindle

*مساحة عمل قابلة لإعادة الإنتاج لعمل jailbreak لجهاز Kindle Paperwhite 2 وإعداد KOReader على firmware `5.12.2.2`.*

[![Website](https://img.shields.io/badge/LazyingArt-lazying.art-0EA5E9?style=for-the-badge)](https://lazying.art)
[![Device](https://img.shields.io/badge/Device-Kindle%20PW2-64748B?style=for-the-badge)](../docs/paperwhite2-5.12.2.2-koreader-jailbreak.md)
[![Workflow](https://img.shields.io/badge/Workflow-WinterBreak2%20%2B%20KOReader-16A34A?style=for-the-badge)](../docs/package-manifest.md)
[![Sponsor](https://img.shields.io/badge/Sponsor-lachlanchen-EA4AAA?style=for-the-badge&logo=githubsponsors&logoColor=white)](https://github.com/sponsors/lachlanchen)

يوثق هذا المستودع سير عمل Lachlan لجهاز Kindle Paperwhite 6th generation / PW2: تجهيز WinterBreak2، وUniversal Hotfix، وMRPI، وKUAL، وKOReader، وأدوات مزامنة ملفات PDF الخاصة بـ LinguaLeaf. يتتبع المستودع السكربتات القابلة لإعادة الإنتاج، وقيم التحقق، والملاحظات فقط؛ أما الأرشيفات التي تم تنزيلها والحزم المستخرجة وأشجار staging ونسخ الجهاز الاحتياطية فهي مستبعدة عمدا.

| Donate | PayPal | Stripe |
| --- | --- | --- |
| [![Donate](https://img.shields.io/badge/Donate-LazyingArt-0EA5E9?style=for-the-badge&logo=kofi&logoColor=white)](https://chat.lazying.art/donate) | [![PayPal](https://img.shields.io/badge/PayPal-RongzhouChen-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/RongzhouChen) | [![Stripe](https://img.shields.io/badge/Stripe-Donate-635BFF?style=for-the-badge&logo=stripe&logoColor=white)](https://buy.stripe.com/aFadR8gIaflgfQV6T4fw400) |

## الحالة

اكتمل التجهيز من جهة الكمبيوتر. الخطوات المتبقية على Kindle هي:

1. تثبيت `Update_hotfix_universal.bin` عبر `Update Your Kindle`.
2. بعد إعادة التشغيل، افتح كتيب `Run Hotfix` إذا ظهر.
3. ابحث عن `;log mrpi` لتثبيت KUAL.
4. افتح KUAL ثم شغل KOReader.

## المحتويات

| المسار | الغرض |
| --- | --- |
| `docs/paperwhite2-5.12.2.2-koreader-jailbreak.md` | الإجراء الكامل لـ jailbreak وKOReader |
| `docs/package-manifest.md` | روابط الحزم وقيم SHA-256 القابلة لإعادة الإنتاج |
| `scripts/` | أدوات الكشف والتجهيز والإخراج والتحقق والمزامنة |
| `references/lingualleaf-koreader-sync.md` | ملاحظات مزامنة PDF وسلوك الجهاز المرصود |
| `firmware/` | ملاحظات firmware محجوزة |
| `logs/downloads.sha256` | قيم hash المسجلة للحزم |

يتم تجاهل المجلدات المحلية `downloads/` و`packages/` و`staging/` و`device-backups/`.

## البدء السريع

```bash
./scripts/check-downloads.sh
./scripts/build-staging.sh
./scripts/detect-kindle.sh
./scripts/stage-winterbreak2.sh
./scripts/stage-post-jailbreak.sh
```

إذا كان مسار mount معروفا:

```bash
./scripts/stage-winterbreak2.sh /media/lachlan/Kindle
./scripts/stage-post-jailbreak.sh /media/lachlan/Kindle
```

## مزامنة LinguaLeaf

```bash
./scripts/sync-lingualleaf-books.sh --all
```

يمكن استبدال مجلدات المصدر:

```bash
LINGUALEAF_COLOR_DIR="/path/to/en-main-color" \
LINGUALEAF_BLACKWHITE_DIR="/path/to/en-main-blackwhite" \
./scripts/sync-lingualleaf-books.sh --all
```

## التحقق

```bash
bash -n scripts/*.sh
git diff --check
./scripts/detect-kindle.sh --help
```

## النطاق

هذا workflow مخصص لتشغيل homebrew مثل KOReader على Kindle تملكه شخصيا. ليس workflow لإزالة DRM. أبق Airplane Mode مفعلا ما لم تكن بحاجة إلى Wi-Fi، وتجنب تحديثات OTA غير المقصودة، واخرج من KOReader قبل نقل الملفات عبر USB.

## الاستشهاد

إذا استخدمت مساحة العمل هذه في بحث أو توثيق، فاستشهد بالمستودع. يقرأ GitHub ملف [CITATION.cff](../CITATION.cff) ويعرض لوحة **Cite this repository** في صفحة المستودع.

```bibtex
@software{chen_kindle_2026,
  author = {Chen, Lachlan},
  title = {Kindle: Kindle Paperwhite 2 Jailbreak and KOReader Setup Workspace},
  year = {2026},
  url = {https://github.com/lachlanchen/Kindle}
}
```
