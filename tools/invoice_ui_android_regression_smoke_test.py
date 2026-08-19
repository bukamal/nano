from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
invoice = (ROOT / "src/nano_offline/views/invoice_view.py").read_text(encoding="utf-8")
main = (ROOT / "src/main.py").read_text(encoding="utf-8")

# Regression contract for the Android gray-screen incident.
for token in [
    "def _show_center_error",
    "تعذر تحميل شاشة الفواتير",
    "بحث برقم الفاتورة أو العميل / المورد",
    "status_filter",
    "type_filter",
    "def _invoice_more_dialog",
    "فواتير مفتوحة",
    "ResponsiveRow(action_controls",
]:
    assert token in invoice, token

# Avoid rebuilding the old dense all-actions row that triggered the mobile rewrite.
assert "ft.Row(actions, wrap=True)" not in invoice

# Status-bar and materials mobile UX corrections.
assert "ft.SafeArea(root, expand=True)" in main
assert 'ft.Text("المواد", size=24' in main
assert '"التصنيفات والوحدات"' in main
assert 'visible=False' in main

print("invoice_ui_android_regression_smoke_test passed")
