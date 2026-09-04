from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
main = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
invoice_ui = (ROOT / "src" / "nano_offline" / "views" / "invoice_view.py").read_text(encoding="utf-8")
invoice_service = (ROOT / "src" / "nano_offline" / "services" / "invoice_service.py").read_text(encoding="utf-8")
item_repo = (ROOT / "src" / "nano_offline" / "repositories" / "item_repository.py").read_text(encoding="utf-8")
all_text = "\n".join([main, invoice_ui, invoice_service, item_repo]).lower()

required_ui = [
    "class InvoiceCenter",
    "فاتورة بيع",
    "إضافة بند",
    "حفظ الفاتورة",
    "تعديل فاتورة",
    "تأكيد حذف الفاتورة",
    "sidebar",
    "mobile_bar",
    "sale_fab",
    "ResponsiveRow",
    "conversion_factor",
    "base_price",
]
for token in required_ui:
    assert token in main + invoice_ui + invoice_service + item_repo, token

for token in ["def update_invoice", "def delete_invoice", "def list_invoices", "def get_invoice"]:
    assert token in invoice_service, token
assert "AccountingRebuilder.rebuild" in invoice_service

assert "def units(" in item_repo
for forbidden in ["telegram", "supabase", "vercel", "service_role_key"]:
    assert forbidden not in all_text, forbidden

print("phase2_flet_ui_contract_smoke_test passed")

assert "label=ft.Text(label)" not in main
assert "page.show_dialog" not in main + invoice_ui
assert "state[\"base_price\"] * float(state.get(\"factor\") or 1)" in invoice_ui
