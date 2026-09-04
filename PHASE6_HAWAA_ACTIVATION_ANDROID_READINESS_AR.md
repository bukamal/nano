# Phase 6 — ربط تفعيل هوى الشام وتجهيز Android

## الهدف

ربط مشروع «قيد أوفلاين» بنفس سيرفر التفعيل المستخدم فعليًا في «هوى الشام»، مع إزالة عقد التفعيل الافتراضي السابق، وتحويل التفعيل إلى بوابة تشغيل حقيقية، ثم إصلاح موقع قاعدة البيانات ليكون مناسبًا لـAndroid وتجهيز CI لبناء APK.

## 1. نفس سيرفر هوى الشام

تم اعتماد Endpoint نفسه:

`https://license.manhal-almasriiii199119.workers.dev/activate`

وعقد الطلب نفسه حرفيًا:

```json
{
  "licenseCode": "LICENSE-KEY",
  "fingerprint": "DEVICE-FINGERPRINT"
}
```

لا يتم إرسال `app_version` لأن السيرفر الحالي لهوى الشام لا يحتاجه في العقد الفعلي.

## 2. Fingerprint متوافق مع هوى الشام

تم اعتماد نفس خوارزمية العميل الحالي لهوى الشام:

- اسم الجهاز.
- المعالج.
- اسم مستخدم النظام.
- نظام التشغيل.
- بنية الجهاز.
- SHA-256 للتركيب النهائي.

الهدف هو أن يكون سلوك الربط بالجهاز متوافقًا مع نفس منظومة الترخيص بدل استخدام UUID عشوائي خاص بقيد.

## 3. الاستجابة والانتهاء

العميل يدعم نفس أسماء حقول الانتهاء الموجودة في عميل هوى الشام:

- `expirationDate`
- `expiration`
- `expiresAt`

ويدعم:

- تواريخ ISO.
- Unix timestamp بالثواني أو milliseconds.
- `lifetime / unlimited / permanent / never`.
- المقابلات العربية مثل «غير محدود» و«مدى الحياة».

## 4. العمل أوفلاين بعد التفعيل

بعد نجاح طلب التفعيل:

- تحفظ نتيجة التفعيل داخل `license_state`.
- تربط البيانات بالـFingerprint الحالي.
- تغلف محليًا باستخدام PBKDF2 + XOR + HMAC-SHA256 لاكتشاف تعديل البيانات المحلية وربطها بالجهاز.
- `status()` لا يجري أي طلب إنترنت.

اختبار Phase 6 يمنع الشبكة صراحة بعد التفعيل ويتأكد أن إعادة إنشاء `LicenseService` ما زالت تعتبر الترخيص صالحًا.

### قيد أمني مهم

سيرفر هوى الشام الحالي لا يعيد Signed Token أو توقيعًا عامًا يمكن التحقق منه أوفلاين. لذلك لا يمكن للعميل وحده إثبات أن Payload المحلية صدرت تشفيريًا من السيرفر بعد انقطاع الإنترنت. الحماية الحالية مناسبة للتوافق مع النظام الحالي وتكشف تعديل الملفات المعتاد، لكن مقاومة Reverse Engineering الكاملة تحتاج تحديث بروتوكول السيرفر نفسه ليصدر توقيعًا تشفيريًا.

## 5. بوابة التفعيل

أضيفت `ActivationGate` قبل شاشة المستخدمين.

تسلسل التشغيل الآن:

1. فتح قاعدة البيانات المحلية.
2. فحص الترخيص محليًا.
3. إذا كان صالحًا: الانتقال إلى تسجيل الدخول المحلي.
4. إذا كان مفقودًا/غير صالح/منتهيًا: عرض شاشة «تفعيل قيد».
5. التفعيل عبر نفس Worker الخاص بهوى الشام.
6. بعد النجاح: الانتقال مباشرة إلى إنشاء المدير أو تسجيل الدخول.

لم يعد عنوان السيرفر أو RSA Public Key قابلًا للتعديل من شاشة الإدارة؛ السيرفر هو سيرفر هوى الشام نفسه.

