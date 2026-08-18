# المرحلة 1 — تحويل قيد إلى Flet أوفلاين

تم استبدال الاعتماد المعماري المتوقع على Telegram/Supabase/Vercel بطبقة بيانات محلية SQLite. هذه المرحلة لا تنقل JavaScript حرفيًا؛ بل تثبت عقد البيانات والحسابات الذي ستبنى عليه بقية الواجهات.

## المطابقة مع المشروع الأصلي

- العملاء: name / phone / address / balance.
- الموردون: نفس بنية الأطراف.
- التعريفات: categories وunits(name, abbreviation).
- المواد: category_id, item_type, purchase_price, selling_price, quantity, base_unit_id, item_units, average_cost.
- الفواتير: sale/purchase، customer_id/supplier_id، date/reference/notes، lines، paid_amount.
- المخزون: تحويل كمية الوحدة إلى base quantity، تكلفة متوسطة في الشراء، وتثبيت cost_amount في البيع.

## اختلاف مقصود

أضيف ledger_entries وinventory_movements كطبقة مرجعية محلية، حتى لا تعتمد التقارير المستقبلية على تجميع عدة مصادر بطريقة قد تسبب ازدواجية.

## التفعيل

license_state موجود محليًا فقط. Endpoint التفعيل والتوقيع الرقمي لم يثبت بعد لأن عنوان خادم الترخيص ومفتاح التوقيع العام غير محددين. لا يوجد أي اتصال إنترنت في مسار الحسابات أو المخزون.
