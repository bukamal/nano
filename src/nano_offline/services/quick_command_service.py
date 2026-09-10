"""Quick Command parser — typed Arabic commands (foundation for future voice).

Examples the owner can type (or later speak):
  • بيع سريع
  • جرد
  • نسخ احتياطي
  • كم باقي السكر
  • فتح العملاء
  • تفعيل الطوارئ
  • إلغاء الطوارئ

Returns a structured CommandResult the shell can execute (navigate / action).
Fully offline, no NLP model — keyword + simple patterns only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nano_offline.core.database import Database
    from nano_offline.repositories.item_repository import ItemRepository


@dataclass(slots=True, frozen=True)
class CommandResult:
    ok: bool
    action: str  # navigate | query | crisis_on | crisis_off | message | unknown
    target: str | None = None
    message: str | None = None
    data: dict | None = None


# (keywords that must ALL appear or any of the alternatives, action, target)
_NAV_PATTERNS: list[tuple[list[str], str, str]] = [
    (["نقطة", "بيع"], "navigate", "pos"),
    (["بيع", "سريع"], "navigate", "pos"),
    (["pos"], "navigate", "pos"),
    (["فاتورة", "بيع"], "navigate", "invoices"),
    (["فواتير"], "navigate", "invoices"),
    (["مشتريات"], "navigate", "invoices"),
    (["مواد"], "navigate", "items"),
    (["مخزون"], "navigate", "items"),
    (["عملاء"], "navigate", "customers"),
    (["موردين"], "navigate", "suppliers"),
    (["موردون"], "navigate", "suppliers"),
    (["تقارير"], "navigate", "reports"),
    (["تقرير"], "navigate", "reports"),
    (["لوحة"], "navigate", "dashboard"),
    (["رئيسية"], "navigate", "dashboard"),
    (["إدارة"], "navigate", "admin"),
    (["اعدادات"], "navigate", "admin"),
    (["إعدادات"], "navigate", "admin"),
    (["جرد"], "navigate", "stocktake"),
    (["مالية"], "navigate", "finance"),
    (["صندوق"], "navigate", "finance"),
    (["إشعارات"], "navigate", "notifications"),
    (["تنبيهات"], "navigate", "notifications"),
]


class QuickCommandService:
    def __init__(self, db: "Database", *, items: "ItemRepository | None" = None) -> None:
        self.db = db
        self.items = items

    def parse(self, text: str) -> CommandResult:
        raw = (text or "").strip()
        if not raw:
            return CommandResult(ok=False, action="unknown", message="اكتب أمراً مثل: بيع سريع، جرد، كم باقي السكر")

        normalized = raw.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه")
        lower = normalized.lower()

        # Crisis toggles
        if any(k in lower for k in ("تفعيل الطوارئ", "وضع الطوارئ", "ازمه", "أزمة", "ازمة")):
            if any(k in lower for k in ("الغاء", "إلغاء", "اطفئ", "ايقاف", "إيقاف", "وقف")):
                return CommandResult(ok=True, action="crisis_off", message="إلغاء وضع الطوارئ الاقتصادي")
            return CommandResult(ok=True, action="crisis_on", message="تفعيل وضع الطوارئ الاقتصادي")

        if any(k in lower for k in ("الغاء الطوارئ", "إلغاء الطوارئ", "اطفاء الطوارئ")):
            return CommandResult(ok=True, action="crisis_off", message="إلغاء وضع الطوارئ الاقتصادي")

        # Stock query: كم باقي X / رصيد X / كمية X
        stock_match = re.search(
            r"(?:كم\s*باقي|رصيد|كميه|كمية|كمية\s*المتبقية)\s+(.+)$",
            normalized,
            flags=re.IGNORECASE,
        )
        if stock_match:
            query = stock_match.group(1).strip(" ؟?،,")
            return self._stock_query(query)

        # Backup
        if any(k in lower for k in ("نسخه احتياط", "نسخة احتياط", "باك اب", "backup", "نسخ احتياط")):
            return CommandResult(ok=True, action="navigate", target="admin", message="فتح النسخ الاحتياطي")

        # Navigation
        for keys, action, target in _NAV_PATTERNS:
            if all(k in lower for k in keys) or (len(keys) == 1 and keys[0] in lower):
                return CommandResult(ok=True, action=action, target=target, message=f"فتح: {target}")

        # Single-token shortcuts
        shortcuts = {
            "بيع": ("navigate", "pos"),
            "جرد": ("navigate", "stocktake"),
            "عملاء": ("navigate", "customers"),
            "تقارير": ("navigate", "reports"),
            "مواد": ("navigate", "items"),
        }
        token = lower.strip()
        if token in shortcuts:
            a, t = shortcuts[token]
            return CommandResult(ok=True, action=a, target=t)

        return CommandResult(
            ok=False,
            action="unknown",
            message="لم أفهم الأمر. جرّب: بيع سريع، جرد، فتح العملاء، كم باقي السكر، تفعيل الطوارئ",
        )

    def _stock_query(self, name_query: str) -> CommandResult:
        name_query = name_query.strip()
        if not name_query:
            return CommandResult(ok=False, action="unknown", message="حدد اسم المادة")
        try:
            with self.db.connect() as conn:
                rows = conn.execute(
                    """SELECT id, name, quantity, selling_price
                       FROM items
                       WHERE item_type='مخزون' AND name LIKE ?
                       ORDER BY name LIMIT 5""",
                    (f"%{name_query}%",),
                ).fetchall()
        except Exception as exc:
            return CommandResult(ok=False, action="message", message=str(exc))

        if not rows:
            return CommandResult(
                ok=True,
                action="message",
                message=f"لا توجد مادة تطابق «{name_query}»",
            )

        if len(rows) == 1:
            d = dict(rows[0])
            qty = float(d["quantity"] or 0)
            return CommandResult(
                ok=True,
                action="query",
                target="items",
                message=f"«{d['name']}»: الكمية المتبقية {qty:g}",
                data={"item_id": int(d["id"]), "quantity": qty, "name": d["name"]},
            )

        lines = [f"• {dict(r)['name']}: {float(dict(r)['quantity'] or 0):g}" for r in rows]
        return CommandResult(
            ok=True,
            action="query",
            target="items",
            message="نتائج متعددة:\n" + "\n".join(lines),
            data={"matches": [dict(r) for r in rows]},
        )


__all__ = ["QuickCommandService", "CommandResult"]
