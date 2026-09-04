# تقرير التعديل: توحيد الألوان عبر Design Tokens

## ما تم
1. **ملف جديد**: `src/nano_offline/core/theme.py`
   يحتوي 3 كلاسات:
   - `Colors` — 35 لونًا موحدًا بأسماء دلالية (PRIMARY, TEXT_SECONDARY, DANGER_BG...)
   - `Spacing` — سلم مسافات موحد (اختياري للاستخدام لاحقًا)
   - `Radius` — سلم انحناء زوايا موحد (اختياري للاستخدام لاحقًا)

2. **استبدال آلي دقيق** لكل قيم الألوان الست-عشرية الحرفية في:
   - `src/main.py` → 204 استبدال
   - `src/nano_offline/views/activation_view.py` → 14 استبدال
   - `src/nano_offline/views/admin_view.py` → 16 استبدال
   - `src/nano_offline/views/finance_view.py` → 65 استبدال
   - `src/nano_offline/views/invoice_view.py` → 54 استبدال
   - `src/nano_offline/views/reports_view.py` → 24 استبدال

   **الإجمالي: 377 استبدال**، من قيمة حرفية `"#0B63F6"` إلى رمز دلالي `Colors.PRIMARY`.

3. تمت إضافة `from nano_offline.core.theme import Colors` تلقائيًا لكل ملف تأثر.

## لماذا هذا مهم
- قبل: تغيير اللون الأساسي للتطبيق يتطلب تعديل 33 موضعًا يدويًا عبر 6 ملفات، مع خطر نسيان موضع أو خطأ كتابة.
- بعد: تغيير سطر واحد في `theme.py` (`PRIMARY = "#..."`) يطبّق التغيير في كل الواجهة فورًا.

## التحقق الذي تم إجراؤه
- ✅ `python -m py_compile` على كل الملفات المعدّلة — نجح بدون أخطاء.
- ✅ `python -m compileall src tools` على كامل المشروع — نجح.
- ✅ لا توجد قيم hex متبقية غير مستبدلة (تم التحقق بـ grep).
- ✅ `tools/core_smoke_test.py` (منطق محاسبي أساسي، لا يعتمد على Flet) — **نجح** (نفس نتائج ما قبل التعديل: `purchase=1 sale=2 customer_balance=50.0 supplier_balance=40.0 stock=12.0`).
- ⚠️ لم أتمكن من تشغيل اختبارات الواجهة (`phase*_flet_ui_contract_smoke_test.py`) لأن بيئة التنفيذ هنا بلا اتصال إنترنت لتثبيت حزمة `flet`. أنصح بتشغيل `PYTHONPATH=src python tools/quality_gate.py` محليًا عندك للتأكد الكامل قبل الدمج — التعديل ميكانيكي بحت (استبدال نص فقط) ولم يغيّر أي منطق، لذا الخطر منخفض جدًا.

## ملاحظة حول نمط الاستخدام كمفتاح Dictionary
وُجد نمط مثل:
```python
bgcolor={"#16A34A": "#ECFDF5", ...}.get(accent, "#EFF6FF")
```
أصبح:
```python
bgcolor={Colors.SUCCESS: Colors.SUCCESS_BG, ...}.get(accent, Colors.PRIMARY_BG)
```
هذا يعمل بشكل سليم لأن `Colors.X` كلها ثوابت نصية عادية وقت التشغيل.

## الخطوة التالية المقترحة
تقسيم `src/main.py` (1,302 سطر) إلى ملفات أصغر:
- `shell.py` (الهيكل العام + التنقل)
- `dashboard_view.py` (لوحة التحكم)
- دوال مساعدة مشتركة (`money()`, `metric()`, إلخ) إلى `nano_offline/components/`
