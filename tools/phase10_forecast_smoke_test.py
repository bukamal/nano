from __future__ import annotations

import tempfile
from pathlib import Path

from nano_offline.app_context import AppContext
from nano_offline.services.invoice_service import InvoiceLineInput

with tempfile.TemporaryDirectory(prefix="nano_phase10_forecast_") as td:
    root = Path(td)
    ctx = AppContext.create(root / "main" / "nano.db")
    ctx.auth.create_initial_admin("admin", "المدير", "StrongPass1")
    ctx.auth.login("admin", "StrongPass1")

    item_id = ctx.items.create(
        name="مادة للتنبؤ", item_type="مخزون",
        purchase_price=5.0, selling_price=12.0, quantity=200,
    )
    customer_id = ctx.customers.create("عميل التنبؤ")
    supplier_id = ctx.suppliers.create("مورد التنبؤ")

    # 8 months of history: a clear seasonal peak in month 5 (sales) and
    # month 6 (purchases) so the seasonal index is visibly distinguishable.
    for m in range(1, 9):
        day = 10 + (m * 7) % 9
        d = f"2026-{m:02d}-{day:02d}"
        extra = 300.0 if m == 5 else 0.0
        ctx.invoices.create_invoice(
            invoice_type="sale", customer_id=customer_id, invoice_date=d,
            lines=[
                InvoiceLineInput(description=f"مبيعات {m}", quantity=1, unit_price=100.0 + extra / 2, item_id=item_id),
                InvoiceLineInput(description=f"مبيعات {m} ب", quantity=1, unit_price=80.0 + extra / 2, item_id=item_id),
            ],
        )
        purchase_extra = 100.0 if m == 6 else 0.0
        ctx.invoices.create_invoice(
            invoice_type="purchase", supplier_id=supplier_id, invoice_date=d,
            lines=[
                InvoiceLineInput(description=f"مشتريات {m}", quantity=1, unit_price=50.0 + purchase_extra / 2, item_id=item_id),
                InvoiceLineInput(description=f"مشتريات {m} ب", quantity=1, unit_price=40.0 + purchase_extra / 2, item_id=item_id),
            ],
        )

    # --- 1. sales forecast: order, positivity, band, determinism ---
    sales = ctx.forecast.seasonal_forecast(invoice_type="sale")
    assert sales["insufficient"] is False, sales
    assert [f["month"] for f in sales["forecasts"]] == ["2026-09", "2026-10", "2026-11"], sales["forecasts"]
    assert sales["confidence"] in ("high", "medium", "low"), sales["confidence"]
    assert sales["confidence_label"] in ("عالية", "متوسطة", "منخفضة"), sales["confidence_label"]
    assert sales["history"][0]["month"] == "2026-01" and sales["history"][-1]["month"] == "2026-08", sales["history"]
    assert sales["seasonal"].get(5) is not None, sales["seasonal"]
    assert sales["seasonal"].get(11) == 1.0  # no-November history -> neutral index
    for f in sales["forecasts"]:
        assert f["forecast"] > 0 and f["low"] <= f["forecast"] <= f["high"], f
    same = ctx.forecast.seasonal_forecast(invoice_type="sale")
    assert same["forecasts"] == sales["forecasts"], "forecast must be deterministic"

    # --- 2. purchases forecast ---
    purchases = ctx.forecast.seasonal_forecast(invoice_type="purchase")
    assert purchases["forecasts"][0]["month"] == "2026-09", purchases["forecasts"]
    assert purchases["history_months"] == 8
    assert purchases["monthly_average"] > 0

    # --- 3. horizon clamp ---
    short = ctx.forecast.seasonal_forecast(invoice_type="sale", horizon=1)
    assert len(short["forecasts"]) == 1
    wide = ctx.forecast.seasonal_forecast(invoice_type="sale", horizon=20)
    assert len(wide["forecasts"]) == 12, len(wide["forecasts"])

    # --- 4. date filter narrows the history window ---
    filtered = ctx.forecast.seasonal_forecast(invoice_type="sale", date_from="2026-03-01", date_to="2026-06-30")
    assert [h["month"] for h in filtered["history"]] == ["2026-03", "2026-04", "2026-05", "2026-06"], filtered["history"]
    assert filtered["forecasts"][0]["month"] == "2026-07", filtered["forecasts"]
    assert filtered["seasonal"].get(5) is not None  # peak month survives the filter

    # --- 5. empty database -> honest insufficient result, no exception ---
    empty = AppContext.create(root / "empty" / "nano.db")
    result = empty.forecast.seasonal_forecast(invoice_type="sale")
    assert result["insufficient"] is True and result["forecasts"] == [], result

    # --- 6. sparse (single month) -> insufficient ---
    sparse = AppContext.create(root / "sparse" / "nano.db")
    sparse_item = sparse.items.create(name="مادة", item_type="مخزون", purchase_price=1.0, selling_price=2.0, quantity=5)
    sparse_customer = sparse.customers.create("عميل")
    sparse.invoices.create_invoice(
        invoice_type="sale", customer_id=sparse_customer, invoice_date="2026-01-05",
        lines=[InvoiceLineInput(description="بند", quantity=1, unit_price=10.0, item_id=sparse_item)],
    )
    sparse_result = sparse.forecast.seasonal_forecast(invoice_type="sale")
    assert sparse_result["insufficient"] is True, sparse_result

    # --- 7. invalid invoice type rejected ---
    try:
        ctx.forecast.seasonal_forecast(invoice_type="unknown")
        raise AssertionError("invalid invoice_type must raise")
    except ValueError:
        pass

print("phase10_forecast_smoke_test passed")