## 6. بيانات Android الدائمة

في Phase 1–5 كان المسار الافتراضي للقاعدة مشتقًا من Source Tree، وهو غير مناسب كتخزين دائم لتطبيق Android معبأ.

أضيف:

`nano_offline.core.paths`

والأولوية أصبحت:

1. `FLET_APP_STORAGE_DATA` على Flet Android.
2. `QEID_DATA_DIR` للتطوير والاختبار.
3. `~/.qeid` على Desktop كـFallback.

قاعدة البيانات:

`<app-data>/qeid.db`

والنسخ الاحتياطية:

`<app-data>/backups/`

## 7. ترحيل Phase 1–5

أضيف `migrate_legacy_database()`.

إذا وجد التطبيق قاعدة قديمة في مسار Source ولم توجد قاعدة في App Storage:

- يستخدم SQLite Backup API.
- يفحص `PRAGMA integrity_check`.
- ينقلها إلى المسار الدائم.
- لا يستبدل قاعدة موجودة مسبقًا.

وبذلك لا يفقد مستخدم Desktop بيانات المراحل السابقة عند الانتقال إلى Phase 6.

## 8. Android Manifest / Flet

أضيف إلى `pyproject.toml`:

- `android.permission.INTERNET` للتفعيل فقط.
- `allowBackup = false` لمنع Android Auto Backup من نسخ قاعدة البيانات أو ترخيص الجهاز تلقائيًا إلى جهاز آخر.
- Splash/Adaptive background.

الإصدار:

- `0.6.0`
- `build_number = 6`
- `Flet 0.28.3`
- `SCHEMA_VERSION = 4` دون Migration جديد لأن بنية الجداول لم تتغير.

## 9. GitHub Actions

أضيف:

`.github/workflows/build-android-apk.yml`

ويقوم بـ:

1. Python 3.12.
2. تثبيت setuptools/wheel والمشروع.
3. تشغيل Quality Gate.
4. تشغيل APK Release Preflight.
5. `flet build apk` للإصدار 0.6.0 / build 6.
6. جمع `qeid-offline-release.apk`.
7. رفعه كـArtifact.

## 10. الاختبارات الجديدة

- `phase6_hawaa_activation_contract_smoke_test.py`
  - يتحقق من URL نفسه.
  - يتحقق أن Body يحتوي `licenseCode` و`fingerprint` فقط.
  - يمنع أي بيانات محاسبية في الطلب.
  - يثبت أن الفحص اللاحق أوفلاين.
  - يفحص انتهاء الترخيص واكتشاف العبث المحلي.

- `phase6_android_storage_smoke_test.py`
  - يفحص `FLET_APP_STORAGE_DATA`.
  - يفحص ترحيل DB القديمة باستخدام SQLite Backup API.
  - يمنع الكتابة فوق قاعدة Android موجودة.

- `phase6_activation_ui_contract_smoke_test.py`
  - يفحص وجود Activation Gate قبل Auth.
  - يفحص إزالة إعدادات RSA/URL من واجهة الإدارة.

- `phase6_android_build_contract_smoke_test.py`
  - الإصدار/build.
  - INTERNET permission.
  - allowBackup=false.
  - Workflow APK.

- `apk_release_preflight.py`
  - عقد Release ثابت قبل بناء APK.

## 11. نتيجة Quality Gate

جميع اختبارات Phase 1–6 نجحت، بما فيها:

- الحسابات والمخزون.
- الفواتير.
- الدفعات والسندات.
- التقارير التاريخية.
- المستخدمون والصلاحيات.
- النسخ والاسترجاع.
- RS256 القديم للتوافق.
- عقد سيرفر هوى الشام الجديد.
- Android Storage.
- APK Preflight.

## التالي

Phase 7 مناسبة لـ:

- تصدير واستيراد Backup فعليًا من Android خارج مساحة التطبيق.
- مشاركة Backup.
- PDF/طباعة الفواتير وكشوف الحساب.
- نموذج تكلفة الخدمات.
- تحسينات شاشة الهاتف وتجربة APK على جهاز حقيقي.
