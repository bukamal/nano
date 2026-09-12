# نانو — تطبيقات متعددة تشترك في قاعدة بيانات واحدة

تم تقسيم النظام إلى **ثلاثة تطبيقات منفصلة** تعمل كعمليات مستقلة وتشترك في نفس ملف SQLite.

| التطبيق | المجلد | الوظيفة الرئيسية |
|---------|--------|------------------|
| **نانو المحاسبة** | `apps/nano_accounting` | عملاء، موردون، مالية، فواتير، تقارير، إدارة |
| **نانو المستودع** | `apps/nano_inventory` | مواد، جرد، مشتريات |
| **نانو نقطة البيع** | `apps/nano_pos` | واجهة البيع السريع فقط (تفتح مباشرة) |

التطبيق الأصلي الكامل (`src/main.py`) يبقى كما هو للتوافق.

---

## كيف تُشارك قاعدة البيانات؟

جميع التطبيقات تستخدم `nano_offline.core.paths.database_path()`.

أولوية المسار:

1. متغير البيئة `NANO_SHARED_DATA_DIR` ← **استخدمه دائمًا عند تشغيل أكثر من تطبيق**
2. `FLET_APP_STORAGE_DATA` (أندرويد — خاص بكل حزمة)
3. `NANO_DATA_DIR` / `QEID_DATA_DIR`
4. الافتراضي على سطح المكتب: `~/.nano/nano.db`

### تشغيل مشترك على سطح المكتب (موصى به)

```bash
# في كل طرفية / اختصار:
export NANO_SHARED_DATA_DIR="$HOME/.nano"
export PYTHONPATH=src

# تطبيق المحاسبة
python apps/nano_accounting/main.py

# تطبيق المستودع
python apps/nano_inventory/main.py

# تطبيق نقطة البيع
python apps/nano_pos/main.py
```

أو استخدم السكربت المساعد:

```bash
./apps/run_suite.sh accounting
./apps/run_suite.sh inventory
./apps/run_suite.sh pos
```

---

## ملاحظات مهمة حول أندرويد

### 1) منع خطأ «التطبيق غير مثبت»

- كل APK له `applicationId` مختلف: `com.nano.accounting` / `com.nano.inventory` / `com.nano.pos`.
- الـ ContentProvider يستخدم authority فريد: `${applicationId}.shared.db` → لا تعارض.
- **لا** يُعرَّف إذن مخصص (`<permission>`) في أكثر من حزمة (يسبب `INSTALL_FAILED_DUPLICATE_PERMISSION`).
- استخدم **نفس مفتاح التوقيع** (Keystore) للثلاثة.

### 2) مشاركة قاعدة البيانات (حل مشكلة «لا تقرأ التطبيقات القاعدة»)

المسار المشترك:

```
/storage/emulated/0/Documents/NanoShared/nano.db
```

على **Android 11+** يجب منح صلاحية **«الوصول إلى كل الملفات»** (All files access / MANAGE_EXTERNAL_STORAGE) لكل تطبيق من التطبيقات الثلاثة، وإلا:

- يسقط النظام إلى مجلد خاص بكل حزمة → كل تطبيق يرى قاعدة بيانات فارغة أو مختلفة.
- هذا هو السبب المباشر لمشكلة «عدم قراءة قاعدة البيانات من التطبيقات».

**خطوات التشغيل الصحيح على الجهاز:**

1. ثبّت التطبيقات الثلاثة (أي ترتيب).
2. افتح **إعدادات النظام → التطبيقات → نانو المحاسبة** (ثم المستودع ونقطة البيع).
3. فعّل **الوصول إلى كل الملفات** / All files access.
4. أعد تشغيل كل تطبيق مرة واحدة بعد منح الصلاحية.
5. تحقق من التشخيص (إن وُجد في لوحة الإدارة): يجب أن يظهر `truly_shared = true`.

بدون هذه الصلاحية لن تُشارك القاعدة مهما كان الـ ContentProvider.

### 3) ContentProvider الحالي

- موجود كجسر ملفات (File-style) وليس استعلام جداول.
- `exported="false"` + authority فريد لكل APK → آمن للتثبيت.
- المشاركة الفعلية تتم عبر الملف في `Documents/NanoShared` وليس عبر ContentResolver للجداول.

---

## البنية التقنية

```
src/nano_offline/          ← النواة المشتركة (repositories, services, views, core)
  bootstrap.py             ← تدفق مشترك: splash → تفعيل → دخول → shell
apps/
  nano_accounting/main.py  ← واجهة المحاسبة فقط
  nano_inventory/main.py   ← واجهة المستودع فقط
  nano_pos/main.py         ← واجهة نقطة البيع فقط
```

كل تطبيق يستدعي `run_app(...)` من `bootstrap.py` ويمرر دالة `build_*_shell` الخاصة به.

---

## التطوير والاختبار

```bash
# تثبيت الحزمة في وضع التطوير
pip install -e .
pip install -e extensions/flet_native_files

# تشغيل أي تطبيق
PYTHONPATH=src NANO_SHARED_DATA_DIR=~/.nano python apps/nano_pos/main.py
```

تأكد أن SQLite يعمل بوضع WAL (مفعّل أصلًا في `Database.connect`). هذا يسمح بقراءات متزامنة من عدة تطبيقات + كاتب واحد في كل لحظة.
