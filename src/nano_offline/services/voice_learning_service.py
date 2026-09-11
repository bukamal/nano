"""Local self-expanding voice memory (offline).

Learns from successful commands and item matches so the assistant
improves on *this* device without a cloud model:

  • phrase → action aliases (successful utterances)
  • spoken item nicknames → catalog item
  • unknown phrases log (for later review / soft matching)
  • usage counts to prefer frequent patterns
"""

from __future__ import annotations

import json
import re
from typing import Any


def _norm(text: str) -> str:
    t = (text or "").strip().casefold()
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي"), ("ؤ", "و"), ("ئ", "ي")):
        t = t.replace(a, b)
    t = re.sub(r"[^\w\s\u0600-\u06ff]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


class VoiceLearningService:
    def __init__(self, db) -> None:
        self.db = db
        self._ensure()

    def _ensure(self) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_phrase_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phrase_norm TEXT NOT NULL UNIQUE,
                    phrase_raw TEXT,
                    action TEXT NOT NULL,
                    target TEXT,
                    data_json TEXT,
                    hits INTEGER NOT NULL DEFAULT 1,
                    last_used_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_item_alias (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alias_norm TEXT NOT NULL UNIQUE,
                    alias_raw TEXT,
                    item_id INTEGER NOT NULL,
                    item_name TEXT,
                    hits INTEGER NOT NULL DEFAULT 1,
                    last_used_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_unknown_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phrase_norm TEXT NOT NULL,
                    phrase_raw TEXT,
                    section TEXT,
                    hits INTEGER NOT NULL DEFAULT 1,
                    last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_voice_unknown_norm ON voice_unknown_log(phrase_norm)"
            )

    # ---- phrases (commands) -----------------------------------------------

    def remember_phrase(
        self,
        phrase: str,
        *,
        action: str,
        target: str | None = None,
        data: dict | None = None,
    ) -> None:
        if action in ("unknown", "voice_stop", None, ""):
            return
        # Don't memorize pure help chatter as executable commands
        if action in ("message",) and not target:
            return
        norm = _norm(phrase)
        if len(norm) < 2:
            return
        payload = json.dumps(data or {}, ensure_ascii=False)
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT id, hits FROM voice_phrase_memory WHERE phrase_norm=?",
                (norm,),
            ).fetchone()
            if row:
                conn.execute(
                    """UPDATE voice_phrase_memory
                       SET hits=hits+1, last_used_at=CURRENT_TIMESTAMP,
                           action=?, target=?, data_json=?, phrase_raw=?
                       WHERE id=?""",
                    (action, target, payload, phrase.strip(), int(row["id"])),
                )
            else:
                conn.execute(
                    """INSERT INTO voice_phrase_memory(phrase_norm, phrase_raw, action, target, data_json)
                       VALUES(?,?,?,?,?)""",
                    (norm, phrase.strip(), action, target, payload),
                )

    def lookup_phrase(self, phrase: str) -> dict | None:
        norm = _norm(phrase)
        if not norm:
            return None
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT phrase_raw, action, target, data_json, hits
                   FROM voice_phrase_memory WHERE phrase_norm=?""",
                (norm,),
            ).fetchone()
            if not row:
                # soft: phrase contained in a learned phrase or vice-versa
                row = conn.execute(
                    """SELECT phrase_raw, action, target, data_json, hits
                       FROM voice_phrase_memory
                       WHERE phrase_norm LIKE ? OR ? LIKE '%' || phrase_norm || '%'
                       ORDER BY hits DESC, length(phrase_norm) DESC LIMIT 1""",
                    (f"%{norm}%", norm),
                ).fetchone()
            if not row:
                return None
            data = {}
            try:
                data = json.loads(row["data_json"] or "{}")
            except Exception:
                data = {}
            # bump hit
            try:
                conn.execute(
                    """UPDATE voice_phrase_memory SET hits=hits+1, last_used_at=CURRENT_TIMESTAMP
                       WHERE phrase_norm=? OR phrase_norm LIKE ?""",
                    (norm, f"%{norm}%"),
                )
            except Exception:
                pass
            return {
                "action": row["action"],
                "target": row["target"],
                "data": data,
                "hits": int(row["hits"] or 1),
                "phrase": row["phrase_raw"],
            }

    # ---- item aliases -----------------------------------------------------

    def remember_item_alias(self, spoken: str, *, item_id: int, item_name: str) -> None:
        norm = _norm(spoken)
        if len(norm) < 2 or not item_id:
            return
        # skip if identical to official name
        if norm == _norm(item_name):
            return
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM voice_item_alias WHERE alias_norm=?", (norm,)
            ).fetchone()
            if row:
                conn.execute(
                    """UPDATE voice_item_alias
                       SET hits=hits+1, last_used_at=CURRENT_TIMESTAMP,
                           item_id=?, item_name=?, alias_raw=?
                       WHERE id=?""",
                    (int(item_id), item_name, spoken.strip(), int(row["id"])),
                )
            else:
                conn.execute(
                    """INSERT INTO voice_item_alias(alias_norm, alias_raw, item_id, item_name)
                       VALUES(?,?,?,?)""",
                    (norm, spoken.strip(), int(item_id), item_name),
                )

    def resolve_item_alias(self, spoken: str) -> dict | None:
        norm = _norm(spoken)
        if not norm:
            return None
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT item_id, item_name, alias_raw, hits
                   FROM voice_item_alias WHERE alias_norm=?""",
                (norm,),
            ).fetchone()
            if not row:
                row = conn.execute(
                    """SELECT item_id, item_name, alias_raw, hits
                       FROM voice_item_alias
                       WHERE alias_norm LIKE ? OR ? LIKE '%' || alias_norm || '%'
                       ORDER BY hits DESC LIMIT 1""",
                    (f"%{norm}%", norm),
                ).fetchone()
            if not row:
                return None
            return {
                "item_id": int(row["item_id"]),
                "item_name": row["item_name"],
                "alias": row["alias_raw"],
                "hits": int(row["hits"] or 1),
            }

    # ---- unknowns ---------------------------------------------------------

    def remember_unknown(self, phrase: str, *, section: str | None = None) -> None:
        norm = _norm(phrase)
        if len(norm) < 2:
            return
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM voice_unknown_log WHERE phrase_norm=? AND IFNULL(section,'')=IFNULL(?, '')",
                (norm, section),
            ).fetchone()
            if row:
                conn.execute(
                    """UPDATE voice_unknown_log
                       SET hits=hits+1, last_seen_at=CURRENT_TIMESTAMP, phrase_raw=?
                       WHERE id=?""",
                    (phrase.strip(), int(row["id"])),
                )
            else:
                conn.execute(
                    """INSERT INTO voice_unknown_log(phrase_norm, phrase_raw, section)
                       VALUES(?,?,?)""",
                    (norm, phrase.strip(), section),
                )

    def top_unknowns(self, limit: int = 20) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT phrase_raw, section, hits, last_seen_at
                   FROM voice_unknown_log ORDER BY hits DESC, last_seen_at DESC LIMIT ?""",
                (int(limit),),
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict[str, int]:
        with self.db.connect() as conn:
            phrases = conn.execute("SELECT COUNT(*) c FROM voice_phrase_memory").fetchone()["c"]
            aliases = conn.execute("SELECT COUNT(*) c FROM voice_item_alias").fetchone()["c"]
            unknowns = conn.execute("SELECT COUNT(*) c FROM voice_unknown_log").fetchone()["c"]
        return {
            "phrases": int(phrases or 0),
            "item_aliases": int(aliases or 0),
            "unknowns": int(unknowns or 0),
        }

    def teach_phrase(self, phrase: str, *, action: str, target: str | None = None, data: dict | None = None) -> None:
        """Explicit teaching API (future admin UI)."""
        self.remember_phrase(phrase, action=action, target=target, data=data)


__all__ = ["VoiceLearningService", "_norm"]
