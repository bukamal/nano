from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
main = (ROOT / "src/main.py").read_text(encoding="utf-8")
invoice = (ROOT / "src/nano_offline/views/invoice_view.py").read_text(encoding="utf-8")
dashboard = (ROOT / "src/nano_offline/views/dashboard_view.py").read_text(encoding="utf-8")

for token in [
    "sale_fab",
    'mobile_item("dashboard", "الرئيسية"',
    'mobile_item("items", "المواد"',
    'mobile_item("invoices", "الفواتير"',
    'mobile_item("more", "المزيد"',
    'ft.Text("نظام المحاسبة الذكي"',
    'def show_more',
]:
    assert token in main, token

# Dashboard body content moved into DashboardCenter (nano_offline/views/dashboard_view.py)
# as part of the 2026-08 refactor that split main.py's view closures into
# Center classes; same functional guarantee, new location.
for token in [
    'ft.Text("إجراءات سريعة"',
    'ft.Text("آخر الفواتير"',
    'ft.Text("تنبيهات"',
]:
    assert token in dashboard, token

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
