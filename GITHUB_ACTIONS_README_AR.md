# ملفات GitHub Actions لتطبيقات نانو المتعددة

هذا المجلد يوفّر كل ما تحتاجه لبناء:

| Workflow | الملف | الناتج |
|----------|-------|--------|
| التطبيق الكامل | `.github/workflows/build-android-apk.yml` | `nano-release.apk` |
| التطبيقات الثلاثة | `.github/workflows/build-android-suite.yml` | 3 APKs منفصلة |
| بوابة الجودة | `.github/workflows/quality-gate.yml` | اختبارات سريعة بدون SDK |

## حزم أندرويد الناتجة

| التطبيق | Application ID | اسم العرض | Entry module |
|---------|----------------|-----------|--------------|
| الكامل | `com.nano` | Nano \| نانو | `main` |
| المحاسبة | `com.nano.accounting` | نانو محاسبة | `main_accounting` |
| المستودع | `com.nano.inventory` | نانو المستودع | `main_inventory` |
| نقطة البيع | `com.nano.pos` | نانو نقطة البيع | `main_pos` |

يمكن تثبيت الثلاثة معًا على نفس الجهاز (أسماء حزم مختلفة).

---

## كيفية الدمج في مستودعك

انسخ الملفات التالية إلى جذر المشروع (مع الحفاظ على المسارات):

```
.github/workflows/build-android-apk.yml
.github/workflows/build-android-suite.yml
.github/workflows/quality-gate.yml
apps/build_suite_apk.sh
apps/README_MULTI_APP_AR.md
apps/run_suite.sh
src/main_accounting.py
src/main_inventory.py
src/main_pos.py
src/nano_offline/bootstrap.py
src/nano_offline/core/paths.py          # يستبدل الملف الحالي
src/nano_offline/suite/__init__.py
src/nano_offline/suite/accounting_app.py
src/nano_offline/suite/inventory_app.py
src/nano_offline/suite/pos_app.py
```

ثم:

```bash
chmod +x apps/build_suite_apk.sh apps/run_suite.sh
```

تأكد أن `pyproject.toml` يحتوي:

```toml
[tool.flet.app]
path = "src"
module = "main"
```

(السكربت يعدّل `module` مؤقتًا أثناء بناء كل تطبيق ثم يعيده.)

---

## التشغيل اليدوي على GitHub

1. **Actions** → **Build Android Suite APKs** → **Run workflow**
2. اختياري: اكتب `accounting,pos` في حقل apps لبناء جزء فقط، أو اترك `all`.
3. بعد النجاح حمّل الـ Artifacts:
   - `nano-accounting-apk`
   - `nano-inventory-apk`
   - `nano-pos-apk`
   - `nano-suite-all-apks` (الكل معًا)

---

## البناء المحلي

```bash
# تطبيق واحد
./apps/build_suite_apk.sh accounting
./apps/build_suite_apk.sh inventory
./apps/build_suite_apk.sh pos
./apps/build_suite_apk.sh full

# الناتج في dist/
ls dist/
```

---

## ملاحظات أندرويد حول قاعدة البيانات المشتركة

التطبيقات الثلاثة **منفصلة** (حزم مختلفة). على سطح المكتب تشارك `~/.nano/nano.db` عبر `NANO_SHARED_DATA_DIR`.

على أندرويد كل حزمة لها تخزين خاص. مشاركة ملف SQLite الحقيقي تحتاج لاحقًا:

- مسار تخزين خارجي مشترك + صلاحيات، أو
- Content Provider في أحد التطبيقات.

هذا لا يمنع بناء وتوزيع الـ APKs الثلاثة الآن.

---

## المتطلبات في GitHub Actions

- Ubuntu runner (الافتراضي)
- Java 17
- Android SDK (platform 35 + build-tools 34)
- Python 3.12 + uv
- لا حاجة لـ secrets إلا إذا أضفت لاحقًا توقيع keystore مخصص

للتوقيع بـ release keystore خاص بك، أضف secrets:

- `ANDROID_KEYSTORE_BASE64`
- `ANDROID_KEYSTORE_PASSWORD`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`

ثم وسّع `build_suite_apk.sh` لتمريرها إلى `flet build` (FLET يدعم متغيرات التوقيع القياسية).
