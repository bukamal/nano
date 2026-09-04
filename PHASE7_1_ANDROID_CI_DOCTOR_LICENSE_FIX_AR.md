# Phase 7.1 — إصلاح بيئة Android CI وFlutter Doctor

## المشكلة

ظهر في GitHub Actions أن `flet build apk` انتهى بخطأ ثم قضى وقتًا طويلًا في إعادة تشغيل `flutter doctor`. أظهر Doctor أيضًا أن بعض تراخيص Android SDK غير مقبولة.

مهم: `flutter doctor` الذي يظهر بعد رسالة `Error building Flet app` هو تشخيص لاحق للفشل، ولذلك لا يثبت أن التراخيص كانت السبب الأول الوحيد. المقتطف المرسل لا يحتوي أول أمر فشل قبل Doctor.

## الإصلاح

- إعداد Java 17 صراحة عبر `actions/setup-java@v4`.
- تحديد `ANDROID_HOME` و`ANDROID_SDK_ROOT` من Android SDK الموجود على GitHub runner.
- اكتشاف `sdkmanager` بطريقة متينة.
- تثبيت/التحقق من `cmdline-tools;latest`, `platform-tools`, `platforms;android-35`, `build-tools;34.0.0`.
- قبول جميع Android SDK licenses قبل تشغيل Flet.
- إضافة `FLET_CLI_NO_RICH_OUTPUT=1` لسجل CI أبسط.
- إضافة `FLET_CLI_SKIP_FLUTTER_DOCTOR=1` وتمرير `--skip-flutter-doctor` إلى `flet build` حتى لا يضيع وقت طويل في Doctor بعد أي فشل مستقل.
- حفظ كامل خرج `flet build` في `flet-build.log` مع `pipefail` للحفاظ على exit code الحقيقي.
- رفع سجل البناء كـArtifact دائمًا حتى عند فشل المهمة.
- تحديد `timeout-minutes: 60` حتى لا تستمر مهمة تالفة لساعات.

## ما نتوقعه في التشغيل القادم

إذا كانت المشكلة الوحيدة هي التراخيص، سيكمل Flet إلى مراحل إنشاء Flutter/Gradle. إذا بقي خطأ آخر، ستنتهي المهمة مباشرة عند أول خطأ حقيقي، وسيكون `qeid-flet-build-log` متاحًا بدل تكرار Flutter Doctor لساعات.
