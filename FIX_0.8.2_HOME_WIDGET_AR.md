# Nano 0.8.2 — إصلاح ودجت الشاشة الرئيسية (PHASE10)

## المشكلة كما ظهرت للمستخدم

1. عند إضافة ودجت "Nano | نانو" (2×4) من قائمة ودجت أندرويد، تظهر معاينة
   الودجت **بيضاء/فارغة تمامًا** داخل منتقي الودجت (قبل الإضافة).
2. بعد إضافتها فعليًا للشاشة الرئيسية، تعرض الودجت باستمرار رسالة أندرويد
   القياسية **"يتعذّر عرض المحتوى"** بدل الأرقام (مبيعات اليوم / رصيد
   الصندوق)، ولا تتعافى حتى بعد فتح التطبيق أو الانتظار.

## السبب الجذري

`android/src/main/AndroidManifest.xml` (في وحدة الإضافة
`extensions/flet_native_files/.../android/`) كان يسجّل `NanoWidgetReceiver`
بـ `android:exported="false"`.

هذا الـreceiver **لا** يُستدعى من داخل عملية التطبيق نفسه — بل من عملية
الـlauncher/System Server عبر بثّ `APPWIDGET_UPDATE`، في كل مرة تُضاف
الودجت أو تُغيَّر مقاساتها أو يحين موعد تحديثها الدوري. هذا استدعاء عابر
للعمليات (cross-process) بامتياز، وهو بالضبط ما يتحكم به `exported` — ومنذ
Android 12 (API 31) أصبح أندرويد يفرض هذا القيد فعليًا بدل تجاهله. مع
`exported="false"`:

- عملية البناء والتثبيت تنجح بلا أي خطأ ظاهر.
- الودجت تظهر في القائمة (لهذا كانت مرئية أصلاً)، لكن أندرويد لا يملك صورة
  معاينة لها فتظهر فارغة (السبب الثاني أدناه).
- بعد الإضافة، بثّ `APPWIDGET_UPDATE` من الـlauncher لا يصل أبدًا إلى
  `NanoWidgetReceiver`، فلا يُستدعى `NanoGlanceWidget.provideGlance` مطلقًا
  — وهذا هو بالضبط ما يعرضه أندرويد كرسالة "تعذّر تحميل الودجت" الثابتة،
  وليس عطلاً (crash) داخل كود Compose/Glance نفسه.

السبب الثاني (المعاينة الفارغة في المنتقي) أبسط: `nano_widget_info.xml` لم
يكن يعرّف `android:previewImage` أصلاً، وأندرويد يعرض شبكة بيضاء فارغة
لأي ودجت بلا صورة معاينة معرَّفة — بغض النظر عن حالة `exported`.

## التصحيحات

1. `android:exported="false"` → `android:exported="true"` على
   `<receiver android:name="com.nano.homewidget.NanoWidgetReceiver">`.
2. إضافة `android:previewImage="@drawable/nano_widget_preview"` (أيقونة
   التطبيق نفسها، مُعاد تحجيمها) و`android:description="@string/..."`
   (نص جديد في `res/values/strings.xml`) إلى `nano_widget_info.xml`، حتى
   تظهر معاينة حقيقية ووصف عند الضغط المطوّل على الودجت في منتقي أندرويد.
3. `tools/verify_flet_native_files_registration.py` أصبح يتحقق أيضًا —
   بعد كل بناء APK فعلي — أن `<receiver>` الخاص بـ`NanoWidgetReceiver` في
   البيان النهائي المُدمَج يحمل `android:exported="true"` تحديدًا، لا فقط
   أنه موجود بالاسم. وجود الاسم وحده لم يكن كافيًا: كان يمر حتى مع
   `exported="false"` الذي سبّب هذه المشكلة أصلاً دون أي خطأ بناء يكشفها.

## خطوات التحقق بعد أول بناء APK فعلي

نفس خطوات `PHASE10_HOME_WIDGET_GLANCE_AR.md`، بالإضافة إلى: التأكد من
ظهور صورة معاينة حقيقية (لا شبكة بيضاء) عند فتح منتقي ودجت أندرويد قبل
إضافتها.

- Version: 0.8.2
- Android build number: 14
