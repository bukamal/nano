# Phase 7.2 — إصلاح تعارض file_picker في بناء Android

## الخطأ

فشل `flet build apk` عند حل حزم Flutter بسبب تعارض مباشر:

- Flet `0.28.3` يطلب `file_picker ^10.1.9`.
- إضافة `flet_native_files` كانت تطلب `file_picker ^8.3.7`.
- لا يوجد إصدار واحد يحقق الشرطين، لذلك توقف Dart Pub قبل مرحلة Gradle.

## الإصلاح

- تثبيت `file_picker: 10.1.9` داخل `flet_native_files` لضمان تطابق حتمي مع نطاق Flet 0.28.3.
- رفع إصدار إضافة Python/Flutter من `0.1.0` إلى `0.1.1` لمنع Cache أو metadata قديمة.
- رفع التطبيق إلى `0.7.1` ورقم البناء إلى `8`.
- تحديث GitHub Actions وAPK preflight واختبارات العقد بنفس أرقام الإصدار.
- إضافة `phase7_2_flutter_dependency_alignment_smoke_test.py` لمنع عودة القيد القديم `^8.3.7`.
- تشديد اختبار Wheel ليتحقق أن Flutter payload يحتوي `file_picker: 10.1.9` فعليًا.
- إزالة مجلدات build وegg-info المولدة من الحزمة النهائية حتى لا تحمل Metadata قديمة.

## لماذا لم يتغير كود Dart؟

الاستدعاء الحالي:

```dart
FilePicker.platform.pickFiles(...)
```

متوافق مع `file_picker 10.1.9`، لذلك لا توجد حاجة لتغيير منطق اختيار الملفات في هذه المرحلة.

## النتائج

نجحت بوابة الجودة كاملة بعد الإصلاح، بما فيها:

- `phase7_native_extension_packaging_smoke_test`
- `phase7_2_flutter_dependency_alignment_smoke_test`
- `apk_release_preflight`
- جميع اختبارات Phase 1–7

لم يتم تنفيذ `flutter build apk` داخل بيئة ChatGPT الحالية لعدم توفر Flutter SDK محليًا؛ التحقق النهائي من Pub/Gradle يتم في GitHub Actions.
