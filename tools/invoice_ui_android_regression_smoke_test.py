from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
invoice = (ROOT / "src/nano_offline/views/invoice_view.py").read_text(encoding="utf-8")
main = (ROOT / "src/main.py").read_text(encoding="utf-8")

# Regression contract for the Android gray-screen incident.
for token in [
    "def _show_center_error",
    "تعذر تحميل شاشة الفواتير",
    "بحث في الفواتير",
    'filters = {"type": "all", "status": "all"}',
    "def set_filter",
    "def _invoice_more_dialog",
    "فواتير مفتوحة",
    "ft.Row(actions, spacing=8, wrap=True)",
]:
    assert token in invoice, token

# Actions remain compact and limited; the dense legacy all-actions row is not used.
assert "طباعة" in invoice and "مشاركة PDF" in invoice

# Status-bar and materials mobile UX corrections.
assert "ft.SafeArea(root, expand=True)" in main
assert 'set_header("المواد"' in main
assert '"التصنيفات والوحدات"' in main
assert 'visible=False' in main

print("invoice_ui_android_regression_smoke_test passed")
