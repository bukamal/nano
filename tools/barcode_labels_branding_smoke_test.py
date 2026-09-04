from __future__ import annotations
import sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from nano_offline.core.database import Database
from nano_offline.core.barcode128 import code128b_bars, code128b_svg
from nano_offline.repositories.item_repository import ItemRepository
from nano_offline.repositories.settings_repository import SettingsRepository
from nano_offline.services.invoice_service import InvoiceService
from nano_offline.services.statement_service import StatementService
from nano_offline.services.document_service import DocumentService

with tempfile.TemporaryDirectory(prefix='qeid-barcode-labels-') as td:
    db = Database(Path(td) / 'db.sqlite3')
    db.initialize()

    # --- 1. Code128B renderer: deterministic, checksum-correct, valid SVG ---
    bars1 = code128b_bars('123456789012')
    bars2 = code128b_bars('123456789012')
    assert bars1 == bars2, "encoding must be deterministic"
    assert all(w >= 1 for w, _ in bars1), "every bar/space module must be >=1 unit wide"
    # Start(B) + N data symbols + checksum + stop -> at least 3 symbols worth of bars
    assert len(bars1) > 6 * 3

    svg_empty = code128b_svg('', width=200, height=60)
    assert '<svg' in svg_empty and 'width="200"' in svg_empty  # empty input must not crash

    svg = code128b_svg('ABC-123', width=240, height=70)
    assert svg.startswith('<svg') and svg.strip().endswith('</svg>')
    assert 'ABC-123' in svg  # human-readable text under the bars

    # Only ASCII 32-126 (subset B) is encodable; anything else is dropped, not raise.
    bars_arabic = code128b_bars('قلم123')
    bars_digits_only = code128b_bars('123')
    assert bars_arabic == bars_digits_only

    # --- 2. Repository + settings wiring ---
    items = ItemRepository(db)
    settings = SettingsRepository(db)
    pen_id = items.create(name='قلم حبر', purchase_price=1, selling_price=2.5, barcode='1111222233334')
    book_id = items.create(name='دفتر', purchase_price=1, selling_price=1.75, barcode='AAA-000-1')
    no_barcode_id = items.create(name='بدون باركود', purchase_price=1, selling_price=1)

    assert settings.get('company_name', 'نانو') == 'نانو'  # seeded default
    settings.set_many({
        'company_name': 'متجر النجمة',
        'invoice_color': '#7C3AED',
        'company_logo': 'data:image/png;base64,AAAA',
    })
    all_settings = settings.get_all()
    assert all_settings['company_name'] == 'متجر النجمة'
    assert all_settings['invoice_color'] == '#7C3AED'
    assert all_settings['company_logo'].startswith('data:image/png')

    # Clearing a setting (empty string) removes the row instead of storing "".
    settings.set('company_logo', '')
    assert 'company_logo' not in settings.get_all()

    # --- 3. Document service: branding flows into every printed shell ---
    invoices = InvoiceService(db)
    doc = DocumentService(db, invoices, StatementService(db))
    shell_html = doc._shell('عنوان تجريبي', '<p>محتوى</p>')
    assert '#7C3AED' in shell_html
    assert 'متجر النجمة' in shell_html

    # --- 4. Barcode label sheet: one <svg> per requested copy, price/name shown ---
    pen = items.get(pen_id)
    book = items.get(book_id)
    labels = (
        [{'name': pen['name'], 'barcode': pen['barcode'], 'price': pen['selling_price']}] * 2
        + [{'name': book['name'], 'barcode': book['barcode'], 'price': book['selling_price']}]
    )
    sheet_html = doc.barcode_labels_html(labels, columns=3)
    assert sheet_html.count('<svg') == 3
    assert sheet_html.count(pen['name']) == 2
    assert book['name'] in sheet_html
    assert '#7C3AED' in sheet_html  # accent color reused in the label sheet too

    # An item with no barcode contributes nothing when it slips into the list.
    no_bc = items.get(no_barcode_id)
    filtered_html = doc.barcode_labels_html(
        [{'name': no_bc['name'], 'barcode': no_bc.get('barcode'), 'price': no_bc['selling_price']}]
        + [{'name': pen['name'], 'barcode': pen['barcode'], 'price': pen['selling_price']}],
        columns=2,
    )
    assert no_bc['name'] not in filtered_html
    assert filtered_html.count('<svg') == 1

    # An all-barcode-less list is a clear error, not a blank/empty PDF.
    try:
        doc.barcode_labels_html([{'name': no_bc['name'], 'barcode': None, 'price': 1}])
        raise SystemExit('expected ValueError for a label list with no barcodes')
    except ValueError:
        pass

print('barcode_labels_branding_smoke_test passed')
