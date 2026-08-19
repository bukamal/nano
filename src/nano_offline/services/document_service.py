from __future__ import annotations

from html import escape

from nano_offline.core.database import Database
from nano_offline.services.invoice_service import InvoiceService
from nano_offline.services.statement_service import StatementService


class DocumentService:
    """Offline print-ready HTML documents for native Android/iOS printing/PDF."""

    def __init__(self, db: Database, invoices: InvoiceService, statements: StatementService):
        self.db = db
        self.invoices = invoices
        self.statements = statements

    def _settings(self) -> dict[str, str]:
        with self.db.connect() as conn:
            return {str(r["key"]): str(r["value"]) for r in conn.execute("SELECT key,value FROM settings").fetchall()}

    @staticmethod
    def _money(value: float | int | None) -> str:
        return f"{float(value or 0):,.2f}"

    @staticmethod
    def _e(value) -> str:
        return escape(str(value or ""), quote=True)

    def _shell(self, title: str, body: str) -> str:
        settings = self._settings()
        company = self._e(settings.get("company_name") or "نانو")
        currency = self._e(settings.get("currency") or "USD")
        return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{self._e(title)}</title>
<style>
@page {{ size: A4; margin: 12mm; }}
* {{ box-sizing: border-box; }}
body {{ direction: rtl; font-family: Tahoma, Arial, sans-serif; color:#172033; margin:0; font-size:12px; }}
.sheet {{ width:100%; }}
.header {{ border-bottom:3px solid #0B63F6; padding-bottom:10px; margin-bottom:14px; }}
.brand {{ color:#0B63F6; font-size:24px; font-weight:700; }}
.doc-title {{ font-size:19px; font-weight:700; margin-top:5px; }}
.meta {{ color:#64748B; margin-top:4px; line-height:1.8; }}
.grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin:12px 0; }}
.metric {{ border:1px solid #D8E1EA; border-radius:8px; padding:8px; }}
.metric small {{ display:block; color:#64748B; margin-bottom:4px; }}
.metric strong {{ font-size:15px; }}
table {{ width:100%; border-collapse:collapse; margin-top:10px; }}
th {{ background:#0B63F6; color:#fff; padding:7px 5px; border:1px solid #0B63F6; }}
td {{ padding:6px 5px; border:1px solid #D8E1EA; vertical-align:top; }}
tr:nth-child(even) td {{ background:#F8FAFC; }}
.money {{ direction:ltr; unicode-bidi:isolate; white-space:nowrap; }}
.note {{ border:1px solid #BFD5E8; background:#EEF6FC; border-radius:8px; padding:8px; margin-top:10px; }}
.footer {{ margin-top:14px; border-top:1px solid #D8E1EA; padding-top:8px; color:#64748B; font-size:10px; }}
.currency::after {{ content:' {currency}'; }}
</style>
</head>
<body><div class="sheet">
<div class="header"><div class="brand">{company}</div><div class="doc-title">{self._e(title)}</div></div>
{body}
<div class="footer">تم إنشاء المستند محليًا بواسطة Nano | نانو</div>
</div></body></html>"""

    def invoice_html(self, invoice_id: int) -> str:
        inv = self.invoices.get_invoice(invoice_id)
        if not inv:
            raise ValueError("الفاتورة غير موجودة")
        kind = "فاتورة بيع" if inv["type"] == "sale" else "فاتورة شراء"
        party_label = "العميل" if inv["type"] == "sale" else "المورد"
        status = {
            "paid": "مدفوعة",
            "partial": "مدفوعة جزئيًا",
            "unpaid": "غير مدفوعة",
        }.get(inv.get("payment_status"), str(inv.get("payment_status") or ""))

        line_rows = []
        for idx, line in enumerate(inv["lines"], start=1):
            description = line.get("description") or line.get("item_name") or "—"
            unit = line.get("unit_abbreviation") or line.get("unit_name") or "—"
            line_rows.append(
                f"<tr><td>{idx}</td><td>{self._e(description)}</td>"
                f"<td>{self._e(unit)}</td><td class='money'>{self._money(line['quantity'])}</td>"
                f"<td class='money'>{self._money(line['unit_price'])}</td>"
                f"<td class='money'>{self._money(line['total'])}</td></tr>"
            )

        remaining = max(0.0, float(inv.get("remaining_amount") or 0))
        body = f"""
<div class="meta">رقم الفاتورة: <b>#{int(inv['id'])}</b> &nbsp; | &nbsp; التاريخ: {self._e(inv['invoice_date'])}</div>
<div class="meta">{party_label}: <b>{self._e(inv.get('party_name') or 'نقدي')}</b>"
{(' &nbsp; | &nbsp; المرجع: ' + self._e(inv.get('reference'))) if inv.get('reference') else ''}</div>
<div class="grid">
  <div class="metric"><small>الإجمالي</small><strong class="money">{self._money(inv['total'])}</strong></div>
  <div class="metric"><small>المدفوع</small><strong class="money">{self._money(inv['paid_amount'])}</strong></div>
  <div class="metric"><small>المتبقي</small><strong class="money">{self._money(remaining)}</strong></div>
</div>
<div class="meta">الحالة: <b>{self._e(status)}</b></div>
<table>
<thead><tr><th>#</th><th>البيان</th><th>الوحدة</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th></tr></thead>
<tbody>{''.join(line_rows)}</tbody>
</table>
{f'<div class="note"><b>ملاحظات:</b> {self._e(inv.get("notes"))}</div>' if inv.get('notes') else ''}
"""
        return self._shell(f"{kind} #{int(inv['id'])}", body)

    def statement_html(
        self,
        party_type: str,
        party_id: int,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> str:
        data = self.statements.party_statement(
            party_type,
            party_id,
            date_from=date_from,
            date_to=date_to,
        )
        party = data["party"]
        kind = "عميل" if party_type == "customer" else "مورد"
        rows = []
        for idx, row in enumerate(data["rows"], start=1):
            movement = float(row.get("movement") or 0)
            rows.append(
                f"<tr><td>{idx}</td><td>{self._e(row['entry_date'])}</td>"
                f"<td>{self._e(row.get('description') or row.get('source_label'))}</td>"
                f"<td>{self._e(row.get('source_label'))} #{self._e(row.get('source_id') or '—')}</td>"
                f"<td class='money'>{self._money(movement)}</td>"
                f"<td class='money'>{self._money(row.get('balance'))}</td></tr>"
            )
        period = "كل الفترات"
        if date_from or date_to:
            period = f"من {self._e(date_from or 'البداية')} إلى {self._e(date_to or 'النهاية')}"
        balance = float(data["current_balance"] or 0)
        current_label = "مستحق على الحساب" if balance >= 0 else "رصيد دائن للطرف"
        body = f"""
<div class="meta">الحساب: <b>{self._e(party['name'])}</b> &nbsp; | &nbsp; النوع: {kind} &nbsp; | &nbsp; الفترة: {period}</div>
<div class="grid">
  <div class="metric"><small>الرصيد الافتتاحي</small><strong class="money">{self._money(data['opening_balance'])}</strong></div>
  <div class="metric"><small>الرصيد الختامي للفترة</small><strong class="money">{self._money(data['closing_balance'])}</strong></div>
  <div class="metric"><small>الرصيد الحالي</small><strong class="money">{self._money(abs(balance))} — {self._e(current_label)}</strong></div>
</div>
<table>
<thead><tr><th>#</th><th>التاريخ</th><th>البيان</th><th>المصدر</th><th>الحركة</th><th>الرصيد</th></tr></thead>
<tbody>{''.join(rows) if rows else '<tr><td colspan="6">لا توجد حركات في الفترة المحددة.</td></tr>'}</tbody>
</table>
"""
        return self._shell(f"كشف حساب {kind} — {party['name']}", body)
