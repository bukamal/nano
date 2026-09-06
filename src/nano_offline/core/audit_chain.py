"""Tamper-evident audit chain (phase 10).

Every ``audit_log`` row carries two extra hashes computed by an AFTER INSERT
trigger (``trg_audit_chain`` in ``core/database.py``):

* ``prev_hash`` — the ``row_hash`` of the previous row (chain linkage; NULL
  for the first hashed row after migration).
* ``row_hash``   — SHA-256 over the row's canonical JSON payload **plus**
  ``prev_hash``, so editing a row invalidates its own hash, and deleting or
  reordering a row breaks the next row's linkage.

Because the hash is computed inside the trigger, every write path in the app
(services, repositories, the legacy actor-stamping trigger) is covered with
zero per-callsite changes. ``verify_audit_chain`` walks the table in id order,
re-derives each hash, and reports the first broken row. Rows written before
this migration have NULL hashes and are treated as a sealed root: they cannot
be retroactively hashed without rewriting history, so they are skipped and
the chain simply starts at the first hashed row.

Design notes:
- The trigger reads the row back from the table (not ``NEW.*``) so it hashes
  the *final* stored values — after ``trg_audit_attach_actor`` has stamped
  user_id/username — which is exactly what the verifier re-derives.
- SHA-256 is not authentication against someone who can edit both the table
  and the hash computation; it is tamper *evidence*: any modification that is
  not also a deliberate full re-hash of the entire chain is detected, and the
  chain makes silent partial edits (the historical use case: "fixing" one old
  record) instantly visible to the admin audit screen.
"""

from __future__ import annotations

import hashlib
import json

__all__ = ["compute_row_hash", "verify_audit_chain"]


def compute_row_hash(
    *,
    action,
    entity_type,
    entity_id,
    details,
    user_id,
    username,
    created_at,
    prev_hash,
) -> str:
    """Deterministic SHA-256 for one audit row (must match the trigger)."""
    payload = {
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "details": details,
        "user_id": user_id,
        "username": username,
        "created_at": created_at,
        "prev": prev_hash,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_audit_chain(db) -> dict:
    """Walk the audit log and re-derive the chain.

    Returns ``{"valid": bool, "rows": int, "hashed": int, "broken_at": int|None}``.
    ``broken_at`` is the id of the first row whose stored hash no longer
    matches its content or whose linkage is broken (None when valid).
    """
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT id, action, entity_type, entity_id, details, user_id,
                      username, created_at, prev_hash, row_hash
               FROM audit_log ORDER BY id"""
        ).fetchall()
    last_hash: str | None = None
    hashed = 0
    for r in rows:
        row_hash = r["row_hash"]
        if row_hash is None:
            continue  # pre-migration row: sealed root marker
        hashed += 1
        if last_hash is None:
            if r["prev_hash"] is not None:
                return {"valid": False, "rows": len(rows), "hashed": hashed, "broken_at": r["id"]}
        elif r["prev_hash"] != last_hash:
            return {"valid": False, "rows": len(rows), "hashed": hashed, "broken_at": r["id"]}
        computed = compute_row_hash(
            action=r["action"],
            entity_type=r["entity_type"],
            entity_id=r["entity_id"],
            details=r["details"],
            user_id=r["user_id"],
            username=r["username"],
            created_at=r["created_at"],
            prev_hash=r["prev_hash"],
        )
        if computed != row_hash:
            return {"valid": False, "rows": len(rows), "hashed": hashed, "broken_at": r["id"]}
        last_hash = row_hash
    return {"valid": True, "rows": len(rows), "hashed": hashed, "broken_at": None}
