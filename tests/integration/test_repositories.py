"""Integration tests: real AppContext/DB, repositories (sync + .aio), audit, backup."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from nano_offline.app_context import AppContext
from nano_offline.core.audit_chain import verify_audit_chain
from nano_offline.services.invoice_service import InvoiceLineInput


@pytest.fixture()
def ctx(tmp_path):
    return AppContext.create(tmp_path / "nano.db")


@pytest.fixture()
def seeded(ctx):
    ctx.definitions.create_unit("قطعة", "ق")
    ctx.customers.create("عميل", "0900000000")
    ctx.suppliers.create("مورد")
    item_id = ctx.items.create(name="مادة A", purchase_price=10, selling_price=15, quantity=10)
    return {"item_id": item_id}


def test_item_repository_sync(ctx, seeded):
    rows = ctx.items.list()
    assert any(r["id"] == seeded["item_id"] for r in rows)


def test_item_repository_async_bridge(ctx, seeded):
    async def scenario():
        return await ctx.items.aio.list()

    rows = asyncio.run(scenario())
    assert any(r["id"] == seeded["item_id"] for r in rows)
    # bridge exposes only @blocking methods
    with pytest.raises(AttributeError, match="not tagged @blocking"):
        ctx.items.aio._check_barcode_free


def test_party_repository_async(ctx, seeded):
    async def scenario():
        return await ctx.customers.aio.list()

    rows = asyncio.run(scenario())
    assert rows and rows[0]["name"] == "عميل"


def test_invoice_flow_updates_state(ctx, seeded):
    supplier_id = ctx.suppliers.list()[0]["id"]
    customer_id = ctx.customers.list()[0]["id"]
    ctx.invoices.create_invoice(
        invoice_type="purchase", supplier_id=supplier_id, paid_amount=20,
        lines=[InvoiceLineInput(description="A", item_id=seeded["item_id"], quantity=5, unit_price=12)],
    )
    item = ctx.items.get(seeded["item_id"])
    assert round(item["quantity"], 6) == 15
    assert round(ctx.suppliers.get(supplier_id)["balance"], 6) == 40
    ctx.invoices.create_invoice(
        invoice_type="sale", customer_id=customer_id, paid_amount=10,
        lines=[InvoiceLineInput(description="A", item_id=seeded["item_id"], quantity=3, unit_price=20)],
    )
    assert round(ctx.items.get(seeded["item_id"])["quantity"], 6) == 12
    assert round(ctx.customers.get(customer_id)["balance"], 6) == 50
    assert ctx.db.integrity_check() == "ok"


def test_audit_chain_valid_after_writes(ctx, seeded):
    supplier_id = ctx.suppliers.list()[0]["id"]
    ctx.invoices.create_invoice(
        invoice_type="purchase", supplier_id=supplier_id, paid_amount=5,
        lines=[InvoiceLineInput(description="A", item_id=seeded["item_id"], quantity=1, unit_price=12)],
    )
    result = verify_audit_chain(ctx.db)
    assert result["valid"] is True
    assert result["hashed"] >= 1


def test_audit_chain_detects_tampering(ctx, seeded):
    supplier_id = ctx.suppliers.list()[0]["id"]
    ctx.invoices.create_invoice(
        invoice_type="purchase", supplier_id=supplier_id, paid_amount=5,
        lines=[InvoiceLineInput(description="A", item_id=seeded["item_id"], quantity=1, unit_price=12)],
    )
    assert verify_audit_chain(ctx.db)["valid"] is True
    # Silently edit a historical audit row without re-hashing the chain.
    with ctx.db.connect() as conn:
        conn.execute("UPDATE audit_log SET details='tampered' WHERE action='create' AND entity_type='invoice'")
    broken = verify_audit_chain(ctx.db)
    assert broken["valid"] is False
    assert broken["broken_at"] is not None


def test_backup_create_validate_restore(ctx, seeded, tmp_path):
    supplier_id = ctx.suppliers.list()[0]["id"]
    ctx.invoices.create_invoice(
        invoice_type="purchase", supplier_id=supplier_id, paid_amount=5,
        lines=[InvoiceLineInput(description="A", item_id=seeded["item_id"], quantity=1, unit_price=12)],
    )
    target = tmp_path / "b.nanobackup"
    out = ctx.backup.create_backup(target)
    assert Path(out).exists()
    validation = ctx.backup.validate_backup(out)
    assert validation.valid and int(validation.schema_version) >= 1
    # mutate after backup via a real accounting edit, then restore the file
    ctx.invoices.delete_invoice(
        ctx.invoices.list_invoices()[0]["id"]
    )
    assert ctx.invoices.list_invoices() == []
    ctx.backup.restore_backup(out)
    ctx.reload(ctx.db.path)
    assert len(ctx.invoices.list_invoices()) == 1


def test_backup_encrypted_requires_password(ctx, seeded, tmp_path):
    target = tmp_path / "enc.nanobackup"
    ctx.backup.create_backup(target, password="s3cret!")
    manifest = ctx.backup.validate_backup(target, password="s3cret!")
    assert manifest.valid and manifest.encrypted is True
    # wrong/absent password must fail on both validate and restore
    with pytest.raises(ValueError):
        ctx.backup.validate_backup(target)
    with pytest.raises(ValueError):
        ctx.backup.restore_backup(target)
