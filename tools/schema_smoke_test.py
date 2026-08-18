from __future__ import annotations
import sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from qeid_offline.core.database import Database, SCHEMA_VERSION

with tempfile.TemporaryDirectory(prefix='qeid-schema-') as td:
    db=Database(Path(td)/'x.db'); db.initialize()
    with db.connect() as c:
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required={'customers','suppliers','categories','units','items','item_units','invoices','invoice_lines','payments','inventory_movements','ledger_entries','expenses','expense_categories','vouchers','payment_allocations','audit_log','license_state','settings'}
        assert required <= tables, required-tables

        item_columns={r[1] for r in c.execute("PRAGMA table_info(items)")}
        assert {'opening_quantity','opening_unit_cost'} <= item_columns
        invoice_columns={r[1] for r in c.execute("PRAGMA table_info(invoices)")}
        assert 'initial_paid_amount' in invoice_columns
        v=c.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
        assert int(v)==SCHEMA_VERSION
    assert db.integrity_check()=='ok'
print('schema_smoke_test passed')
