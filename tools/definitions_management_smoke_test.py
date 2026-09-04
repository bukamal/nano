from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nano_offline.app_context import AppContext

with tempfile.TemporaryDirectory(prefix="qeid-definitions-mgmt-") as td:
    ctx = AppContext.create(Path(td) / "nano.db")

    cat_id = ctx.definitions.create_category("مواد غذائية")
    unit_id = ctx.definitions.create_unit("كيلو", "كغ")
    assert ctx.definitions.list_categories()[0]["item_count"] == 0
    assert ctx.definitions.list_units()[0]["item_count"] == 0

    ctx.definitions.rename_category(cat_id, "أغذية")
    ctx.definitions.rename_unit(unit_id, "كيلوغرام", "كغم")
    cats = ctx.definitions.list_categories()
    units = ctx.definitions.list_units()
    assert cats[0]["name"] == "أغذية", cats
    assert units[0]["name"] == "كيلوغرام" and units[0]["abbreviation"] == "كغم", units

    # Unused category/unit: delete succeeds.
    ctx.definitions.delete_category(cat_id)
    ctx.definitions.delete_unit(unit_id)
    assert ctx.definitions.list_categories() == []
    assert ctx.definitions.list_units() == []

    # Category/unit referenced by an item (as base unit): delete must be blocked
    # with a friendly message, matching PartyRepository.delete's convention.
    cat_id2 = ctx.definitions.create_category("خدمات")
    unit_id2 = ctx.definitions.create_unit("قطعة", "ق")
    item_id = ctx.items.create(
        name="خدمة صيانة", purchase_price=5, selling_price=10, quantity=0,
        base_unit_id=unit_id2, category_id=cat_id2,
    )
    assert ctx.definitions.list_categories()[0]["item_count"] == 1
    assert ctx.definitions.list_units()[0]["item_count"] == 1

    try:
        ctx.definitions.delete_category(cat_id2)
        raise AssertionError("delete_category should have raised for an in-use category")
    except ValueError as exc:
        assert "مرتبط" in str(exc)

    try:
        ctx.definitions.delete_unit(unit_id2)
        raise AssertionError("delete_unit should have raised for an in-use base unit")
    except ValueError as exc:
        assert "مرتبط" in str(exc)

    # A unit referenced only as an *alternate* conversion unit (item_units),
    # not as the base unit, must be protected too.
    unit_id3 = ctx.definitions.create_unit("علبة", "ع")
    ctx.items.update(
        item_id, name="خدمة صيانة", purchase_price=5, selling_price=10,
        base_unit_id=unit_id2, item_units=[{"unit_id": unit_id3, "conversion_factor": 2}],
    )
    try:
        ctx.definitions.delete_unit(unit_id3)
        raise AssertionError("delete_unit should have raised for a unit used as an alternate conversion unit")
    except ValueError as exc:
        assert "مرتبط" in str(exc)

    # Empty-name validation still enforced on rename, same as create.
    try:
        ctx.definitions.rename_category(cat_id2, "   ")
        raise AssertionError("rename_category should reject a blank name")
    except ValueError:
        pass

print("definitions_management_smoke_test passed")
