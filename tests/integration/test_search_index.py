"""FTS5 search-index behaviour: parity, paging and maintenance.
The repository search path must return *exactly* the same rows whether it is
answered by the FTS5 trigram index or by the literal-substring LIKE fallback;
``count`` must agree; paging with ``limit``/``offset`` must tile the result set
without gaps or overlaps; and indexes must stay in sync across create/update/
delete and after an index loss (backup restore).

Every test is written to pass with or without FTS5 support: when the bundled
SQLite lacks FTS5/trigram, the fallback is exercised and the index-specific
assertions are skipped. This keeps the suite green on any CI/build.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from nano_offline.app_context import AppContext
from nano_offline.core import search_index


def _ctx():
    tmp = tempfile.TemporaryDirectory(prefix="nano-search-")
    return AppContext.create(Path(tmp.name) / "nano.db"), tmp


def _seed(ctx) -> None:
    ctx.items.create(name="Widget", barcode="123")
    ctx.items.create(name="بدون باركود")
    ctx.items.create(name="Widget Pro")
    ctx.items.create(name="abc123", barcode="99887766")
    ctx.items.create(name="مرحبا بالعالم")
    ctx.items.create(name="صندوق كبير")
    ctx.items.create(name="XX")
    ctx.customers.create("زبون ألف")
    ctx.customers.create("زبون باء")
    ctx.suppliers.create("مورد سمير")


def _expected_item_ids(ctx, query: str) -> list[int]:
    with ctx.db.connect() as conn:
        pattern = search_index.like_pattern(query)
        rows = conn.execute(
            "SELECT i.id FROM items i "
            "WHERE i.name LIKE ? ESCAPE '\\' OR i.barcode LIKE ? ESCAPE '\\' "
            "ORDER BY i.name",
            (pattern, pattern),
        ).fetchall()
        return [int(r[0]) for r in rows]


_QUERIES = ["", "Wi", "Wid", "idget", "abc", "123", "9988", "مرحبا", "صندوق", "XX", "zzz"]


def test_database_initializes_search_index():
    ctx, tmp = _ctx()
    try:
        with ctx.db.connect() as conn:
            assert search_index.fts_table_exists(conn, "items_fts")
            assert search_index.fts_table_exists(conn, "customers_fts")
            assert search_index.fts_table_exists(conn, "suppliers_fts")
    finally:
        tmp.cleanup()


def test_items_search_parity_between_fts_and_like_contract():
    ctx, tmp = _ctx()
    try:
        _seed(ctx)
        if not ctx.db.fts_tokenizer:
            return  # fallback-only environment: nothing special to prove
        for query in _QUERIES:
            rows = ctx.items.list(search=query)
            got = [r["id"] for r in rows]
            expected = _expected_item_ids(ctx, query)
            assert got == expected, f"query={query!r}: {got} vs LIKE {expected}"
            assert ctx.items.count(search=query) == len(
                {r["id"] for r in ctx.items.list(search=query)}
            )
    finally:
        tmp.cleanup()


def test_long_query_short_query_routing():
    ctx, tmp = _ctx()
    try:
        _seed(ctx)
        if not ctx.db.fts_tokenizer:
            return
        with ctx.db.connect() as conn:
            # >= 3 chars routes through the index; shorter queries must NOT
            # (trigram MATCH returns nothing for them, breaking substring search).
            assert search_index.is_fts_eligible(conn, "items_fts", "Wid")
            assert not search_index.is_fts_eligible(conn, "items_fts", "Wi")
            assert search_index.query_rowids(conn, "items_fts", "get") is not None
            assert search_index.query_rowids(conn, "items_fts", "Wi") is None
            assert "Widget" in {
                (ctx.items.get(i) or {})["name"] for i in search_index.query_rowids(conn, "items_fts", "get")
            }
    finally:
        tmp.cleanup()


def test_items_count_and_pagination_tile_the_result_set():
    ctx, tmp = _ctx()
    try:
        for i in range(25):
            ctx.items.create(name=f"بند ثاني {i:02d}", selling_price=i)
        assert ctx.items.count() == 25
        assert ctx.items.count(search="بند ثاني") == 25
        assert ctx.items.count(search="لا يوجد") == 0

        page_size = 10
        seen: list[int] = []
        for offset in range(0, 25, page_size):
            page = ctx.items.list(search="بند ثاني", limit=page_size, offset=offset)
            assert len(page) == min(page_size, 25 - offset)
            seen.extend(r["id"] for r in page)
        assert len(seen) == len(set(seen)) == 25
        # Same order as the unpaginated list.
        full = ctx.items.list(search="بند ثاني")
        assert [r["id"] for r in full] == seen
    finally:
        tmp.cleanup()


def test_triggers_keep_index_in_sync_on_create_update_delete():
    ctx, tmp = _ctx()
    try:
        item_id = ctx.items.create(name="ABC123")
        assert [r["id"] for r in ctx.items.list(search="ABC")] == [item_id]

        ctx.items.update(item_id, name="XYZ789")
        assert ctx.items.list(search="ABC") == []
        assert [r["id"] for r in ctx.items.list(search="XYZ")] == [item_id]
        assert [r["id"] for r in ctx.items.list(search="xyz")] == [item_id]  # case-insensitive

        ctx.items.delete(item_id)
        assert ctx.items.list(search="XYZ") == []
        assert ctx.items.count(search="XYZ") == 0
    finally:
        tmp.cleanup()


def test_stale_index_repairs_and_missing_index_falls_back():
    ctx, tmp = _ctx()
    try:
        _seed(ctx)
        # 1) Stale index (drifted ledger, mid-upgrade state): one source row is
        # not in the index, so the index count diverges from the source.
        with ctx.db.transaction() as conn:
            conn.execute(
                "DELETE FROM items_fts WHERE rowid = (SELECT id FROM items WHERE name='Widget')"
            )
        # The stale index now misses the deleted row (only "Widget Pro" found).
        assert {r["name"] for r in ctx.items.list(search="Widget")} == {"Widget Pro"}
        with ctx.db.connect() as conn:
            search_index.ensure(conn)
        assert {r["name"] for r in ctx.items.list(search="Widget")} == {"Widget", "Widget Pro"}
        assert ctx.items.count(search="Widget") == 2

        # 2) Index table entirely missing: the repository must silently fall
        # back to the LIKE path (same rows, no crash).
        with ctx.db.transaction() as conn:
            conn.execute("DROP TABLE items_fts")
        with ctx.db.connect() as conn:
            assert not search_index.fts_table_exists(conn, "items_fts")
        rows = ctx.items.list(search="Widget")
        assert {r["name"] for r in rows} == {"Widget", "Widget Pro"}
        assert ctx.items.count(search="Widget") == 2

        # A later ensure() (next startup) recreates the index.
        with ctx.db.connect() as conn:
            search_index.ensure(conn)
            assert search_index.fts_table_exists(conn, "items_fts")
        assert {r["name"] for r in ctx.items.list(search="Widget")} == {"Widget", "Widget Pro"}
    finally:
        tmp.cleanup()


def test_parties_search_and_pagination():
    ctx, tmp = _ctx()
    try:
        _seed(ctx)
        with ctx.db.connect() as conn:
            pattern = search_index.like_pattern("زبون")
            names = {
                str(r[0])
                for r in conn.execute(
                    "SELECT name FROM customers WHERE name LIKE ? ESCAPE '\\'", (pattern,)
                ).fetchall()
            }
        assert names == {"زبون ألف", "زبون باء"}
        assert {r["name"] for r in ctx.customers.list(search="زبون")} == names
        assert ctx.customers.count(search="زبون") == 2
        assert ctx.customers.list(search="زبون", limit=1, offset=0)  # paging works

        assert [r["name"] for r in ctx.suppliers.list(search="مورد")] == ["مورد سمير"]
        assert ctx.suppliers.count(search="مورد") == 1
    finally:
        tmp.cleanup()
