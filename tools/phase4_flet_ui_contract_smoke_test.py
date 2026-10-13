from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
main = (ROOT / "src/main.py").read_text(encoding="utf-8")
view = (ROOT / "src/nano_offline/views/reports_view.py").read_text(encoding="utf-8")
ctx = (ROOT / "src/nano_offline/app_context.py").read_text(encoding="utf-8")

required_main = [
    "from nano_offline.views.reports_view import ReportsCenter",
    "reports_center = ReportsCenter(",
    "on_open_statement=open_statement",
    "on_open_invoice=invoice_center.show_invoice_detail",
    "reports_center.show_center",
    '"التقارير"',
    "ft.Icons.QUERY_STATS_OUTLINED",
]
for token in required_main:
    assert token in main, token

for token in [
    'self._set_header("التقارير"',
    '"قائمة الدخل والربحية"',
    '"ربحية الفواتير والمواد"',
    '"حركة وتقييم المخزون"',
    '"ذمم العملاء والموردين"',
    '"حركة الصندوق"',
    "ResponsiveRow",
    "date_from",
    "date_to",
]:
    assert token in view, token

assert "reports: ReportingService" in ctx
assert "reports=ReportingService(db)" in ctx
print("phase4_flet_ui_contract_smoke_test passed")
