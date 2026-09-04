from __future__ import annotations
import sys, sqlite3, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from nano_offline.core.database import Database, SCHEMA_VERSION, SCHEMA_SQL
from nano_offline.repositories.item_repository import ItemRepository

with tempfile.TemporaryDirectory(prefix='qeid-barcode-') as td:
    # --- 1. upgrade path: a real schema-6 database (no barcode column, no
    # unique index) must gain both without breaking existing rows. ---
    old_db = Path(td) / 'old.db'
    legacy_sql = SCHEMA_SQL.replace("    barcode TEXT,\n", "")
    legacy_sql = legacy_sql[: legacy_sql.index("-- Partial unique index")] + legacy_sql[legacy_sql.index("CREATE TABLE IF NOT EXISTS item_units") :]
    conn = sqlite3.connect(old_db)
    conn.executescript(legacy_sql)
    conn.execute("INSERT INTO schema_meta(key,value) VALUES('schema_version','6')")
    conn.execute(
        "INSERT INTO items(name,item_type,purchase_price,selling_price,quantity,average_cost,opening_quantity,opening_unit_cost) "
        "VALUES('Legacy Item','مخزون',1,2,0,1,0,0)"
    )
    conn.commit(); conn.close()
    assert 'barcode' not in {r[1] for r in sqlite3.connect(old_db).execute("PRAGMA table_info(items)")}

    db = Database(old_db)
    db.initialize()
    assert SCHEMA_VERSION == 9
    with db.connect() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(items)")}
        assert 'barcode' in cols
        assert conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == str(SCHEMA_VERSION)
        assert conn.execute("SELECT 1 FROM items WHERE name='Legacy Item'").fetchone() is not None

    # --- 2. repository: create/update/find_by_barcode + uniqueness ---
    repo = ItemRepository(db)
    id1 = repo.create(name='Item A', purchase_price=1, selling_price=2, barcode='1111')
    id2 = repo.create(name='Item B', purchase_price=1, selling_price=2)          # no barcode
    id3 = repo.create(name='Item C', purchase_price=1, selling_price=2)          # no barcode either
    assert id2 != id3  # two barcode-less items must coexist (partial index)

    found = repo.find_by_barcode('1111')
    assert found and int(found['id']) == id1
    assert repo.find_by_barcode('does-not-exist') is None
    assert repo.find_by_barcode('') is None

    try:
        repo.create(name='Item D', purchase_price=1, selling_price=2, barcode='1111')
        raise SystemExit('expected duplicate-barcode create to raise ValueError')
    except ValueError:
        pass

    repo.update(id2, name='Item B', purchase_price=1, selling_price=2, barcode='2222')
    assert repo.find_by_barcode('2222') and int(repo.find_by_barcode('2222')['id']) == id2

    try:
        repo.update(id3, name='Item C', purchase_price=1, selling_price=2, barcode='2222')
        raise SystemExit('expected duplicate-barcode update to raise ValueError')
    except ValueError:
        pass

    # clearing a barcode frees it up for reuse elsewhere
    repo.update(id2, name='Item B', purchase_price=1, selling_price=2, barcode=None)
    id4 = repo.create(name='Item E', purchase_price=1, selling_price=2, barcode='2222')
    assert id4 != id2

    # --- 3. fresh (non-migrated) database ends up with the same shape ---
    fresh = Database(Path(td) / 'fresh.db')
    fresh.initialize()
    with fresh.connect() as conn:
        assert 'barcode' in {r[1] for r in conn.execute("PRAGMA table_info(items)")}
        idx = {r[1] for r in conn.execute("PRAGMA index_list(items)")}
        assert 'idx_items_barcode' in idx

print('barcode_scan_smoke_test passed')
