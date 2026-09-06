# FIX_0.9.2 — مزامنة الودجت بعد الاسترجاع + تحديث بصري للبطاقة

## المشكلة

بعد استرجاع نسخة احتياطية بنجاح (الأمان يُنشأ، الـ`.db` يُستبدل، الـreload ينجح)، ودجت الشاشة الرئيسية
تبقى تظهر إما:

1. رسالة "افتح التطبيق للتحديث" (حين لم تُدفع أي لقطة بعد)، أو
2. أرقامًا قديمة تعود لتاريخ ما قبل النسخة الاحتياطية (حين وُجدت لقطة سابقة في
   `SharedPreferences` لم تُمسح عند الاسترجاع).

ولوحظ ذلك بالتحديد في الأجهزة التي أُعيدت بياناتها من نسخة احتياطية دون أن يُنفَّذ أي بيع/سند
جديد بعدها، لأن اللقطة لا تُحدَّث إلا من مسارين مُحفِّزين:

- الفوري: عند البيع/السند (`refresh_home_widget` بعد الحفظ)،
- الدوري: `WorkManager` كل 30 دقيقة كحدٍّ أدنى (المسار الوحيد حين يكون التطبيق مُغلقًا).

لا توجد أي عملية دفع/تحديث عند الـlogin أو الـreload بعد الاسترجاع.

## التشخيص — أسطر من الكود

### 1. اللقطة محفوظة خارج ملف الـDB

```kotlin
// extensions/flet_native_files/.../NanoWidgetReceiver.kt
const val PREFS_NAME = "nano_widget_state"
const val KEY_SNAPSHOT = "snapshot_json"
```

`restore_backup` يستبدل ملف `.db` فقط، ولا يلمس هذا المفتاح:

```python
# src/nano_offline/services/backup_service.py (قبل هذا الإصلاح)
def restore_backup(self, backup_path, password=None) -> Path:
    ...
    os.replace(temp_target, self.db.path)   # يستبدل .db فقط، وليس الودجت prefs
```

### 2. الـreload لا يدفع لقطة جديدة

```python
# src/nano_offline/views/admin_view.py (قبل هذا الإصلاح)
safety = self.ctx.backup.restore_backup(path)
self.ctx.reload(self.ctx.db.path)
# ← لا push_home_widget بعد ذلك
set_dialog(title="تم الاسترجاع بنجاح", ...)
```

أين كان يجب أن يحدث الدفع؟ لا يوجد مكان — `home_widget.py.refresh_home_widget` يُستدعى
فقط داخل مسارَي البيع/السند، و`native_files.dart._pushHomeWidgetSnapshot` فقط من داخل
WorkManager.

## الحل — ثلاث خطوات دقيقة بعد replace الـDB

أضفت ثلاث دوال مكشوفة في `core/home_widget.py` ودعوتها من داخل `admin_view.confirm` فور
`ctx.reload(...)` بنجاح:

```
clear_home_widget              ← يمسح snapshot.json من SharedPreferences
force_refresh_home_widget      ← يُجبر كل instance من الودجت على إعادة الرسم فورًا
push_home_widget(snapshot)     ← يدفع sales_today/cash_balance من الـDB المُسترجعة
```

### ملفات الفرونت (Kotlin)

أضفت معالجات `clear` و`refresh_now` على قناة `nano/home_widget`:

```kotlin
// NanoHomeWidgetPlugin.kt
override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
    when (call.method) {
        "push"          -> handlePush(call, result)
        "clear"         -> handleClear(result)         // جديد
        "refresh_now"   -> handleRefreshNow(result)    // جديد
        "diagnose"      -> handleDiagnose(result)
        else            -> result.notImplemented()
    }
}
```

وفي `NanoWidgetReceiver`:

```kotlin
fun clearSnapshot(context: Context) {
    context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        .edit().remove(KEY_SNAPSHOT).apply()
    NanoWidgetDiagnostics.lastClearAt = System.currentTimeMillis()
}

fun refreshAllNow(context: Context) {
    val ctx = context.applicationContext
    val manager = AppWidgetManager.getInstance(ctx)
    val ids = manager.getAppWidgetIds(ComponentName(ctx, NanoWidgetReceiver::class.java))
    refresh(ctx, manager, ids)
    NanoWidgetDiagnostics.lastRefreshNowAt = System.currentTimeMillis()
}
```

### ملفات الـbridge (Dart)

أضفت حالتَي `'clear_home_widget'` و`'force_refresh_home_widget'` على `_FletNativeFilesControlState.handleMethod`.

### نقطة الربط في الـadmin

```python
# src/nano_offline/views/admin_view.py
self.ctx.reload(self.ctx.db.path)
log("4: context reloaded, syncing home widget with restored DB")
try:
    from nano_offline.core.home_widget import refresh_home_widget_after_restore
    refresh_home_widget_after_restore(self.page, self.native_files, self.ctx.dashboard)
except Exception as widget_exc:
    # لا نُلغي نجاح الاسترجاع إذا فشل تحديث الودجت — DB صحيحٌ في كل الأحوال،
    # والتمرير الدوري/البيع التالي سيُصحّح المسار.
    print(f"[nano-restore] widget resync skipped: {widget_exc!r}", flush=True)
```

## التحديث البصري — إعادة هوية البطاقة

اللوحة كانت:
`خلفية موحّدة #0F766E + قيمة 18sp + CardLayout + حافة نص-تنبيه inline`.

