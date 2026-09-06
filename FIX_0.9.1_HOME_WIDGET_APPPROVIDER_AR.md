# Nano 0.9.1 — الودجت بلا طبقة Glance: إعادة بناء على AppWidgetProvider

## المشكلة

الودجت ما زالت تعرض "يتعذّر عرض المحتوى" رغم كل إصلاحات 0.8.2–0.8.5.

## التشخيص (من الكود والملاحظات الموثّقة في الشجرة)

1. **الاحتمال الأول والأسهل للتحقق: الـAPK المثبّت قديم.** `build_nano_apk.sh`
   كان ما زال يبني بـ `--build-version 0.8.1 --build-number 14` — أي أن أي
   APK مبني بهذا السكربت **لا يحتوي أيًا من إصلاحات الودجت من 0.8.2 فما
   بعد**، ويعيد بالضبط سلوك 0.8.1 (رسالة "تعذّر عرض المحتوى" الثابتة).
   هذا الإصلاح يرفع الأرقام إلى `0.9.1 / build 22` في السكربت و`pyproject.toml`
   و`version.py` و`README.md`. **قبل أي شيء: تحقّق من رقم الإصدار المثبّت**
   (إعدادات أندرويد ← التطبيقات ← نانو): إن كان 0.8.1/14 أو أقل فهذا وحده
   يفسّر كل شيء.

2. **الاحتمال الثاني — موثّق فعليًا في FIX_0.8.4/0.8.5:** لو كان الـAPK
   حديثًا، أثبتت لوحة التشخيص أن `widget_count = 1` وأن الـpush يصل ويُدمج
   في الحالة المحفوظة، **لكن `provideGlance` لم تُستدعَ ولو مرة واحدة**.
   عطل بهذا العمق يقع داخل آلية جلسة Glance نفسها
   (`GlanceAppWidgetReceiver → AppWidgetSession → RemoteViewsService`) —
   طبقة مكتبة خارجية لا يصلها أي try/catch من كود المشروع، ولا يمكن
   معالجتها من داخل كود التطبيق على هذا المكدّس (هذا بالضبط ما خلصت إليه
   0.8.5).

## الحل

استبدال Jetpack Glance بالكامل بمكوّن `AppWidgetProvider` عادي يرسل
`RemoteViews` مباشرة:

- الرسم يتم في `onUpdate()` بمكتبة أندرويد الأساسية فقط
  (`android.appwidget` / `android.widget`): **إذا نُفّذ `onUpdate` فستُرسَم
  الودجت** — لا آلية جلسة، لا Compose، لا inliner، لا DataStore.
- عقد الجسر لم يتغيّر: نفس القناة `nano/home_widget` ونفس الطريقتين
  `push`/`diagnose` ونفس مفاتيح JSON (`sales_today` / `cash_balance` /
  `overdue_count` / `low_stock_count`). لهذا `core/home_widget.py` و
  `native_files.py` و`native_files.dart` **بلا أي تعديل**.
- التخزين انتقل من Preferences DataStore الخاص بـ Glance إلى مفتاح
  `SharedPreferences` واحد، مع نفس دلالات الدمج لكل مفتاح: المسار الفوري
  (بيع/سند) لا يمسح أرقام التنبيهات التي وضعها التمرير الدوري.
- تُحفَظ الميزات: النقر لفتح التطبيق (reflection محمي يفشل بصمت إن تعذّر)،
  المعاينة والوصف في منتقي الودجت، التحديث الدوري 30 دقيقة من النظام +
  تمرير WorkManager عند إغلاق التطبيق، وزر Quick Settings.

## الملفات المعدَّلة

```
extensions/flet_native_files/src/flutter/flet_native_files/android/src/main/
  kotlin/com/nano/homewidget/NanoWidgetReceiver.kt      [أعيدت كتابته: AppWidgetProvider + RemoteViews + التشخيص]
  kotlin/com/nano/homewidget/NanoGlanceWidget.kt        [حُذف]
  kotlin/com/nano/homewidget/NanoHomeWidgetPlugin.kt    [أعيدت كتابته بلا Glance/DataStore]
  res/layout/nano_widget.xml                            [جديد]
  res/drawable/nano_widget_bg.xml                       [جديد]
extensions/flet_native_files/src/flutter/flet_native_files/android/build.gradle  [حُذفت تبعيات Glance/Compose/DataStore]
build_nano_apk.sh            [0.8.1/14 ← 0.9.1/22]
pyproject.toml               [version + build_number ← 0.9.1/22]
src/nano_offline/version.py  [0.9.0/21 ← 0.9.1/22]
README.md                    [أرقام البناء في قسم Android]
FIX_0.9.1_HOME_WIDGET_APPPROVIDER_AR.md [هذه الملاحظة]
```

لم يتغيّر: `AndroidManifest.xml` (نفس الـreceiver بنفس الاسم و`exported="true"`)،
`nano_widget_info.xml`، `pubspec.yaml`، الجسران Dart/Python،
`NanoQuickSettingsTileService.kt`، و`tools/verify_flet_native_files_registration.py`
(فحصه لوجود الـreceiver و`exported="true"` يبقى صالحًا كما هو).

## خطوات البناء والتحقق

1. احذف الودجت القديمة من الشاشة الرئيسية.
2. `./build_nano_apk.sh`
3. `python tools/verify_flet_native_files_registration.py build/flutter`
4. ثبّت `dist/nano-release.apk`، ثم أضف الودجت من جديد من قائمة ودجت أندرويد:
   عليها أن تظهر فورًا (أو برسالة "افتح التطبيق للتحديث" إن لم يصل push بعد).
5. نفّذ فاتورة بيع أو سندًا → تتحدّث الودجت فورًا دون إغلاق التطبيق.
6. أغلق التطبيق تمامًا وانتظر → التمرير الدوري (WorkManager) يحدّثها أيضًا.
7. لو استمر أي فشل، التقط:
   `adb logcat -v time | grep -iE "homewidget|nano_widget|AppWidget"`
   والصق الناتج — مع هذه البنية الجديدة فإن أي سطر استثناء في logcat
   يشير إلى موضع العطل بشكل قاطع.

## حاشية

لوحة التشخيص داخل التطبيق (التي أضافتها 0.8.4/0.8.5 في `admin_view.py`)
**غير موجودة في شجرة 0.9.1 الحالية** — لم تُدمج مع إعادة التنظيم. التحقق
يكون عبر الودجت نفسها أو عبر logcat، وطريقة `diagnose` في القناة ما زالت
محفوظة في الجسر تحسبًا لإعادة إضافة اللوحة.

- Version: 0.9.1
- Android build number: 22
