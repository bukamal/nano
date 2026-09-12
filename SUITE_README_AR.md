# نانو — الحزمة الكاملة (تطبيقات متعددة + تخزين مشترك + GitHub Actions)

هذه الحزمة تضم مشروع نانو الأصلي مع كل التعديلات التالية:

## 1) تطبيقات منفصلة تشترك في قاعدة البيانات

| التطبيق | نقطة الدخول | Application ID |
|---------|-------------|----------------|
| الكامل | `src/main.py` | `com.nano` |
| المحاسبة | `src/main_accounting.py` | `com.nano.accounting` |
| المستودع | `src/main_inventory.py` | `com.nano.inventory` |
| نقطة البيع | `src/main_pos.py` | `com.nano.pos` |

الكود المشترك: `src/nano_offline/`  
واجهات التطبيقات: `src/nano_offline/suite/`  
تشغيل سطح المكتب: `./apps/run_suite.sh accounting|inventory|pos|full`

## 2) تخزين مشترك على أندرويد

- المسار المفضّل: `Documents/NanoShared/nano.db`
- Content Provider: `content://com.nano.shared.db/database`
- صلاحية signature: `com.nano.permission.ACCESS_SHARED_DB`
- عند الإقلاع يستدعي `bootstrap` → `prepare_shared_storage()` قبل فتح القاعدة

التفاصيل: `SHARED_STORAGE_AR.md`

## 3) GitHub Actions

| Workflow | الوظيفة |
|----------|---------|
| `.github/workflows/build-android-suite.yml` | يبني 3 APKs بالتوازي |
| `.github/workflows/build-android-apk.yml` | يبني التطبيق الكامل |
| `.github/workflows/quality-gate.yml` | اختبارات سريعة |

البناء المحلي:

```bash
./apps/build_suite_apk.sh accounting
./apps/build_suite_apk.sh inventory
./apps/build_suite_apk.sh pos
./apps/build_suite_apk.sh full
```

## تشغيل سريع (سطح المكتب)

```bash
pip install -e extensions/flet_native_files
pip install -e .
export PYTHONPATH=src
export NANO_SHARED_DATA_DIR="$HOME/.nano"

./apps/run_suite.sh accounting
./apps/run_suite.sh inventory
./apps/run_suite.sh pos
```

## ملاحظات

- على سطح المكتب المشاركة تعمل فورًا عبر `~/.nano/nano.db`.
- على أندرويد قد يُطلب من المستخدم منح «الوصول لكل الملفات» مرة واحدة.
- الحزم الثلاث يجب توقيعها بنفس مفتاح التوقيع لصلاحية Content Provider.
- `MANAGE_EXTERNAL_STORAGE` مقيد في Google Play — مناسب للاستخدام الداخلي.
