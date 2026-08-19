from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
main = (ROOT / "src/main.py").read_text(encoding="utf-8")
invoice = (ROOT / "src/nano_offline/views/invoice_view.py").read_text(encoding="utf-8")
finance = (ROOT / "src/nano_offline/views/finance_view.py").read_text(encoding="utf-8")
admin = (ROOT / "src/nano_offline/views/admin_view.py").read_text(encoding="utf-8")
docs = (ROOT / "src/nano_offline/services/document_service.py").read_text(encoding="utf-8")

for needle in [
    "NativeFiles()",
    "page.overlay.append(native_files)",
    "mobile_primary",
    "mobile_secondary",
    'ft.Text("المزيد"',
    'ft.Icons.MORE_HORIZ',
]:
    assert needle in main, needle
for needle in ["طباعة", "PDF", "print_html", "share_pdf"]:
    assert needle in invoice, needle
for needle in ["طباعة الكشف", "مشاركة PDF", "statement_html"]:
    assert needle in finance, needle
for needle in ["مشاركة النسخة", "استيراد نسخة من الجهاز", "pick_file", "share_file", "nanobackup", "qeidbackup"]:
    assert needle in admin, needle
for needle in ['lang="ar" dir="rtl"', "invoice_html", "statement_html", "@page"]:
    assert needle in docs, needle

print("phase7_ui_contract_smoke_test passed")
