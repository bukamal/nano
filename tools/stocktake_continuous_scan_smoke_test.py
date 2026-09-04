from __future__ import annotations
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nano_offline.core.database import Database, SCHEMA_VERSION
from nano_offline.repositories.item_repository import ItemRepository
from nano_offline.repositories.stocktake_repository import StocktakeRepository
from nano_offline.services.auth_service import AuthService
from nano_offline.services.stocktake_service import StocktakeService

assert SCHEMA_VERSION == 12

with TemporaryDirectory(prefix="qeid-stocktake-") as td:
    db = Database(Path(td) / "nano.db")
    db.initialize()

    with db.connect() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(stocktake_sessions)")}
        assert {"id", "status", "started_at", "committed_at", "notes"} <= cols
        cols2 = {r[1] for r in conn.execute("PRAGMA table_info(stocktake_lines)")}
        assert {"session_id", "item_id", "counted_qty", "system_qty_snapshot", "scan_count"} <= cols2

    items = ItemRepository(db)
    stocktake_repo = StocktakeRepository(db)
    auth = AuthService(db)
    auth.create_initial_admin("admin", "مدير", "password123")
    auth.login("admin", "password123")
    service = StocktakeService(db, items, stocktake_repo, auth)

    item_a = items.create(name="Item A", purchase_price=10, selling_price=15, quantity=20, barcode="ITEM-A-0001")
    item_b = items.create(name="Item B", purchase_price=5, selling_price=8, quantity=5, barcode="ITEM-B-0002")
    service_item = items.create(name="Wash Service", item_type="خدمة", purchase_price=0, selling_price=20)

    # --- 1. repository-level: create/add_scan accumulation + snapshot freeze
    sid = stocktake_repo.create_session(notes="test run")
    sess = stocktake_repo.get_session(sid)
    assert sess["status"] == "open"

    stocktake_repo.add_scan(sid, item_a, qty=1, system_qty_snapshot=20)
    stocktake_repo.add_scan(sid, item_a, qty=1, system_qty_snapshot=999)  # snapshot must NOT move on repeat scan
    lines = stocktake_repo.list_lines(sid)
    line_a = next(l for l in lines if l["item_id"] == item_a)
    assert line_a["counted_qty"] == 2
    assert line_a["system_qty_snapshot"] == 20
    assert line_a["scan_count"] == 2

    stocktake_repo.set_counted_qty(sid, item_a, 18)  # manual correction -> undercount vs system(20)
    line_a = next(l for l in stocktake_repo.list_lines(sid) if l["item_id"] == item_a)
    assert line_a["counted_qty"] == 18

    stocktake_repo.discard_session(sid)
    assert stocktake_repo.get_session(sid)["status"] == "discarded"
    # discarding must not touch inventory
    assert items.get(item_a)["quantity"] == 20

    # --- 2. service-level scan(): barcode resolution + unit conversion + service guard
    sid2 = service.start_session()
    r1 = service.scan(sid2, "ITEM-A-0001")
    assert r1["status"] == "added" and r1["counted_qty"] == 1
    r2 = service.scan(sid2, "ITEM-A-0001")
    assert r2["status"] == "added" and r2["counted_qty"] == 2
    r3 = service.scan(sid2, "DOES-NOT-EXIST")  # unknown, no similar match expected
    assert r3["status"] in ("not_found", "similar")
    r4 = service.scan(sid2, "0000000")  # bad length/checksum-ish numeric -> may or may not trip checksum
    assert r4["status"] in ("not_found", "checksum", "similar")

    r5 = service.scan(sid2, "ITEM-B-0002")
    assert r5["status"] == "added"

    # scanning a service item must be rejected (no physical stock to count)
    items.update(service_item, name="Wash Service", item_type="خدمة", purchase_price=0, selling_price=20, barcode="SERVICE-0003")
    r6 = service.scan(sid2, "SERVICE-0003")
    assert r6["status"] == "service"

    # --- 3. diff_summary: only nonzero diffs, sorted by |value|
    # item_a counted=2 vs book=20 -> diff=-18 (big value); item_b counted=1 vs book=5 -> diff=-4
    diffs = service.diff_summary(sid2, only_diffs=True)
    assert len(diffs) == 2
    assert diffs[0]["item_id"] == item_a  # bigger |value_diff| first
    assert abs(diffs[0]["diff"] - (-18)) < 1e-9
    assert abs(diffs[1]["diff"] - (-4)) < 1e-9

    # --- 4. commit(): recompute against CURRENT book qty, write adjustment
    # movements, shift items.quantity AND items.opening_quantity, mark
    # session committed, write an audit_log row.
    before_a = items.get(item_a)
    before_opening_a = float(before_a["opening_quantity"])
    n = service.commit(sid2)
    assert n == 2
    after_a = items.get(item_a)
    assert abs(float(after_a["quantity"]) - 2) < 1e-9  # counted value, since diff was computed vs book=20
    assert abs(float(after_a["opening_quantity"]) - (before_opening_a - 18)) < 1e-9
    after_b = items.get(item_b)
    assert abs(float(after_b["quantity"]) - 1) < 1e-9

    with db.connect() as conn:
        mv = conn.execute(
            "SELECT * FROM inventory_movements WHERE item_id=? AND movement_type='adjustment' ORDER BY id DESC LIMIT 1",
            (item_a,),
        ).fetchone()
        assert mv is not None and abs(float(mv["quantity_delta"]) - (-18)) < 1e-9
        audit = conn.execute(
            "SELECT * FROM audit_log WHERE entity_type='stocktake_session' AND entity_id=? ORDER BY id DESC LIMIT 1", (sid2,)
        ).fetchone()
        assert audit is not None and audit["action"] == "commit"

    assert stocktake_repo.get_session(sid2)["status"] == "committed"

    # --- 5. committing an already-committed/discarded session must fail
    try:
        stocktake_repo.commit_session(sid2, [])
        raise SystemExit("expected re-commit to raise")
    except ValueError:
        pass

    # --- 6. permission check: a viewer-role user cannot start/commit a session
    auth.create_user(username="viewer1", full_name="مشاهد", password="password123", role="viewer")
    auth.logout()
    auth.login("viewer1", "password123")
    try:
        service.start_session()
        raise SystemExit("expected PermissionError for viewer role")
    except PermissionError:
        pass

    auth.logout()
    auth.login("admin", "password123")

    # --- 7. quick-add-during-scan: unresolved code -> item created with that
    # exact barcode -> the SAME code re-fed through scan() must now resolve
    # and land as the first count, in one continuous session (this is what
    # views/stocktake_view.py's offer_create()/save() flow drives).
    sid3 = service.start_session()
    new_code = "NEWITEM-0099"
    r1 = service.scan(sid3, new_code)
    assert r1["status"] == "not_found" and r1["code"] == new_code

    new_item_id = items.create(name="مادة جديدة أثناء الجرد", barcode=new_code, purchase_price=3, selling_price=6)

    r2 = service.scan(sid3, new_code)
    assert r2["status"] == "added"
    assert int(r2["item"]["id"]) == new_item_id
    assert r2["counted_qty"] == 1

    lines3 = service.lines(sid3)
    line_new = next(l for l in lines3 if l["item_id"] == new_item_id)
    assert line_new["system_qty_snapshot"] == 0  # brand-new item has no book stock yet
    assert line_new["counted_qty"] == 1

    diffs3 = service.diff_summary(sid3, only_diffs=True)
    diff_new = next(d for d in diffs3 if d["item_id"] == new_item_id)
    assert diff_new["diff"] == 1
    service.discard_session(sid3)  # cleanup only -- don't touch inventory in this test

    # --- 8. resume-open-session: an unfinished session must be discoverable
    # and distinguishable from "no open session", and discarding/committing
    # it must make it stop showing up as resumable (this is what
    # views/stocktake_view.py's show_center() checks before ever starting a
    # fresh session, so an app close mid-walk doesn't strand the counts).
    assert service.find_resumable_session() is None

    sid4 = service.start_session(notes="جلسة معلّقة")
    service.scan(sid4, "ITEM-A-0001")
    resumable = service.find_resumable_session()
    assert resumable is not None
    assert int(resumable["id"]) == sid4
    assert resumable["line_count"] == 1

    # a second, unrelated open session -- find_resumable_session must still
    # surface exactly one (the newest), never crash on multiple opens
    sid5 = service.start_session()
    resumable2 = service.find_resumable_session()
    assert int(resumable2["id"]) == sid5

    service.discard_session(sid5)
    service.discard_session(sid4)
    assert service.find_resumable_session() is None

print("stocktake_continuous_scan_smoke_test passed")
