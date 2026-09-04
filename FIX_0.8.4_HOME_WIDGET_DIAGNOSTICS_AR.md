# Nano 0.8.4 — تصحيح ثالث لودجت الشاشة الرئيسية + لوحة تشخيص داخل التطبيق

## التصحيح: getAppWidgetState بلا حماية

`FIX_0.8.3_HOME_WIDGET_AR.md` غلّف كل ما بداخل `provideContent` بطبقتي try/catch،
لكن `getAppWidgetState(context, PreferencesGlanceStateDefinition, id)` في
`NanoGlanceWidget.provideGlance` يُنفَّذ **قبل** `provideContent` مباشرة، ولم
يكن ملفوفًا بأي حماية. هذا الاستدعاء يقرأ DataStore من القرص، وأي استثناء منه
(ملف تالف، خطأ إدخال/إخراج، قراءة تتزامن مع كتابة) كان يُسقط `provideGlance`
بالكامل قبل أن تصل طبقتا 0.8.3 للتنفيذ إطلاقًا — أي أنه يُعيد بالضبط رسالة
"يتعذّر عرض المحتوى" التي كان 0.8.3 يُفترض أن ينهيها.

### التصحيح في `NanoGlanceWidget.kt`

استدعاء `getAppWidgetState` أصبح داخل try/catch خاص به، خارج `provideContent`:
عند الفشل، تُستخدم قيمة `null` كبديل (تُعامَل مثل عدم وجود بيانات محفوظة بعد)
بدل إسقاط الودجت بالكامل، والودجت تنتقل عندها إلى نفس مسار "تعذّر تحميل
الأرقام" المُعالَج أصلاً في 0.8.3.

## لوحة تشخيص جديدة داخل التطبيق (الإدارة ← ودجت الشاشة الرئيسية)

كل الفحوصات السابقة (0.8.2/0.8.3) كانت تتطلب قراءة الكود يدويًا أو التقاط
`adb logcat`. هذا الإصدار يضيف مسارًا كاملاً لعرض نفس المعلومات من داخل
التطبيق نفسه:

- كائن `NanoWidgetDiagnostics` (Kotlin، ذاكرة فقط) يسجّل: آخر خطأ في قراءة
  DataStore، آخر خطأ في رسم المحتوى، آخر بيانات محفوظة، ووقت/نتيجة آخر
  تحديث فوري (push).
- طريقة جديدة `diagnose` على قناة `nano/home_widget` (في
  `NanoHomeWidgetPlugin.kt`) تُعيد كل هذا كـJSON، بالإضافة لعدد نسخ الودجت
  المضافة فعليًا للشاشة الرئيسية حاليًا.
- `native_files.dart`: حالة جديدة `diagnose_home_widget` على القناة
  الرئيسية تُمرّر الطلب لقناة الودجت (أو تُبلّغ صراحة عن منصّة غير مدعومة
  على غير أندرويد).
- `native_files.py`: دالة جديدة `diagnose_home_widget()` بنفس عقد
  `diagnose_sound()` — لا تبتلع الفشل، بل تُعيده كسطر تشخيص بحد ذاته.
- `views/admin_view.py`: تبويب جديد "ودجت الشاشة الرئيسية" في لوحة الإدارة،
  بزر "تشخيص الودجت" يفتح نفس نمط حوار "تشخيص النظام الصوتي" الموجود مسبقًا
  (صفوف ✓/✗/● قابلة للتحديد، مع زرّي "اختبار الآن" و"إعادة الفحص"). زر
  "اختبار الآن" يدفع بيانات لوحة التحكم الحالية فورًا (نفس مسار ما بعد حفظ
  فاتورة بيع) ثم يعيد الفحص مباشرة.

## الملفات المعدَّلة

```
extensions/flet_native_files/src/flutter/flet_native_files/android/src/main/kotlin/com/nano/homewidget/
  NanoGlanceWidget.kt        [تعديل: حماية getAppWidgetState + NanoWidgetDiagnostics]
  NanoHomeWidgetPlugin.kt    [تعديل: طريقة diagnose + تسجيل نتيجة push]

extensions/flet_native_files/src/flutter/flet_native_files/lib/src/native_files.dart  [تعديل: حالة diagnose_home_widget]
extensions/flet_native_files/src/flet_native_files/native_files.py                     [تعديل: diagnose_home_widget()]
src/nano_offline/views/admin_view.py                                                    [تعديل: تبويب + لوحة تشخيص الودجت]
```

## حدود معروفة

لم يُبنَ APK فعليًا في بيئة التطوير الحالية (لا تتوفر Flutter/Gradle Runtime
هنا) — نفس القيد المذكور في الملاحظات السابقة. قبل أول بناء فعلي، نفّذ
`tools/verify_flet_native_files_registration.py build/flutter` كالمعتاد، ثم
افتح لوحة "تشخيص الودجت" الجديدة بعد إضافة الودجت للشاشة الرئيسية للتأكد من
أن كل الصفوف خضراء.

- Version: 0.8.4
- Android build number: 16