البطاقة الآن:
1. **خلفية**: تدرّج لوني من `#0F766E` إلى `#115E59` بزاوية 135° (نفس PRIMARY_DARK).
2. **حدّة العنوان**: 14sp → 14sp مع `letterSpacing=0.04` + نقطة حيّة `#5EEAD4` شكل بيضاوي
   عند زاوية العنوان (نفس `Colors.PRIMARY_DARK` في الوضع الليلي — لون مفيد بشكل طبيعي في
   خلفيات داكنة).
3. **القيم**: KPI بحجم **22sp** عريض بدل 18sp، مع تباعد علوي 2dp بين العنوان الفرعي والقيمة.
4. **حالة التنبيه**: تتحول من نص inline إلى كبسولة مستقلة `nano_widget_alert_pill` بخلفية
   نصف شفّافة `26FFD9C2` وحدّ ناعم `66FFD9C2`، يرتفع 12dp بدل 6dp — قراءة "تنبيه لطيف"
   بدل "نَصّ ملصوق".
5. **Freshness footer**: سطر جديد `nano_widget_footer` يعرض `تم التحديث قبل X` (دقيقة/ساعة،
   أو وقت مطلق في الوضع `Locale("ar")` لإن اليوم تجاوز 24 ساعة). يحسب من `updated_at`
   ISO 8601 (UTC → التوقيت المحلي للجهاز)، يُخفى إذا لم تصل لقطة بعد.
6. **First-run hint**: نص موحَّد من `@string/nano_widget_hint` بدل نص مُضمَّن، ومحاذاة وسط بدل بداية.

كل ما سبق يستخدم ألوانًا من `theme.py` نفسها (`Colors.PRIMARY`/`PRIMARY_DARK`/`PRIMARY_BORDER`
وسلسلة الـ`C7E5E0`/`FFD9C2`/`5EEAD4` للقراءات الداكنة)، لا توجد طبقة تصميم جديدة.

## الملفات المعدَّلة

```
extensions/flet_native_files/src/flutter/flet_native_files/android/src/main/
  kotlin/com/nano/homewidget/NanoWidgetReceiver.kt       [أعيد + clearSnapshot/refreshAllNow/badge dot image]
  kotlin/com/nano/homewidget/NanoHomeWidgetPlugin.kt     [أعيد + clear/refresh_now/footer]
  res/layout/nano_widget.xml                             [أعيد: تدرّج/تنبيه كبسولة/footer/letterSpacing]
  res/drawable/nano_widget_bg.xml                        [gradient بدل solid]
  res/drawable/nano_widget_alert_pill.xml                [جديد]
  res/drawable/ic_nano_dot.xml                           [شكل بيضاوي للنقطة الحيّة]
  res/values/strings.xml                                 [+ nano_widget_hint]
lib/src/native_files.dart                               [+ 'clear_home_widget' / 'force_refresh_home_widget']
src/nano_offline/core/home_widget.py                     [أعيد: clear/force_refresh/refresh_home_widget_after_restore]
src/nano_offline/views/admin_view.py                     [استدعاء refresh_home_widget_after_restore داخل confirm()]
pyproject.toml                                           [version 0.9.2 / build_number 23]
src/nano_offline/version.py                              [APP_VERSION 0.9.2 / BUILD_NUMBER 23]
build_nano_apk.sh                                        [--build-version 0.9.2 --build-number 23]
README.md                                                [--build-version 0.9.2 --build-number 23]
FIX_0.9.2_HOME_WIDGET_RESTORE_SYNC_AR.md [هذه الملاحظة]
```

## خطوات التحقق

1. احذف الودجت القديمة إن وُجدت، ثم `./build_nano_apk.sh` وصدّر `dist/nano-release.apk` (0.9.2 / 23).
2. افتح التطبيق، تنفيذ فاتورة بيع → ودجت محدّثة فورًا، بأرقام من يومك الحالي.
3. أنشئ نسخة احتياطية يدويًا من admin مثلًا، سجّل مبيعات وأضف موادًا، ثم استرجع تلك النسخة.
4. ولحظة إغلاق نافذة "تم الاسترجاع بنجاح"، اضغط طولًا على مساحة فارغة في الشاشة الرئيسية،
   أضف ودجت Nano → يجب أن تظهر فورًا بأرقام الـDB المُسترجعة (وليس رسالة `افتح التطبيق للتحديث`).
5. اتركها 30+ دقيقة بدون أي عملية → التمرير الدوري يُجدّدها كما كان. هذا المسار لم يتغيّر.
6. لو استمر أي فشل:
   `adb logcat -v time | grep -iE "homewidget|nano_widget|AppWidget"`

## حاشية

- هذا الإصلاح مُكمِّل لـFIX_0.9.1 (الانتقال من Glance إلى AppWidgetProvider). لم نعد إلى Glance.
- الدوال الثلاث الجديدة (`clear_home_widget`/`force_refresh_home_widget`/`refresh_home_widget_after_restore`)
  آمنة للاستدعاء في أي وقت — لو استُدعيت خارج سياق الاسترجاع (مثلًا من شاشة ما قبل
  الدخول) فهي عمليات no-op آمنة على المنصات غير-أندرويد (desktop/dev) ودون أي تأكد
  إضافي على المعلوم المطلوبة.
- الـupdate_periodMillis في `nano_widget_info.xml` ظل `1_800_000` (30 دقيقة)، حدٌّ
  أدنى يفرضه النظام، ليس معرَّضًا لتعديل هنا.

- Version: 0.9.2
- Android build number: 23
