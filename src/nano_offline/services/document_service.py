from __future__ import annotations

from html import escape

from nano_offline.core.barcode128 import code128b_svg
from nano_offline.core.qr_gen import qr_svg
from nano_offline.core.invoice_signing import sign_invoice
from nano_offline.core.database import Database
from nano_offline.core import currency
from nano_offline.core import invoice_settings
from nano_offline.services.invoice_service import InvoiceService
from nano_offline.services.statement_service import StatementService

# Modern default accent -- overridden per-install by the `invoice_color`
# setting (see AdminCenter's branding section). Kept as a module constant
# so both the invoice shell and the barcode-label sheet fall back to the
# same color when the user hasn't customized it yet.
_DEFAULT_ACCENT = "#0F766E"

_STATUS_STYLE = {
    "paid": ("مدفوعة", "#0F766E", "#E4F5F1"),
    "partial": ("مدفوعة جزئيًا", "#B45309", "#FCF1DC"),
    "unpaid": ("غير مدفوعة", "#B42318", "#FBE9E7"),
}


class DocumentService:
    """Offline print-ready HTML documents for native Android/iOS printing/PDF."""

    def __init__(self, db: Database, invoices: InvoiceService, statements: StatementService):
        self.db = db
        self.invoices = invoices
        self.statements = statements

    def _settings(self) -> dict[str, str]:
        with self.db.connect() as conn:
            return {str(r["key"]): str(r["value"]) for r in conn.execute("SELECT key,value FROM settings").fetchall()}

    def _money_parts(self, value: float | int | None, inv: dict | None = None) -> tuple[str, str]:
        """Return ``(amount_text, symbol)`` for a stored USD amount, at whichever
        rate/symbol applies (see :meth:`_money`), with no formatting glue between
        them -- the caller decides how to lay the two out.
        """
        if inv is not None and inv.get("invoice_exchange_rate") is not None:
            rate = float(inv["invoice_exchange_rate"])
            symbol = inv.get("invoice_currency_symbol") or currency.DEFAULT_DISPLAY_SYMBOL
            decimals = 2 if (inv.get("invoice_currency_code") == currency.DISPLAY_CURRENCY_USD) else 0
            amount_text = currency.format_amount(value, rate=rate, symbol=symbol, decimals=decimals, with_symbol=False)
        else:
            settings = self._settings()
            symbol = currency.get_display_symbol(settings)
            amount_text = currency.format_amount(value, settings, with_symbol=False)
        return amount_text, symbol

    def _money_text(self, value: float | int | None, inv: dict | None = None) -> str:
        """Plain "amount symbol" text, for contexts that can't hold HTML (e.g. QR payloads).

        Uses the same LRI/PDI isolate as ``currency._amount_with_symbol`` --
        see that function's docstring -- since this plain-text path has no
        CSS available to pin the symbol's side the way ``_money()``'s
        ``.money-wrap`` does.
        """
        amount_text, symbol = self._money_parts(value, inv)
        return currency._amount_with_symbol(amount_text, symbol)

    def _money(self, value: float | int | None, inv: dict | None = None) -> str:
        """Format a stored USD amount for printing, as HTML.

        When ``inv`` is given and carries a historical rate/currency snapshot
        (see ``invoice_exchange_rate`` on the ``invoices`` table), the amount
        is rendered at *that* rate -- the one actually in force when the
        invoice was issued -- instead of today's configured rate, so an old
        invoice never silently re-prices itself after the admin updates the
        exchange rate. Falls back to the live settings for documents with no
        such snapshot (statements, barcode labels, legacy rows).

        The amount and the currency symbol are wrapped in their own ``<span>``
        elements inside an inline-flex ``.money-wrap`` container instead of
        being written as one plain "amount symbol" text run. Some print
        layouts (three-up totals rows in particular) mix this right-to-left
        page with left-to-right amount text closely enough that the browser's
        automatic bidi reordering places the symbol on the wrong side of the
        number -- flex layout order doesn't depend on that reordering, so the
        symbol always lands after the amount as intended.
        """
        amount_text, symbol = self._money_parts(value, inv)
        return (
            f'<span class="money-wrap"><span class="amt">'
            f'{amount_text}</span><span class="sym">{self._e(symbol)}</span></span>'
        )

    @staticmethod
    def _qty(value: float | int | None) -> str:
        return f"{float(value or 0):,.2f}"

    @staticmethod
    def _e(value) -> str:
        return escape(str(value or ""), quote=True)

    @staticmethod
    def _accent_tint(hex_color: str, amount: float = 0.92) -> str:
        """Return a very light tint of ``hex_color`` for header/card backgrounds."""
        try:
            h = hex_color.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            r = int(r + (255 - r) * amount)
            g = int(g + (255 - g) * amount)
            b = int(b + (255 - b) * amount)
            return f"#{r:02X}{g:02X}{b:02X}"
        except Exception:
            return "#F8FAFC"

    @staticmethod
    def _accent_shade(hex_color: str, amount: float = 0.22) -> str:
        """Return a slightly darker shade of ``hex_color`` (for gradients/borders)."""
        try:
            h = hex_color.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            r = int(r * (1 - amount))
            g = int(g * (1 - amount))
            b = int(b * (1 - amount))
            return f"#{r:02X}{g:02X}{b:02X}"
        except Exception:
            return hex_color

    def _shell(self, title: str, subtitle: str, body: str) -> str:
        settings = self._settings()
        company = self._e(settings.get("company_name") or "نانو")
        display_symbol = self._e(currency.get_display_symbol(settings))
        accent = settings.get("invoice_color") or _DEFAULT_ACCENT
        accent_deep = self._accent_shade(accent)
        tint = self._accent_tint(accent)
        logo = settings.get("company_logo") or ""
        logo_html = f'<img src="{self._e(logo)}" alt="" class="logo"/>' if logo else '<div class="logo logo-fallback"></div>'
        return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{self._e(title)}</title>
