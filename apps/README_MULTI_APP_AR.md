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

- كل APK يحصل على مجلد تخزين خاص (`FLET_APP_STORAGE_DATA` مختلف).
- لذلك **لا** يمكن لتطبيقين منفصلين على أندرويد مشاركة نفس ملف SQLite بسهولة بدون حلول إضافية:
  - مسار مشترك خارجي + صلاحيات واسعة، أو
  - Content Provider أصلي.

**الحل العملي الحالي:**
- طوّر واختبر التطبيقات المنفصلة على سطح المكتب أولًا.
- عند بناء APK لأندرويد لاحقًا يمكن:
  1. بناء ثلاثة حزم مختلفة مع توجيه `NANO_SHARED_DATA_DIR` لمسار مشترك، أو
  2. الإبقاء على حزمة واحدة مع نقاط دخول متعددة (Launcher Activities) إذا رغبت بتجنب تعقيدات التخزين.

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
