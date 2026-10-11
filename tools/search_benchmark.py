"""Micro-benchmark: FTS5 trigram search vs the LIKE fallback on Nano's items.
Measures, on a generated database of tens of thousands of items, how long a
substring search takes through the FTS5 index (``core/search_index.py``) versus
the plain unindexed ``name/barcode LIKE`` scan, plus the cost of building the
index once. Run it whenever the search path changes:
    python tools/search_benchmark.py [n_items]
It is intentionally *not* part of the quality gate: wall-clock numbers depend
on the machine, so a hard threshold would be flaky CI. Read it as a human
artifact proving the speed-up the index buys once item counts get large.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nano_offline.app_context import AppContext  # noqa: E402
from nano_offline.core import search_index  # noqa: E402

REPEATS = 25


def _seed(ctx: AppContext, n_items: int) -> None:
    """Bulk-seed items straight into SQLite (FTS triggers keep the index live),
    so creation cost reflects what a fully-indexed database pays per write."""
    rows = []
    for i in range(n_items):
        name = f"بند رقم {i:06d}"
        rows.append((name, f"BR{i:08d}" if i % 7 == 0 else None))
    with ctx.db.transaction() as conn:
        conn.executemany(
            "INSERT INTO items(name,purchase_price,selling_price,average_cost,"
            "opening_quantity,opening_unit_cost,quantity,barcode) "
            "VALUES(?,0,0,0,0,0,0,?)",
            rows,
        )


def _best_ms(fn) -> float:
    # Warm up once, then take the best run (least noise from scheduling).
    fn()
    best = float("inf")
    for _ in range(REPEATS):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best * 1000.0


def main(n_items: int) -> int:
    tmp = tempfile.TemporaryDirectory(prefix="nano-search-bench-")
    ctx = AppContext.create(Path(tmp.name) / "nano.db")

    print(f"seeding {n_items:,} items (FTS triggers active)...", flush=True)
    t0 = time.perf_counter()
    _seed(ctx, n_items)
    print(f"  seed took {time.perf_counter() - t0:.2f}s", flush=True)

    barcode_index = max(i for i in range(n_items) if i % 7 == 0)
    queries = {
        "unique tail  (last item)": f"بند رقم {n_items - 1:06d}",
        "common       (\"بند رقم 5\")": "بند رقم 5",
        "broad        (\"بند\")": "بند",
        "barcode      (unique)": f"BR{barcode_index:08d}",
    }

    # Phase 1: LIKE (drop the index; the repository falls back automatically).
    with ctx.db.connect() as conn:
        for idx in search_index.INDEXES:
            conn.execute(f"DROP TABLE IF EXISTS {idx.table}")
    like_ok = len(ctx.items.list(search=queries["unique tail  (last item)"])) > 0
    assert like_ok, "fixture sanity: LIKE search returned nothing"
    print("\n-- LIKE (unindexed) --", flush=True)
    like_ms = {}
    for label, q in queries.items():
        ms = _best_ms(lambda q=q: ctx.items.list(search=q))
        like_ms[label] = ms
        print(f"  {label}: {ms:.2f} ms", flush=True)

    # Phase 2: build the index, then measure FTS.
    with ctx.db.connect() as conn:
        t0 = time.perf_counter()
        tokenizer = search_index.ensure(conn)
        build_s = time.perf_counter() - t0
    assert tokenizer == "trigram"
    print(f"\n-- index build: {build_s:.2f}s --", flush=True)
    fts_ok = len(ctx.items.list(search=queries["unique tail  (last item)"])) == 1
    assert fts_ok, "fixture sanity: FTS search returned nothing"
    print("\n-- FTS5 (indexed) --", flush=True)
    for label, q in queries.items():
        ms = _best_ms(lambda q=q: ctx.items.list(search=q))
        like = like_ms[label]
        faster = "x%.1f faster" % (like / ms) if like > ms else "slower"
        print(f"  {label}: {ms:.2f} ms  ({faster})", flush=True)

    # Pagination (deep page) on both paths, to show TABLE vs INDEX under OFFSET.
    def _page():
        return ctx.items.list(search="بند رقم", limit=50, offset=n_items - 50)

    if len(_page()) == 50:
        with ctx.db.connect() as conn:
            for idx in search_index.INDEXES:
                conn.execute(f"DROP TABLE IF EXISTS {idx.table}")
        like = _best_ms(_page)
        with ctx.db.connect() as conn:
            search_index.ensure(conn)
        fts = _best_ms(_page)
        print(
            f"\n-- deep page (limit=50 offset={n_items - 50}, 'بند رقم') --\n"
            f"  LIKE: {like:.2f} ms  FTS: {fts:.2f} ms  "
            f"({'x%.1f faster' % (like / fts) if like > fts else 'slower'})",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20_000
    raise SystemExit(main(n))