<style>
@page {{ size: A4; margin: 12mm; }}
* {{ box-sizing: border-box; }}
html, body {{ padding:0; }}
body {{
  direction: rtl;
  font-family: 'Cairo', 'Segoe UI', Tahoma, Arial, sans-serif;
  color:#1E293B;
  margin:0;
  font-size:12px;
  line-height:1.55;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}}
.sheet {{ width:100%; }}
.header {{
  display:flex; align-items:center; gap:14px;
  padding:14px 16px; margin-bottom:16px; border-radius:12px;
  background: linear-gradient(135deg, {tint} 0%, #FFFFFF 65%);
  border:1px solid #E2E8F0;
  border-top:4px solid {accent};
}}
.logo {{ height:48px; max-width:130px; object-fit:contain; border-radius:6px; }}
.logo-fallback {{ height:44px; width:44px; border-radius:10px; background:{accent}; }}
.header-text {{ flex:1; min-width:0; }}
.brand {{ color:{accent_deep}; font-size:21px; font-weight:800; letter-spacing:.2px; }}
.doc-title-row {{ display:flex; align-items:center; gap:8px; margin-top:6px; flex-wrap:wrap; }}
.doc-title {{ font-size:16px; font-weight:700; color:#0F172A; }}
.doc-subtitle {{ font-size:11px; color:#64748B; }}
.badge {{
  display:inline-block; padding:3px 10px; border-radius:999px;
  font-size:10.5px; font-weight:700;
}}
.doc-number {{
  font-size:11px; color:#fff; background:{accent}; border-radius:8px;
  padding:5px 10px; font-weight:700; white-space:nowrap;
}}
.meta-row {{
  display:flex; flex-wrap:wrap; gap:8px 22px; margin:2px 0 14px;
  color:#334155; font-size:11.5px;
}}
.meta-row b {{ color:#0F172A; }}
.meta-row .sep {{ color:#CBD5E1; }}
.grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin:4px 0 16px; }}
.metric {{
  border:1px solid #E2E8F0; border-radius:10px; padding:10px 12px;
  background:#F8FAFC; position:relative; overflow:hidden;
}}
.metric::before {{
  content:''; position:absolute; inset-inline-start:0; top:0; bottom:0; width:4px; background:{accent};
}}
.metric small {{ display:block; color:#64748B; margin-bottom:5px; font-size:10.5px; font-weight:600; }}
.metric strong {{ font-size:15px; font-weight:800; color:#0F172A; }}
.rate-note {{
  display:flex; align-items:center; gap:6px; margin:0 0 14px; padding:7px 11px;
  border:1px dashed #CBD5E1; border-radius:8px; background:#FBFCFE;
  color:#475569; font-size:10.5px;
}}
.rate-note b {{ color:{accent_deep}; direction:ltr; unicode-bidi:isolate; }}
table {{ width:100%; border-collapse:collapse; margin-top:6px; border-radius:8px; overflow:hidden; }}
thead th {{
  background:{accent}; color:#fff; padding:8px 6px; font-size:11px; font-weight:700;
  border-inline-end:1px solid rgba(255,255,255,.25);
}}
th:first-child {{ border-top-right-radius:8px; }}
th:last-child {{ border-top-left-radius:8px; }}
td {{ padding:7px 6px; border-bottom:1px solid #E9EEF3; vertical-align:top; font-size:11.5px; }}
tbody tr:nth-child(even) td {{ background:#F8FAFC; }}
tbody tr:last-child td {{ border-bottom:1px solid #E2E8F0; }}
.money {{ white-space:nowrap; text-align:end; }}
.money-wrap {{
  display:inline-flex; align-items:baseline; gap:3px;
  direction:ltr; unicode-bidi:isolate; white-space:nowrap; font-variant-numeric:tabular-nums;
}}
.note {{ border:1px solid #BFD5E8; background:#EEF6FC; border-radius:10px; padding:10px 12px; margin-top:14px; font-size:11.5px; }}
.note b {{ color:{accent_deep}; }}
.footer {{
  margin-top:20px; border-top:1px solid #E2E8F0; padding-top:10px;
  display:flex; justify-content:space-between; color:#94A3B8; font-size:9.5px;
}}
.currency::after {{ content:' {display_symbol}'; }}
.sheet {{ position:relative; }}
.watermark {{
  position:absolute; inset-inline-start:50%; top:44%; transform:translate(-50%,-50%) rotate(-28deg);
  font-size:64px; font-weight:800; color:#B42318; opacity:.09; letter-spacing:4px;
  white-space:nowrap; pointer-events:none; z-index:0;
}}
.num-barcode {{ line-height:0; }}
.num-barcode svg {{ height:22px; width:auto; display:block; }}
.progress-wrap {{ margin:0 0 16px; }}
.progress-label {{
  display:flex; justify-content:space-between; font-size:10.5px; color:#64748B;
  margin-bottom:4px; font-weight:600;
}}
.progress-track {{ height:7px; border-radius:999px; background:#E9EEF3; overflow:hidden; }}
.progress-fill {{ height:100%; border-radius:999px; background:{accent}; }}
.metric .fx {{ display:block; margin-top:2px; font-size:10px; font-weight:600; color:#94A3B8; }}
.sign-row {{ display:flex; gap:16px; margin-top:26px; align-items:flex-end; }}
.sign-box {{
  flex:1; border:1px dashed #CBD5E1; border-radius:10px; padding:22px 10px 8px;
  text-align:center; font-size:10.5px; color:#64748B;
}}
.verify-box {{
  flex:0 0 auto; text-align:center; font-size:9px; color:#64748B; line-height:1.4;
}}
.verify-box svg {{ width:64px; height:64px; display:block; margin:0 auto 4px; }}
</style>
</head>
<body><div class="sheet">
<div class="header">
  {logo_html}
  <div class="header-text">
    <div class="brand">{company}</div>
    <div class="doc-title-row"><span class="doc-title">{self._e(subtitle)}</span></div>
  </div>
  <div class="doc-number">{self._e(title)}</div>
</div>
{body}
<div class="footer"><span>تم إنشاء المستند محليًا بواسطة نانو</span><span>Nano Offline</span></div>
</div></body></html>"""

    def invoice_html(self, invoice_id: int) -> str:
        inv = self.invoices.get_invoice(invoice_id)
        if not inv:
            raise ValueError("الفاتورة غير موجودة")
        settings = self._settings()
        kind = "فاتورة بيع" if inv["type"] == "sale" else "فاتورة شراء"
        party_label = "العميل" if inv["type"] == "sale" else "المورد"
        status_key = str(inv.get("payment_status") or "unpaid")
        status_text, status_fg, status_bg = _STATUS_STYLE.get(status_key, ("—", "#475569", "#F1F5F9"))

        line_rows = []
        for idx, line in enumerate(inv["lines"], start=1):
            description = line.get("description") or line.get("item_name") or "—"
            unit = line.get("unit_abbreviation") or line.get("unit_name") or "—"
            line_rows.append(
                f"<tr><td>{idx}</td><td>{self._e(description)}</td>"
                f"<td>{self._e(unit)}</td><td class='money'>{self._qty(line['quantity'])}</td>"
                f"<td class='money'>{self._money(line['unit_price'], inv)}</td>"
                f"<td class='money'>{self._money(line['total'], inv)}</td></tr>"
            )

        remaining = max(0.0, float(inv.get("remaining_amount") or 0))
        reference_html = (
            f'<span class="sep">|</span> المرجع: <b>{self._e(inv.get("reference"))}</b>'
            if inv.get("reference")
            else ""
        )

        rate_html = ""
        rate = inv.get("invoice_exchange_rate")
        code = inv.get("invoice_currency_code")
        has_fx = rate is not None and code == currency.DISPLAY_CURRENCY_SYP
        if has_fx:
            rate_html = (
                '<div class="rate-note">سعر صرف الدولار وقت إصدار الفاتورة: '
                f'<b>1 $ = {float(rate):,.0f} {self._e(inv.get("invoice_currency_symbol") or "ل.س")}</b>'
                "</div>"
            )

        def _fx_line(value) -> str:
            # Stored amounts are always USD (see currency.py); when the invoice
            # was issued while displaying SYP, show the USD figure underneath
            # so the printed slip carries both currencies without forcing the
            # reader back up to the rate-note to do the conversion themselves.
            return f'<span class="fx">${float(value or 0):,.2f}</span>' if has_fx else ""

        num_barcode = code128b_svg(str(int(inv["id"])), width=100, height=26, show_text=False, bar_color="#0F172A")
        total = float(inv.get("total") or 0)
        party_key = str(inv.get("customer_id") or inv.get("supplier_id") or inv.get("party_name") or "-")
        verify_token = sign_invoice(
            self.db, invoice_id=int(inv["id"]), invoice_date=str(inv["invoice_date"]), total=total, party_key=party_key
        )
        verify_qr = qr_svg(verify_token, size=64, level="M", quiet_zone=1, dark="#0F172A")
        paid = float(inv.get("paid_amount") or 0)
        paid_ratio = max(0.0, min(1.0, (paid / total))) if total > 1e-9 else 1.0
        watermark_html = '<div class="watermark">غير مدفوعة</div>' if status_key == "unpaid" else ""

        # Admin-configurable display number, due date, footer terms, and
        # optional sign/verify boxes -- see core.invoice_settings. All read
        # fresh on every print, so an admin change applies retroactively to
        # every invoice's next print/PDF without touching any stored data.
        display_number = invoice_settings.format_invoice_number(int(inv["id"]), settings)
        due_date = invoice_settings.due_date_for(inv.get("invoice_date"), settings)
        due_html = (
            f'<span class="sep">|</span> الاستحقاق: <b>{self._e(due_date.isoformat())}</b>'
            if due_date and status_key != "paid"
            else ""
        )
        footer_note = invoice_settings.footer_text(settings)
        footer_html = f'<div class="note">{self._e(footer_note)}</div>' if footer_note else ""
        sign_boxes_html = (
            '<div class="sign-box">توقيع المستلم</div><div class="sign-box">ختم الشركة</div>'
            if invoice_settings.show_sign_boxes(settings)
            else ""
        )
        verify_box_html = (
            f'<div class="verify-box">{verify_qr}<span>تحقق من الفاتورة</span></div>'
            if invoice_settings.show_verify_qr(settings)
            else ""
        )

        body = f"""
{watermark_html}
<div class="meta-row">
  <span>رقم الفاتورة: <b>#{self._e(display_number)}</b></span>
  <span class="num-barcode">{num_barcode}</span>
  <span class="sep">|</span>
  <span>التاريخ: <b>{self._e(inv['invoice_date'])}</b></span>
  {due_html}
  <span class="sep">|</span>
  <span>{party_label}: <b>{self._e(inv.get('party_name') or 'نقدي')}</b></span>
  {reference_html}
  <span class="sep">|</span>
  <span class="badge" style="color:{status_fg};background:{status_bg}">{self._e(status_text)}</span>
</div>
{rate_html}
<div class="grid">
  <div class="metric"><small>الإجمالي</small><strong class="money">{self._money(inv['total'], inv)}</strong>{_fx_line(total)}</div>
  <div class="metric"><small>المدفوع</small><strong class="money">{self._money(inv['paid_amount'], inv)}</strong>{_fx_line(paid)}</div>
  <div class="metric"><small>المتبقي</small><strong class="money">{self._money(remaining, inv)}</strong>{_fx_line(remaining)}</div>
</div>
<div class="progress-wrap">
  <div class="progress-label"><span>نسبة السداد</span><span>{round(paid_ratio * 100)}٪</span></div>
  <div class="progress-track"><div class="progress-fill" style="width:{paid_ratio * 100:.1f}%"></div></div>
</div>
<table>
<thead><tr><th>#</th><th>البيان</th><th>الوحدة</th><th>الكمية</th><th>السعر</th><th>الإجمالي</th></tr></thead>
<tbody>{''.join(line_rows)}</tbody>
</table>
{f'<div class="note"><b>ملاحظات:</b> {self._e(inv.get("notes"))}</div>' if inv.get('notes') else ''}
{footer_html}
<div class="sign-row">
  {sign_boxes_html}
  {verify_box_html}
</div>
"""
        return self._shell(f"#{self._e(display_number)}", kind, body)

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
        any_historical = False
        for idx, row in enumerate(data["rows"], start=1):
            movement = float(row.get("movement") or 0)
            # Each movement is printed at the rate that applied when it
            # actually happened (its own invoice/payment snapshot); the
            # running balance stays at today's live rate since it represents
            # what is owed *now*, not a historical figure.
            hist_rate = row.get("movement_exchange_rate")
            if hist_rate is not None:
                any_historical = True
                movement_text = self._money(
                    movement,
                    {
                        "invoice_exchange_rate": hist_rate,
                        "invoice_currency_code": row.get("movement_currency_code"),
                        "invoice_currency_symbol": row.get("movement_currency_symbol"),
                    },
                )
            else:
                movement_text = self._money(movement)
            rows.append(
                f"<tr><td>{idx}</td><td>{self._e(row['entry_date'])}</td>"
                f"<td>{self._e(row.get('description') or row.get('source_label'))}</td>"
                f"<td>{self._e(row.get('source_label'))} #{self._e(row.get('source_id') or '—')}</td>"
                f"<td class='money'>{movement_text}</td>"
                f"<td class='money'>{self._money(row.get('balance'))}</td></tr>"
            )
        period = "كل الفترات"
        if date_from or date_to:
            period = f"من {self._e(date_from or 'البداية')} إلى {self._e(date_to or 'النهاية')}"
        balance = float(data["current_balance"] or 0)
        current_label = "مستحق على الحساب" if balance >= 0 else "رصيد دائن للطرف"
        body = f"""
<div class="meta-row">
  <span>الحساب: <b>{self._e(party['name'])}</b></span>
  <span class="sep">|</span>
  <span>النوع: <b>{kind}</b></span>
  <span class="sep">|</span>
  <span>الفترة: <b>{period}</b></span>
</div>
<div class="grid">
  <div class="metric"><small>الرصيد الافتتاحي</small><strong class="money">{self._money(data['opening_balance'])}</strong></div>
  <div class="metric"><small>الرصيد الختامي للفترة</small><strong class="money">{self._money(data['closing_balance'])}</strong></div>
  <div class="metric"><small>الرصيد الحالي</small><strong class="money">{self._money(abs(balance))} — {self._e(current_label)}</strong></div>
</div>
{'<div class="rate-note">عمود «الحركة» معروض بسعر الصرف وقت حدوث كل حركة، بينما «الرصيد» بالسعر الحالي دائمًا.</div>' if any_historical else ''}
<table>
<thead><tr><th>#</th><th>التاريخ</th><th>البيان</th><th>المصدر</th><th>الحركة</th><th>الرصيد</th></tr></thead>
<tbody>{''.join(rows) if rows else '<tr><td colspan="6">لا توجد حركات في الفترة المحددة.</td></tr>'}</tbody>
</table>
"""
        return self._shell(f"كشف حساب {kind}", party["name"], body)

    def barcode_labels_html(
        self,
        labels: list[dict],
        *,
        columns: int = 3,
        include_price_qr: bool = False,
        label_size: tuple[int, int] = (210, 54),
        show_text: bool = True,
        layout: str = "sheet",
        roll_width_mm: int = 58,
    ) -> str:
        """Barcode labels for printing/PDF via the native print path.

        ``labels`` is a flat list of ``{"name": str, "barcode": str, "price":
        float|None}`` -- one entry per physical sticker (the caller repeats an
        item's dict N times for N copies), so this stays a pure renderer with
        no knowledge of "copies" as a concept.

        ``include_price_qr``: when true and a label has a price, adds a small
        second QR code next to the price with plain text (item name + price)
        -- no protocol, no signature, nothing app-specific. It exists purely
        so a *customer's own phone*, with whatever generic camera/QR app they
        already have, can scan the shelf label and read the price back
        without needing this app or any network connection. This is a
        one-way, read-only convenience: the QR is baked in at print time, so
        like the printed price text right next to it, it goes stale if the
        price changes later and the label isn't reprinted.

        ``label_size``/``show_text``: admin-configurable sticker size
        (core.barcode_settings.label_dimensions) and whether the human-
        readable code is printed under the bars.

        ``layout``: ``"sheet"`` (default, unchanged from before) lays labels
        out on an A4 grid of ``columns`` columns via the shared invoice shell
        -- meant for sticker sheets on a regular printer. ``"roll"`` instead
        renders one label per printed "page" stacked full-width down a
        continuous strip sized to ``roll_width_mm`` (58/80mm are the two
        near-universal thermal roll widths) -- no grid, no invoice-style
        logo header (that would waste paper on every single label), just the
        essentials. Both go through the exact same native print/PDF pipeline
        the caller already has (services.document_service only changes the
        HTML/CSS shape of the page), so a thermal printer that's already set
        up as the OS's active/default printer works with zero extra plumbing.
        """
        settings = self._settings()
        accent = settings.get("invoice_color") or _DEFAULT_ACCENT
        lbl_width, lbl_height = label_size
        is_roll = layout == "roll"
        cells = []
        for label in labels:
            code = str(label.get("barcode") or "").strip()
            if not code:
                continue
            name = self._e(label.get("name") or "")
            price = label.get("price")
            price_qr_html = ""
            if price is not None:
                price_html = f'<div class="lbl-price">{self._money(price)}</div>'
                if include_price_qr:
                    qr_text = f"{label.get('name') or ''}\nالسعر: {self._money_text(price)}"
                    price_qr = qr_svg(qr_text, size=60, level="M", quiet_zone=1, dark="#0F172A")
                    price_qr_html = f'<div class="lbl-price-row">{price_html}<div class="lbl-price-qr">{price_qr}</div></div>'
                else:
                    price_qr_html = price_html
            # On a roll label the barcode is the whole point of the strip, so
            # it's rendered wide relative to the sticker-sheet case and then
            # scaled to fill the roll's printable width via CSS (the SVG's
            # own viewBox keeps bar proportions correct at any final size).
            svg_width = 380 if is_roll else lbl_width
            svg_height = int(lbl_height * (380 / lbl_width)) if is_roll else lbl_height
            svg = code128b_svg(code, width=svg_width, height=svg_height, show_text=show_text, bar_color="#0F172A")
            cells.append(
                f'<div class="lbl">'
                f'<div class="lbl-name">{name}</div>'
                f'<div class="lbl-barcode">{svg}</div>'
                f"{price_qr_html}"
                f"</div>"
            )
        if not cells:
            raise ValueError("لا توجد مواد لها باركود لطباعتها")

        if is_roll:
            return self._barcode_labels_roll_html(cells, accent=accent, roll_width_mm=roll_width_mm)

        tint = self._accent_tint(accent, amount=0.94)
        body = f'<div class="lbl-grid">{"".join(cells)}</div>'
        style_extra = f"""
<style>
.lbl-grid {{ display:grid; grid-template-columns:repeat({int(columns)},1fr); gap:5mm; margin-top:4px; }}
.lbl {{
  border:1px solid #E2E8F0; border-radius:8px; padding:7px 6px 8px;
  text-align:center; page-break-inside:avoid; background:#fff;
  box-shadow: inset 0 0 0 1px {tint};
}}
.lbl-name {{
  font-size:10.5px; font-weight:700; margin-bottom:4px; color:#0F172A;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}}
.lbl-barcode {{ border-top:1px dashed #E2E8F0; border-bottom:1px dashed #E2E8F0; padding:4px 0; }}
.lbl-price {{ font-size:12px; font-weight:800; direction:ltr; color:{accent}; }}
.lbl-price-row {{ display:flex; align-items:center; justify-content:center; gap:6px; margin-top:5px; }}
.lbl-price-qr {{ line-height:0; }}
</style>
"""
        html = self._shell(f"{len(cells)} ملصق", "ملصقات باركود", body)
        return html.replace("</head>", f"{style_extra}</head>")

    def _barcode_labels_roll_html(self, cells: list[str], *, accent: str, roll_width_mm: int) -> str:
        """Lean, header-free document for a continuous thermal roll -- see
        ``barcode_labels_html``'s ``layout="roll"`` docstring for why this
        deliberately bypasses ``_shell`` (no logo/company banner per label).
        Each label is its own CSS page sized to the roll's fixed width with
        an automatic height, so the printer driver cuts/feeds between labels
        the same way it already does between receipts.
        """
        # ``cells`` are already ``<div class="lbl">...</div>`` blocks built
        # by the caller above with the same class names this stylesheet
        # targets (.lbl/.lbl-name/.lbl-barcode/.lbl-price...) -- joined
        # as-is, no reformatting needed.
        body = "".join(cells)
        return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<title>ملصقات باركود (لفة حرارية)</title>
<style>
@page {{ size: {int(roll_width_mm)}mm auto; margin: 2mm; }}
* {{ box-sizing: border-box; }}
html, body {{ margin:0; padding:0; width:{int(roll_width_mm)}mm; }}
body {{
  direction: rtl;
  font-family: 'Cairo', 'Segoe UI', Tahoma, Arial, sans-serif;
  color:#0F172A;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
}}
.lbl {{
  width:100%; padding:2mm 1mm; text-align:center;
  page-break-after:always; break-after:page;
}}
.lbl:last-child {{ page-break-after:auto; break-after:auto; }}
.lbl-name {{
  font-size:12px; font-weight:700; margin-bottom:2mm; color:#0F172A;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}}
.lbl-barcode svg {{ width:100%; height:auto; display:block; }}
.lbl-price {{ font-size:14px; font-weight:800; direction:ltr; color:{accent}; margin-top:2mm; }}
.lbl-price-row {{ display:flex; align-items:center; justify-content:center; gap:6px; margin-top:2mm; }}
.lbl-price-qr {{ line-height:0; }}
</style>
</head>
<body>
{body}
</body>
</html>"""

    def item_card_html(
        self,
        *,
        payload: str,
        name: str,
        barcode: str | None,
        purchase_price: float | None = None,
        selling_price: float | None = None,
        unit: str | None = None,
        category: str | None = None,
        trusted: bool = True,
    ) -> str:
        """Printable/shareable card for one item: the same signed QR payload
        produced by ``core.item_card_signing`` alongside a human-readable
        summary, so scanning it on another device (or just reading it off
        the page) adds the item without retyping it. ``trusted`` only
        affects the small caption -- the payload itself is identical either
        way; verification happens at *scan* time on the receiving device.
        """
        qr = qr_svg(payload, size=170, level="M", quiet_zone=2, dark="#0F172A")
        facts: list[tuple[str, str]] = []
        if barcode:
            facts.append(("الباركود", self._e(barcode)))
        if selling_price is not None:
            facts.append(("سعر البيع", self._money(selling_price)))
        if purchase_price is not None:
            facts.append(("سعر الشراء", self._money(purchase_price)))
        if unit:
            facts.append(("الوحدة", self._e(unit)))
        if category:
            facts.append(("التصنيف", self._e(category)))
        fact_rows = "".join(f'<div class="ic-fact"><span>{k}</span><b>{v}</b></div>' for k, v in facts)
        caption = (
            "بطاقة موقّعة لهذا المحل — تُقبل تلقائيًا كموثوقة عند مسحها على جهاز آخر لنفس المنشأة"
            if trusted else
            "بطاقة مادة — عند مسحها على جهاز آخر ستظهر كـ«من مصدر خارجي» إلى أن تُراجَع يدويًا"
        )
        body = f"""
<div class="ic-wrap">
  <div class="ic-qr">{qr}</div>
  <div class="ic-info">
    <div class="ic-name">{self._e(name)}</div>
    {fact_rows}
  </div>
</div>
<div class="note"><b>كيف تُستخدم:</b> امسح هذا الرمز بتطبيق نانو على أي جهاز آخر لإضافة هذه المادة بكل بياناتها مباشرة، بدل إعادة كتابتها يدويًا. {caption}</div>
"""
        style_extra = """
<style>
.ic-wrap { display:flex; gap:20px; align-items:center; border:1px solid #E2E8F0; border-radius:14px; padding:18px; }
.ic-qr { flex:0 0 auto; line-height:0; }
.ic-info { flex:1; min-width:0; }
.ic-name { font-size:18px; font-weight:800; color:#0F172A; margin-bottom:8px; }
.ic-fact { display:flex; justify-content:space-between; gap:12px; font-size:12px; padding:4px 0; border-bottom:1px dashed #E2E8F0; }
.ic-fact span { color:#64748B; }
.ic-fact b { color:#0F172A; }
</style>
"""
        html = self._shell("بطاقة مادة", name, body)
        return html.replace("</head>", f"{style_extra}</head>")

    def party_card_html(self, party_type: str, data: dict) -> str:
        """Printable/shareable summary card for one customer or supplier.

        ``data`` is the dict returned by ``PartyRepository.activity_summary``
        -- the party's own fields (name/phone/address/balance) merged with
        invoice stats and a short list of recent invoices, so the caller
        (parties_view) passes through exactly what it already fetched for
        the on-screen detail sheet instead of this service re-querying.

        A small QR-encoded vCard is included so the contact can be scanned
        straight into another phone's own contacts app with any generic
        camera/QR reader -- no app or network needed, the same one-way
        convenience as the barcode-label price QR above.
        """
        kind = "عميل" if party_type == "customer" else "مورد"
        balance = float(data.get("balance") or 0)
        balance_label = "مستحق على الحساب" if balance >= 0 else "رصيد دائن للطرف"

        vcard_lines = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{data.get('name') or ''}"]
        if data.get("phone"):
            vcard_lines.append(f"TEL;TYPE=CELL:{data['phone']}")
        if data.get("address"):
            vcard_lines.append(f"ADR;TYPE=HOME:;;{data['address']};;;;")
        vcard_lines.append("END:VCARD")
        qr = qr_svg("\n".join(vcard_lines), size=110, level="M", quiet_zone=2, dark="#0F172A")

        recent_rows = []
        for idx, inv in enumerate(data.get("recent_invoices") or [], start=1):
            remaining = float(inv.get("remaining_amount") or 0)
            recent_rows.append(
                f"<tr><td>{idx}</td><td>{self._e(inv.get('invoice_date'))}</td>"
                f"<td>#{self._e(inv.get('id'))}</td>"
                f"<td class='money'>{self._money(inv.get('total'))}</td>"
                f"<td class='money'>{self._money(remaining)}</td></tr>"
            )

        body = f"""
<div class="pc-wrap">
  <div class="pc-info">
    <div class="meta-row">
      <span>النوع: <b>{kind}</b></span>
      <span class="sep">|</span>
      <span>الهاتف: <b>{self._e(data.get('phone') or '—')}</b></span>
    </div>
    <div class="meta-row">
      <span>العنوان: <b>{self._e(data.get('address') or '—')}</b></span>
    </div>
    <div class="grid">
      <div class="metric"><small>الرصيد الحالي</small><strong class="money">{self._money(abs(balance))}</strong><span class="fx">{self._e(balance_label)}</span></div>
      <div class="metric"><small>عدد الفواتير</small><strong>{int(data.get('invoice_count') or 0)}</strong></div>
      <div class="metric"><small>المتبقي على الفواتير المفتوحة</small><strong class="money">{self._money(data.get('outstanding_total'))}</strong></div>
    </div>
  </div>
  <div class="pc-qr">{qr}<span>بطاقة تواصل — امسح لإضافة جهة الاتصال</span></div>
</div>
<table>
<thead><tr><th>#</th><th>التاريخ</th><th>الفاتورة</th><th>الإجمالي</th><th>المتبقي</th></tr></thead>
<tbody>{''.join(recent_rows) if recent_rows else '<tr><td colspan="5">لا توجد فواتير بعد.</td></tr>'}</tbody>
</table>
"""
        style_extra = """
<style>
.pc-wrap { display:flex; gap:16px; align-items:flex-start; margin-bottom:14px; }
.pc-info { flex:1; min-width:0; }
.pc-qr { flex:0 0 auto; text-align:center; font-size:9px; color:#64748B; line-height:1.4; width:120px; }
.pc-qr svg { width:110px; height:110px; display:block; margin:0 auto 4px; }
</style>
"""
        html = self._shell(f"بطاقة {kind}", data.get("name") or "", body)
        return html.replace("</head>", f"{style_extra}</head>")

    @staticmethod
    def _period_label(date_from: str | None, date_to: str | None) -> str:
        if not date_from and not date_to:
            return "كل الفترة"
        return f"من {date_from or 'البداية'} إلى {date_to or 'النهاية'}"

    def pnl_report_html(self, report: dict, *, date_from: str | None, date_to: str | None) -> str:
        """Printable income-statement (P&L) report -- mirrors ReportsCenter._render_pnl."""
        expense_rows = "".join(
            f"<tr><td>{idx}</td><td>{self._e(row['category'])}</td>"
            f"<td class='money'>{self._money(row['amount'])}</td><td>{int(row['count'])}</td></tr>"
            for idx, row in enumerate(report.get("expense_breakdown") or [], start=1)
        )
        body = f"""
<div class="meta-row"><span>الفترة: <b>{self._e(self._period_label(date_from, date_to))}</b></span></div>
<div class="grid">
  <div class="metric"><small>المبيعات</small><strong class="money">{self._money(report['sales'])}</strong></div>
  <div class="metric"><small>تكلفة المبيعات</small><strong class="money">{self._money(report['cogs'])}</strong></div>
  <div class="metric"><small>مجمل الربح</small><strong class="money">{self._money(report['gross_profit'])}</strong><span class="fx">هامش {report['gross_margin_percent']:.1f}٪</span></div>
  <div class="metric"><small>المصروفات</small><strong class="money">{self._money(report['expenses'])}</strong></div>
  <div class="metric"><small>صافي الربح</small><strong class="money">{self._money(report['net_profit'])}</strong></div>
  <div class="metric"><small>المشتريات</small><strong class="money">{self._money(report['purchases'])}</strong></div>
</div>
<table>
<thead><tr><th>#</th><th>التصنيف</th><th>المبلغ</th><th>عدد الحركات</th></tr></thead>
<tbody>{expense_rows or '<tr><td colspan="4">لا توجد مصروفات في الفترة.</td></tr>'}</tbody>
</table>
"""
        return self._shell("قائمة الدخل", "قائمة الدخل والربحية", body)

    def profitability_report_html(
        self, *, invoices: list[dict], items: list[dict], top: list[dict],
        date_from: str | None, date_to: str | None,
    ) -> str:
        """Printable profitability report -- mirrors ReportsCenter._render_profitability."""
        top_rows = "".join(
            f"<tr><td>{idx}</td><td>{self._e(row['item_name'])}</td>"
            f"<td class='money'>{self._money(row['revenue'])}</td></tr>"
            for idx, row in enumerate(top, start=1)
        )
        invoice_rows = "".join(
            f"<tr><td>#{self._e(row['id'])}</td><td>{self._e(row['invoice_date'])}</td>"
            f"<td>{self._e(row['customer_name'])}</td><td class='money'>{self._money(row['total'])}</td>"
            f"<td class='money'>{self._money(row['gross_profit'])}</td><td>{row['margin_percent']:.1f}٪</td></tr>"
            for row in invoices
        )
        item_rows = "".join(
            f"<tr><td>{self._e(row['item_name'])}</td><td class='money'>{self._money(row['revenue'])}</td>"
            f"<td class='money'>{self._money(row['cogs'])}</td><td class='money'>{self._money(row['gross_profit'])}</td>"
            f"<td>{row['margin_percent']:.1f}٪</td></tr>"
            for row in items
        )
        body = f"""
<div class="meta-row"><span>الفترة: <b>{self._e(self._period_label(date_from, date_to))}</b></span></div>
<div class="doc-title" style="margin:6px 0">الأكثر مبيعًا</div>
<table>
<thead><tr><th>#</th><th>المادة</th><th>المبيعات</th></tr></thead>
<tbody>{top_rows or '<tr><td colspan="3">لا توجد مبيعات في الفترة.</td></tr>'}</tbody>
</table>
<div class="doc-title" style="margin:16px 0 6px">ربحية الفواتير</div>
<table>
<thead><tr><th>الفاتورة</th><th>التاريخ</th><th>العميل</th><th>المبيعات</th><th>الربح</th><th>الهامش</th></tr></thead>
<tbody>{invoice_rows or '<tr><td colspan="6">لا توجد فواتير بيع في الفترة.</td></tr>'}</tbody>
</table>
<div class="doc-title" style="margin:16px 0 6px">ربحية المواد والخدمات</div>
<table>
<thead><tr><th>المادة</th><th>المبيعات</th><th>التكلفة</th><th>الربح</th><th>الهامش</th></tr></thead>
<tbody>{item_rows or '<tr><td colspan="5">لا توجد مواد مباعة في الفترة.</td></tr>'}</tbody>
</table>
"""
        return self._shell("الربحية", "ربحية الفواتير والمواد", body)

    def inventory_report_html(
        self, *, rows: list[dict], valuation: dict, date_from: str | None, date_to: str | None,
    ) -> str:
        """Printable inventory movement/valuation report -- mirrors ReportsCenter._render_inventory."""
        item_rows = "".join(
            f"<tr><td>{self._e(row['name'])}</td><td class='money'>{self._qty(row['opening_quantity_period'])}</td>"
            f"<td class='money'>{self._qty(row['purchases_quantity'])}</td><td class='money'>{self._qty(row['sales_quantity'])}</td>"
            f"<td class='money'>{self._qty(row['closing_quantity'])}</td><td class='money'>{self._money(row['closing_value'])}</td></tr>"
            for row in rows
        )
        body = f"""
<div class="meta-row"><span>كما في: <b>{self._e(date_to or 'آخر حركة')}</b></span></div>
<div class="grid">
  <div class="metric"><small>قيمة المخزون</small><strong class="money">{self._money(valuation['total_value'])}</strong></div>
  <div class="metric"><small>عدد المواد المخزنية</small><strong>{valuation['item_count']}</strong></div>
</div>
<table>
<thead><tr><th>المادة</th><th>افتتاحي</th><th>وارد</th><th>صادر</th><th>ختامي</th><th>القيمة الختامية</th></tr></thead>
<tbody>{item_rows or '<tr><td colspan="6">لا توجد مواد مخزنية.</td></tr>'}</tbody>
</table>
"""
        return self._shell("المخزون", "حركة وتقييم المخزون", body)

    def balances_report_html(
        self, *, customers: dict, suppliers: dict,
        open_customers: list[dict], open_suppliers: list[dict], as_of: str | None,
    ) -> str:
        """Printable party-balances report -- mirrors ReportsCenter._render_balances."""

        def party_rows(report: dict) -> str:
            out = []
            for row in report["rows"]:
                balance = float(row["balance"] or 0)
                label = "مستحق" if balance >= 0 else "رصيد دائن"
                out.append(
                    f"<tr><td>{self._e(row['name'])}</td><td class='money'>{self._money(abs(balance))}</td>"
                    f"<td>{label}</td><td>{int(row['invoice_count'])}</td></tr>"
                )
            return "".join(out)

        def open_rows(rows: list[dict]) -> str:
            return "".join(
                f"<tr><td>#{self._e(row['id'])}</td><td>{self._e(row['party_name'])}</td>"
                f"<td>{self._e(row['invoice_date'])}</td><td class='money'>{self._money(row['total'])}</td>"
                f"<td class='money'>{self._money(row['remaining_amount'])}</td></tr>"
                for row in rows
            )

        body = f"""
<div class="meta-row"><span>كما في: <b>{self._e(as_of or 'آخر حركة')}</b></span></div>
<div class="grid">
  <div class="metric"><small>ذمم العملاء</small><strong class="money">{self._money(customers['positive_total'])}</strong></div>
  <div class="metric"><small>أرصدة دائنة للعملاء</small><strong class="money">{self._money(customers['credit_total'])}</strong></div>
  <div class="metric"><small>ذمم الموردين</small><strong class="money">{self._money(suppliers['positive_total'])}</strong></div>
  <div class="metric"><small>دفعات مقدمة للموردين</small><strong class="money">{self._money(suppliers['credit_total'])}</strong></div>
</div>
<div class="doc-title" style="margin:6px 0">العملاء</div>
<table>
<thead><tr><th>الاسم</th><th>الرصيد</th><th>النوع</th><th>عدد الفواتير</th></tr></thead>
<tbody>{party_rows(customers) or '<tr><td colspan="4">لا توجد بيانات.</td></tr>'}</tbody>
</table>
<div class="doc-title" style="margin:16px 0 6px">فواتير العملاء المفتوحة</div>
<table>
<thead><tr><th>الفاتورة</th><th>العميل</th><th>التاريخ</th><th>الإجمالي</th><th>المتبقي</th></tr></thead>
<tbody>{open_rows(open_customers) or '<tr><td colspan="5">لا توجد فواتير بيع مفتوحة.</td></tr>'}</tbody>
</table>
<div class="doc-title" style="margin:16px 0 6px">الموردون</div>
<table>
<thead><tr><th>الاسم</th><th>الرصيد</th><th>النوع</th><th>عدد الفواتير</th></tr></thead>
<tbody>{party_rows(suppliers) or '<tr><td colspan="4">لا توجد بيانات.</td></tr>'}</tbody>
</table>
<div class="doc-title" style="margin:16px 0 6px">فواتير الموردين المفتوحة</div>
<table>
<thead><tr><th>الفاتورة</th><th>المورد</th><th>التاريخ</th><th>الإجمالي</th><th>المتبقي</th></tr></thead>
<tbody>{open_rows(open_suppliers) or '<tr><td colspan="5">لا توجد فواتير شراء مفتوحة.</td></tr>'}</tbody>
</table>
"""
        return self._shell("الذمم", "ذمم العملاء والموردين", body)

    def cash_report_html(self, report: dict, *, date_from: str | None, date_to: str | None) -> str:
        """Printable cash-movement report -- mirrors ReportsCenter._render_cash."""
        rows = "".join(
            f"<tr><td>{self._e(row['entry_date'])}</td>"
            f"<td>{self._e(row.get('description') or row['source_type'])}</td>"
            f"<td class='money'>{self._money(row['debit'])}</td><td class='money'>{self._money(row['credit'])}</td>"
            f"<td class='money'>{self._money(row['balance'])}</td></tr>"
            for row in report["rows"]
        )
        body = f"""
<div class="meta-row"><span>الفترة: <b>{self._e(self._period_label(date_from, date_to))}</b></span></div>
<div class="grid">
  <div class="metric"><small>رصيد افتتاحي</small><strong class="money">{self._money(report['opening_balance'])}</strong></div>
  <div class="metric"><small>المقبوضات</small><strong class="money">{self._money(report['receipts'])}</strong></div>
  <div class="metric"><small>المدفوعات</small><strong class="money">{self._money(report['payments'])}</strong></div>
  <div class="metric"><small>الرصيد الختامي</small><strong class="money">{self._money(report['closing_balance'])}</strong></div>
</div>
<table>
<thead><tr><th>التاريخ</th><th>البيان</th><th>قبض</th><th>صرف</th><th>الرصيد</th></tr></thead>
<tbody>{rows or '<tr><td colspan="5">لا توجد حركات صندوق في الفترة.</td></tr>'}</tbody>
</table>
"""
        return self._shell("الصندوق", "حركة الصندوق", body)
