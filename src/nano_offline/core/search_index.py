"""Optional FTS5 (trigram) search indexes with a transparent LIKE fallback.

Nano's list screens filter with ``name LIKE '%q%'`` / ``barcode LIKE '%q%'``:
an unindexable full scan that is fine for hundreds of rows and slow once there
are tens of thousands. This module maintains FTS5 *trigram* indexes over those
same columns so the **same substring semantics** can be answered by an index.

The design deliberately keeps correctness independent of FTS5 availability:

* FTS5 and the trigram tokenizer are probed at startup (``ensure``). If either
  is missing -- some SQLite builds ship without FTS5 -- no index is created
  and the existing LIKE queries keep working unchanged.
* The trigram tokenizer matches substrings of at least 3 characters; shorter
  ``MATCH`` queries silently return nothing. Callers therefore only route a
  query through the index when it is long enough (:func:`can_use_fts`) and fall
  back to LIKE otherwise, so 1-2 character searches keep substring behavior.
* Indexes are standalone FTS5 tables (``rowid`` = source row id) kept in sync by AFTER
  INSERT/UPDATE/DELETE triggers on the source table, so every write path
  (repositories, accounting rebuilder, imports, restores) is covered without
  those call sites knowing the index exists. ``ensure`` additionally rebuilds
  an index whose row count diverges from its source (e.g. after a filesystem
  restore that bypassed triggers).
* The LIKE fallback escapes ``%``/``_`` so search is literal everywhere,
  mirroring what ``MATCH`` does naturally -- one consistent contract.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# Trigram tokenizer. FTS5's default tokenizer matches whole tokens (the
# unicode61 path) which silently changes query semantics; trigram is the one
# tokenizer that reproduces substring matching, so it is the only one used.
TOKENIZER = "trigram"
MIN_QUERY_LEN = 3


@dataclass(frozen=True)
class FtsIndex:
    table: str
    source: str
    columns: tuple[str, ...]


INDEXES: tuple[FtsIndex, ...] = (
    FtsIndex("items_fts", "items", ("name", "barcode")),
    FtsIndex("customers_fts", "customers", ("name",)),
    FtsIndex("suppliers_fts", "suppliers", ("name",)),
)


def _escape_like(text: str) -> str:
    return text.translate(str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"}))


def like_pattern(query: str) -> str:
    """LIKE pattern matching ``query`` as a literal substring."""
    return f"%{_escape_like(query.strip())}%"


def match_expression(query: str) -> str:
    """FTS5 phrase string for ``query`` (literal, quotes neutralized)."""
    return '"' + query.strip().replace('"', '""') + '"'


def fts_table_exists(conn: sqlite3.Connection, fts_table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (fts_table,)
    ).fetchone() is not None


def is_fts_eligible(conn: sqlite3.Connection, fts_table: str, query: str) -> bool:
    """Route a search through FTS only when it preserves substring semantics."""
    return (
        query.strip() and len(query.strip()) >= MIN_QUERY_LEN and fts_table_exists(conn, fts_table)
    )


def _probe(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute(
            f"CREATE VIRTUAL TABLE temp.__nano_fts_probe USING fts5(x, tokenize='{TOKENIZER}')"
        )
        conn.execute("DROP TABLE temp.__nano_fts_probe")
        return True
    except sqlite3.OperationalError:
        return False


def _create(conn: sqlite3.Connection, idx: FtsIndex) -> None:
    columns = ", ".join(idx.columns)
    new_cols = ", ".join(f"new.{c}" for c in idx.columns)
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {idx.table} USING fts5("
        f"{columns}, tokenize='{TOKENIZER}')"
    )
    conn.execute(
        f"""CREATE TRIGGER IF NOT EXISTS {idx.table}_ai AFTER INSERT ON {idx.source} BEGIN
            INSERT INTO {idx.table}(rowid, {columns}) VALUES (new.id, {new_cols});
        END"""
    )
    conn.execute(
        f"""CREATE TRIGGER IF NOT EXISTS {idx.table}_ad AFTER DELETE ON {idx.source} BEGIN
            DELETE FROM {idx.table} WHERE rowid = old.id;
        END"""
    )
    conn.execute(
        f"""CREATE TRIGGER IF NOT EXISTS {idx.table}_au AFTER UPDATE ON {idx.source} BEGIN
            DELETE FROM {idx.table} WHERE rowid = old.id;
            INSERT INTO {idx.table}(rowid, {columns}) VALUES (new.id, {new_cols});
        END"""
    )


def _backfill(conn: sqlite3.Connection, idx: FtsIndex) -> None:
    """Repopulate a standalone index from the source table (triggers already
    keep it current; this is for first creation, re-enable, or a drift repair)."""
    columns = ", ".join(idx.columns)
    conn.execute(
        f"INSERT INTO {idx.table}(rowid, {columns}) "
        f"SELECT id, {columns} FROM {idx.source}"
    )


def _resync(conn: sqlite3.Connection, idx: FtsIndex) -> None:
    source_rows = int(conn.execute(f"SELECT COUNT(*) FROM {idx.source}").fetchone()[0])
    fts_rows = int(conn.execute(f"SELECT COUNT(*) FROM {idx.table}").fetchone()[0])
    if source_rows != fts_rows:
        # Drift repair: clear and re-read every source row (used after a
        # restore or an upgrade where the table pre-dated the source rows).
        conn.execute(f"DELETE FROM {idx.table}")
        _backfill(conn, idx)


def _drop_triggers(conn: sqlite3.Connection, idx: FtsIndex) -> None:
    # Only the triggers are dropped; the virtual table itself stays in place.
    # Dropping the table is avoided on purpose: SQLite reuses the freed btree
    # pages for a later recreate and can resurrect stale FTS segment rows (an
    # index that counts rows but matches nothing). Without triggers no write
    # ever touches the table, so an unusable index is harmless and searches
    # transparently fall back to LIKE at the repository.
    for suffix in ("_ai", "_ad", "_au"):
        conn.execute(f"DROP TRIGGER IF EXISTS {idx.table}{suffix}")


def _enable(conn: sqlite3.Connection, idx: FtsIndex) -> None:
    """Create the table+triggers if missing and make the index live."""
    table_missing = not fts_table_exists(conn, idx.table)
    trigger_missing = (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?",
            (f"{idx.table}_ai",),
        ).fetchone()
        is None
    )
    _create(conn, idx)
    if table_missing or trigger_missing:
        # Fresh index, or a suspended one being brought back: read the source
        # in full because nothing maintained it while it was missing.
        _backfill(conn, idx)
    else:
        _resync(conn, idx)


def ensure(conn: sqlite3.Connection) -> str | None:
    """Create/maintain the FTS indexes. Returns the tokenizer when usable, else None.

    Called once from ``Database.initialize`` inside its transaction. If FTS5 or
    the trigram tokenizer is unavailable -- or anything fails halfway -- the
    triggers are dropped so no write can ever fail on a virtual-table error,
    and the repositories transparently keep using LIKE searches.
    """
    if not _probe(conn):
        for idx in INDEXES:
            _drop_triggers(conn, idx)
        return None
    try:
        for idx in INDEXES:
            _enable(conn, idx)
    except sqlite3.OperationalError:
        for idx in INDEXES:
            _drop_triggers(conn, idx)
        return None
    return TOKENIZER


def query_rowids(conn: sqlite3.Connection, fts_table: str, query: str) -> list[int] | None:
    """Rowids of ``fts_table`` matching ``query``, or None when not indexable."""
    if not is_fts_eligible(conn, fts_table, query):
        return None
    try:
        rows = conn.execute(
            f"SELECT rowid FROM {fts_table} WHERE {fts_table} MATCH ?",
            (match_expression(query),),
        ).fetchall()
        return [int(r[0]) for r in rows]
    except sqlite3.OperationalError:
        return None


__all__ = [
    "TOKENIZER",
    "MIN_QUERY_LEN",
    "INDEXES",
    "like_pattern",
    "match_expression",
    "fts_table_exists",
    "is_fts_eligible",
    "ensure",
    "query_rowids",
]
