# PHASE10 — ودجت الشاشة الرئيسية (Jetpack Glance)

## الفكرة

امتداد لبنية PHASE9 (WorkManager + عزل خلفي يفتح SQLite مباشرة)، لا مسار جديد
مستقل. مساران للتحديث:

| الحالة | المسار | المصدر |
|---|---|---|
| التطبيق مفتوح وحدثت عملية بيع/سند | فوري عبر `push_home_widget` | `DashboardService` (بايثون، بلا استعلام SQL جديد) |
| التطبيق مغلق | دوري كل 30 دقيقة، ضمن نفس مهمة WorkManager الموجودة | فتح SQLite مباشرة داخل `_runNotificationCheck` |

المسار الفوري يرسل فقط `sales_today` و`cash_balance` (الأرقام التي تتغيّر مع
كل عملية). أما `overdue_count` و`low_stock_count` فتبقى من اختصاص المسار
الدوري وحده، لأنه يطبّق قواعد "متأخر بعد كم يوم" و"حد المخزون الأدنى" من
إعدادات التنبيهات في `notification_service.py` — تكرار هذا المنطق في بايثون
كان سيخاطر باختلاف الجانبين حول تعريف "متأخر". لهذا `NanoHomeWidgetPlugin.kt`
يدمج (merge) كل تحديث بدل استبدال الحالة كاملة، حتى لا يمسح تحديثٌ فوري
أرقام التنبيهات التي وضعها آخر تمرير دوري.

## الملفات المضافة/المعدَّلة

```
extensions/flet_native_files/src/flutter/flet_native_files/
  pubspec.yaml                                    [تعديل: تسجيل plugin.platforms.android]
  lib/src/native_files.dart                        [تعديل: push_home_widget + _pushHomeWidgetSnapshot]
  android/build.gradle                             [جديد]
  android/src/main/AndroidManifest.xml             [جديد]
  android/src/main/res/xml/nano_widget_info.xml    [جديد]
  android/src/main/kotlin/com/nano/homewidget/
    NanoGlanceWidget.kt                            [جديد]
    NanoWidgetReceiver.kt                          [جديد]
    NanoHomeWidgetPlugin.kt                        [جديد]

extensions/flet_native_files/src/flet_native_files/native_files.py  [تعديل: push_home_widget()]
src/nano_offline/core/home_widget.py                                 [جديد]
src/nano_offline/views/invoice_view.py                                [تعديل: استدعاء بعد حفظ فاتورة بيع]
src/nano_offline/views/finance_view.py                                [تعديل: استدعاء بعد حفظ سند]
tools/verify_flet_native_files_registration.py                       [تعديل: فحص دمج الـreceiver]
```

## لماذا بيان الودجت لا يحتاج تعديل ملف مُولَّد

`android/src/main/AndroidManifest.xml` هنا هو بيان **وحدة مكتبة (plugin
module)**، لا بيان التطبيق. Gradle يدمجه تلقائيًا داخل
`build/flutter/android/app/.../AndroidManifest.xml` النهائي في كل بناء —
نفس الآلية التي تسجّل بها `flutter_local_notifications` و`workmanager`
عناصرهما، بلا أي حاجة لتعديل ملف مُولَّد كما حصل مع مشكلة
`compileOptions`/desugaring في `build_nano_apk.sh`.

## خطوات التحقق قبل أول بناء APK فعلي

1. `flet build apk --build-version <x> --build-number <y>`
2. `python tools/verify_flet_native_files_registration.py build/flutter`
   — الآن يتحقق أيضًا من وجود `com.nano.homewidget.NanoWidgetReceiver` في
   البيان النهائي المُدمَج.
3. تثبيت الـAPK وإضافة الودجت يدويًا لأول مرة من قائمة ودجت أندرويد
   (لا يوجد آلية لتثبيتها تلقائيًا أول مرة، هذا سلوك أندرويد نفسه).
4. تنفيذ عملية بيع أو سند من داخل التطبيق والتأكد أن الودجت تتحدّث فورًا
   دون إغلاق التطبيق.
5. إغلاق التطبيق تمامًا (Force stop) والانتظار لتأكيد أن التمرير الدوري
   لا يزال يحدّث الأرقام (نفس اختبار "أغلق وانتظر" المستخدم فعليًا لـPHASE9
   عبر `schedule_test_notification`).

## حدود معروفة

- لم يُبنَ APK فعليًا في بيئة التطوير الحالية (لا تتوفر Flutter/Gradle
  Runtime كاملة هنا) — هذا امتداد لنفس القيد المذكور في `README.md` تحت
  "حدود المرحلة الحالية".
- إصدارات `androidx.glance`/`kotlinx-coroutines` في `android/build.gradle`
  قيم معقولة حالية وقد تحتاج تحديثًا بحسب إصدار Android Gradle Plugin الذي
  يستخدمه `flet build apk` فعليًا وقت البناء.
