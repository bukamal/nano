from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
main = (ROOT / "src/main.py").read_text(encoding="utf-8")
invoice = (ROOT / "src/nano_offline/views/invoice_view.py").read_text(encoding="utf-8")

for token in [
    "sale_fab",
    'mobile_item("dashboard", "الرئيسية"',
    'mobile_item("items", "المواد"',
    'mobile_item("invoices", "الفواتير"',
    'mobile_item("more", "المزيد"',
    'ft.Text("نظام المحاسبة الذكي"',
    'ft.Text("إجراءات سريعة"',
    'ft.Text("آخر الفواتير"',
    'ft.Text("تنبيهات"',
    'def show_more',
]:
    assert token in main, token

for token in [
    'label="بحث في الفواتير"',
    'filters = {"type": "all", "status": "all"}',
    'chip("مبيعات"',
    'chip("مشتريات"',
    'ft.FilledButton("بيع جديد"',
    'ft.OutlinedButton("شراء جديد"',
]:
    assert token in invoice, token

assert "NavigationRail(" not in main
assert "NavigationBar(" not in main
print("qeid_reference_design_phase1_smoke_test passed")
