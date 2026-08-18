from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
main = (ROOT / "src/main.py").read_text(encoding="utf-8")
finance = (ROOT / "src/qeid_offline/views/finance_view.py").read_text(encoding="utf-8")
invoice = (ROOT / "src/qeid_offline/views/invoice_view.py").read_text(encoding="utf-8")
payment_service = (ROOT / "src/qeid_offline/services/payment_service.py").read_text(encoding="utf-8")

required_main = [
    "FinanceCenter",
    '"المالية"',
    "finance_center.show_center",
]
for token in required_main:
    assert token in main, token

required_finance = [
    "سند قبض",
    "سند صرف",
    "الأقدم أولًا تلقائيًا",
    "توزيع يدوي",
    "رصيد على الحساب دون توزيع",
    "المصروفات",
    "كشف حساب العملاء",
    "كشف حساب الموردين",
]
for token in required_finance:
    assert token in finance, token

assert '"تسجيل دفعة"' in invoice
assert 'existing["initial_paid_amount"]' in invoice
assert 'existing["paid_amount"] if existing else 0' not in invoice
assert "register_invoice_payment" in invoice
assert "payment_allocations" in payment_service
assert "allocatable_invoices" in payment_service

print("phase3_flet_ui_contract_smoke_test passed")
