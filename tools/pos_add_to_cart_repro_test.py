"""POS quick-sale add-to-cart repro test.

Simulates the exact call chain a tap on a product tile (or a barcode scan)
triggers in POSCenter._add_item(), against a real AppContext + temp DB,
with a headless fake page. Asserts the cart actually gains the item.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import flet as ft

from nano_offline.app_context import AppContext
from nano_offline.views.pos_view import POSCenter


class FakePage:
    """Headless stand-in for ft.Page: records updates, no-ops async tasks."""

    def __init__(self):
        self.rtl = True
        self.update_count = 0
        self.tasks = []
        self.width = 400
        self.height = 800
        # toast() appends to page.overlay -- provide a real list so the
        # full barcode path runs end-to-end in this harness.
        self.overlay = []

    def update(self, *a, **k):
        self.update_count += 1

    def run_task(self, handler, *args):
        self.tasks.append((handler, args))
        return None

    def open(self, *a, **k):
        pass

    def close(self, *a, **k):
        pass


def build_pos():
    db_path = Path(tempfile.mkdtemp()) / "pos_test.db"
    ctx = AppContext.create(db_path)

    # Seed: a unit + category + one item with stock and a selling price.
    units = ctx.definitions.list_units()
    if units:
        unit_id = int(units[0]["id"])
    else:
        unit_id = ctx.definitions.create_unit("قطعة", "قطعة")
    cats = ctx.definitions.list_categories()
    cat_id = cats[0]["id"] if cats else None
    item_id = ctx.items.create(
        name="مادة اختبار",
        category_id=cat_id,
        item_type="مخزون",
        purchase_price=1.0,
        selling_price=2.5,
        quantity=10,
        base_unit_id=unit_id,
    )
    units = ctx.items.units(item_id)
    assert units, "item must have at least a base unit"
    page = FakePage()
    content = ft.Container()
    pos = POSCenter(page, ctx, content)
    pos.show_center()  # runs _build()
    return pos, ctx, item_id


def test_grid_tap_adds_to_cart():
    pos, ctx, item_id = build_pos()
    assert pos.cart == {}, "cart must start empty"
    pos._add_item(item_id)  # exact call the tile's on_click makes
    assert item_id in pos.cart, f"tile tap must add item to cart; cart={pos.cart}"
    assert pos.cart_order == [item_id]
    assert float(pos.cart[item_id]["qty"]) == 1.0
    # By design a plain tile tap stores unit_price=None; display and
    # checkout fall back to the item's selling_price.
    assert pos.cart[item_id]["unit_price"] is None
    assert float(pos.cart[item_id]["item"]["selling_price"]) == 2.5
    # The bound closure used by the view must exist and be the real one.
    assert callable(getattr(pos, "_refresh_cart", None)), "_refresh_cart must be wired after _build()"
    pos._refresh_cart()
    print("test_grid_tap_adds_to_cart passed")


def test_repeat_tap_bumps_qty():
    pos, ctx, item_id = build_pos()
    pos._add_item(item_id)
    pos._add_item(item_id)
    assert float(pos.cart[item_id]["qty"]) == 2.0, "repeat tap must bump qty"
    assert pos.cart_order == [item_id], "no duplicate rows"
    print("test_repeat_tap_bumps_qty passed")


def test_barcode_adds_to_cart():
    pos, ctx, item_id = build_pos()
    # Primary barcode lookup path (items.barcode) -- set one first.
    import sqlite3
    with ctx.db.connect() as conn:
        conn.execute("UPDATE items SET barcode=? WHERE id=?", ("6290000000017", item_id))
        conn.commit()
    pos._add_by_barcode("6290000000017")
    assert item_id in pos.cart, "barcode scan must add item to cart"
    print("test_barcode_adds_to_cart passed")


if __name__ == "__main__":
    test_grid_tap_adds_to_cart()
    test_repeat_tap_bumps_qty()
    test_barcode_adds_to_cart()
    print("pos_add_to_cart_repro_test: all passed")
