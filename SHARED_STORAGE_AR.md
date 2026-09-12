# تخزين مشترك + Content Provider لتطبيقات نانو المنفصلة

## الهدف

جعل حزم APK الثلاثة (`com.nano.accounting` / `com.nano.inventory` / `com.nano.pos`)
تفتح **نفس ملف** `nano.db` على أندرويد.

## ما تم تنفيذه

### 1) مسار مشترك (الأساسي — Concurrent WAL)

| المكوّن | الموقع |
|---------|--------|
| Kotlin resolver | `com.nano.shared.NanoSharedStorage` |
| MethodChannel | `nano/shared_storage` |
| ContentProvider | `com.nano.shared.NanoSharedDbProvider` (authority: `com.nano.shared.db`) |
| Dart cases | `get_shared_data_dir`, `get_shared_db_path`, `diagnose_shared_storage`, … |
| Python API | `NativeFiles.get_shared_data_dir()` وغيرها |
| `paths.py` | `apply_shared_data_dir()` يضبط `NANO_SHARED_DATA_DIR` |
| Bootstrap | `nano_offline.shared_storage_boot.prepare_shared_storage()` |

**مسار المفضّل على الجهاز:**

```
/storage/emulated/0/Documents/NanoShared/nano.db
```

إذا تعذّر الكتابة هناك، يجرّب `/NanoShared` ثم يسقط إلى مجلد التطبيق الخاص
(غير مشترك — يظهر في التشخيص `truly_shared: false`).

### 2) Content Provider (شبكة أمان)

- Authority: `content://com.nano.shared.db/database`
- صلاحية signature: `com.nano.permission.ACCESS_SHARED_DB`
- يسمح لتطبيقات نانو الموقّعة بنفس المفتاح بفتح ملف القاعدة عبر URI
- مناسب كنسخة احتياطية عندما يكون المسار الخارجي غير متاح؛ **للوصول المتزامن
  الحقيقي مع WAL يُفضَّل المسار المشترك**

### 3) صلاحيات Android

في `AndroidManifest` الخاص بالإضافة:

- `READ_EXTERNAL_STORAGE` / `WRITE_EXTERNAL_STORAGE` (إصدارات أقدم)
- `MANAGE_EXTERNAL_STORAGE` (Android 11+) — يفتح شاشة النظام عبر
  `request_manage_storage`

---

## دمج في التطبيق

### أ) عند الإقلاع (قبل فتح القاعدة)

في `bootstrap.run_app` أو `main` بعد إنشاء `NativeFiles`:

```python
from nano_offline.shared_storage_boot import prepare_shared_storage
from nano_offline.core.paths import apply_shared_data_dir

async def _prepare():
    status = await prepare_shared_storage(native_files)
    # status: active, dir, truly_shared, has_permission, error
    page.session.set("shared_storage", status)  # اختياري للتشخيص

page.run_task(_prepare)
# ثم أنشئ AppContext بعد أن يكتمل التحضير إن أمكن
```

لأن `AppContext.create` يفتح القاعدة فورًا، الأفضل جعل التحضير **متزامنًا عند
أول إطار** أو استدعاء المسار الأصلي مرة بعد `apply_shared_data_dir`.

نمط آمن:

```python
async def main(page):
    native_files = NativeFiles()
    page.overlay.append(native_files)  # إن لزم لـ Flet control
    page.update()
    status = await prepare_shared_storage(native_files)
    # الآن database_path() يشير للمجلد المشترك
    run_app(page, ..., build_shell=...)
```

### ب) طلب صلاحية «كل الملفات» (مرة واحدة)

```python
if not await native_files.has_manage_storage():
    await native_files.request_manage_storage()  # يفتح إعدادات النظام
```

اعرض للمستخدم شرحًا عربيًا قصيرًا:  
«لتوحيد بيانات المحاسبة والمستودع ونقطة البيع على هذا الجهاز، اسمح بالوصول لجميع الملفات.»

---

## ملاحظات متجر بلاي

`MANAGE_EXTERNAL_STORAGE` مقيد في Google Play. للاستخدام الداخلي/المؤسساتي
مقبول غالبًا. للنشر العام لاحقًا:

1. الاعتماد على ContentProvider فقط + مزامنة ملفات، أو
2. العودة لحزمة واحدة مع عدة أيقونات تشغيل، أو
3. مجلد يختاره المستخدم عبر SAF مرة واحدة ويُحفظ URI.

---

## التشخيص

```python
diag = await native_files.diagnose_shared_storage()
# {
#   "dir": "...",
#   "db_path": "...",
#   "truly_shared": true/false,
#   "has_storage_permission": true/false,
#   "sdk": 34,
#   ...
# }
```

---

## ترتيب الدمج المقترح

1. انسخ ملفات Kotlin / Manifest / Dart / Python من هذه الحزمة فوق المشروع.
2. تأكد أن `NanoHomeWidgetPlugin.kt` المحدّث يحل محل النسخة القديمة.
3. اربط `prepare_shared_storage` في نقطة الإقلاع.
4. ابنِ APK واحدًا واختبر أن `Documents/NanoShared/nano.db` يُنشأ.
5. ابنِ الحزم الثلاث وثبّتها معًا وتحقق أن التعديل في واحدة يظهر في الأخرى.
