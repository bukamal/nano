# تقرير التعديل: تقسيم main.py إلى Center Classes

## المشكلة
`src/main.py` كان **1,303 سطرًا**، يحتوي دالة `build_shell()` ضخمة فيها 4 دوال متداخلة
ضخمة (`show_dashboard`, `party_view`, `items_view`, `show_security`) بمنطق واجهة كامل
لكل قسم، مما يجعل الملف صعب القراءة والصيانة.

## الحل المطبّق
اتبعت **نفس النمط الموجود مسبقًا في المشروع نفسه** (الملفات `InvoiceCenter`,
`FinanceCenter`, `ReportsCenter`, `AdminCenter` في `nano_offline/views/`) — كلاس لكل
قسم بواجهة موحدة `__init__(page, ctx, content, ...)` و `show_center()`.

### الملفات الجديدة
| الملف | الكلاس | مستخرج من |
|---|---|---|
| `nano_offline/views/dashboard_view.py` | `DashboardCenter` | `show_dashboard()` |
| `nano_offline/views/parties_view.py` | `PartyCenter` | `party_view()` (يُستخدم لكل من العملاء والموردين) |
| `nano_offline/views/items_view.py` | `ItemsCenter` | `items_view()` |
| `nano_offline/views/security_view.py` | `SecurityCenter` | `show_security()` |

### النتيجة على main.py
```
قبل:  1,303 سطر
بعد:    539 سطر   (تخفيض 59%)
```
`main.py` الآن يحتوي فقط: هيكل الصفحة (Shell)، شريط التنقل الجانبي/السفلي،
التوجيه (routing عبر قاموس actions)، ونقطة الدخول `main()`. كل منطق عرض
قسم محدد انتقل لملفه الخاص.

## كيف تعاملت مع الاعتماديات المتبادلة (بدون تغيير أي سلوك)

1. **`party_view` / `items_view` / `show_security`** كانت مستقلة تمامًا (لا تعتمد
   على دوال أخرى معرّفة لاحقًا في `build_shell`). نقلتها بأمان كامل مع الحفاظ على
   نفس المنطق حرفيًا — فقط استبدال `page`/`ctx`/`content`/`notify`/`money` بأسماء
   محلية مُعرّفة من `self.*` في بداية `show_center()`، لتبقى بقية الكود (المئات من
   الأسطر) **بدون أي تعديل نصي إضافي**، مما يقلل احتمال الخطأ إلى الحد الأدنى.

2. **`show_dashboard`** كانت الحالة الوحيدة المعقدة: تستدعي `navigate()`,
   `open_sale()`, `open_purchase()` المعرّفة *لاحقًا* في `build_shell` (اعتماد أمامي
   forward reference). هذا النمط كان موجودًا أصلًا في الكود القديم ويعمل بسبب
   late-binding closures في بايثون. حافظت على نفس الأسلوب:
   ```python
   dashboard_center = DashboardCenter(
       page, ctx, content,
       on_navigate=lambda key: navigate(key),      # navigate معرّفة لاحقًا في نفس build_shell
       on_open_sale=lambda: open_sale(),
       on_open_purchase=lambda: open_purchase(),
   )
   ```
   بما أن `dashboard_center` يُبنى **داخل** `build_shell` (وليس في ملف خارجي منفصل عن
   السياق)، فإن الـlambdas هذه لا تزال تُغلق (close over) على المتغيرات المحلية لـ
   `build_shell`، وتُحل الأسماء وقت الاستدعاء الفعلي (عند الضغط على زر)، تمامًا كما
   كانت تعمل قبل التعديل.

3. **الاستدعاء الذاتي في `items_view`**: الكود الأصلي كان يستدعي `items_view()` من
   داخل نفسه لإعادة تحميل الشاشة كاملة بعد إضافة تصنيف/وحدة جديدة. استبدلته بـ
   `self.show_center()` — نفس السلوك تمامًا.

## التحقق الذي تم إجراؤه
- ✅ `python -m py_compile` على الملف الرئيسي و4 الملفات الجديدة — نجح
- ✅ `python -m compileall src tools` على كامل المشروع — نجح
- ✅ `ast.parse()` على كل الملفات المعدّلة — لا أخطاء بنيوية
- ✅ فحصت يدويًا عبر grep أنه لا توجد أي إشارة متبقية لأسماء الدوال القديمة
  (`show_dashboard`, `party_view`, `items_view()`, `show_security`) في `main.py`
- ✅ `tools/core_smoke_test.py` (منطق محاسبي، مستقل عن Flet) — نجح بنفس النتائج
- ⚠️ نفس القيد السابق: لم أستطع تشغيل اختبارات واجهة Flet (`phase*_flet_ui_contract_smoke_test.py`)
  لعدم توفر إنترنت لتثبيت حزمة `flet` في بيئتي. **يُنصح بشدة** بتشغيل
  `PYTHONPATH=src python tools/quality_gate.py` كاملاً عندك، خصوصًا الاختبارات التالية
  ذات الصلة المباشرة بما تم تعديله:
  - `tools/phase2_flet_ui_contract_smoke_test.py`
  - `tools/phase3_flet_ui_contract_smoke_test.py`
  - `tools/phase4_flet_ui_contract_smoke_test.py`
  - `tools/phase5_admin_ui_contract_smoke_test.py`
  - `tools/invoice_ui_android_regression_smoke_test.py`
  - `tools/search_select_contract_smoke_test.py`
  - `tools/quick_auth_saved_login_smoke_test.py`
  - `tools/qeid_reference_design_phase1_smoke_test.py` و `phase2`

## ملاحظة حول الاستيراد
تم حذف `SearchSelect` من استيراد `main.py` (لم يعد مستخدَمًا هناك — انتقل استخدامه
بالكامل إلى `items_view.py`)، وأُبقي على `PatternPad` لأنه لا يزال مستخدمًا في مكان
آخر من `main.py` (شاشة الدخول السريع بـ PIN/نمط في `main()`).

## الخطوة التالية المقترحة
- استخراج `nav_button` / `mobile_item` / `show_more` / الشريط الجانبي إلى
  `nano_offline/views/shell_navigation.py` لتقليص `main.py` أكثر (~539 → ~250 سطر تقريبًا).
- إضافة `ruff` إلى بيئة التطوير لفحص static analysis تلقائي عند كل تعديل مستقبلي.
