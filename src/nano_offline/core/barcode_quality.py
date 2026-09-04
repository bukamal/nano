from __future__ import annotations

"""Pure, offline helpers for "smarter" barcode handling: checking whether a
manually-typed or scanned code is a *valid* barcode of its type, and
whether it is suspiciously close to another code already on file (a likely
typo/scan glitch rather than a genuinely different product).

Deliberately pure functions with no DB access, so they're easy to call from
both the item editor (on typing) and the repository (before save) without
either one owning the logic.
"""


def _ean_upc_checksum_ok(digits: str) -> bool:
    """Standard mod-10 check digit shared by EAN-13, EAN-8, and UPC-A.

    The last digit is the check digit; weights alternate 1/3 (or 3/1
    depending on convention) from the right. This mirrors the same
    weighting already used by the app's own EAN-13 generator in
    items_view.py, just run in the "verify" direction instead of
    "generate".
    """
    body, check = digits[:-1], int(digits[-1])
    total = 0
    # Weight from the right: rightmost body digit gets weight 3, next 1, ...
    for i, ch in enumerate(reversed(body)):
        weight = 3 if i % 2 == 0 else 1
        total += int(ch) * weight
    expected = (10 - (total % 10)) % 10
    return expected == check


def checksum_warning(code: str) -> str | None:
    """Return a human (Arabic) warning if ``code`` looks like a EAN/UPC
    numeric barcode but fails its check digit -- or ``None`` if the code is
    valid, or isn't a recognized fixed-length numeric format at all (e.g.
    Code128 tokens, QR payloads, or anything alphanumeric), since those
    have no checksum to verify and are not flagged.
    """
    code = (code or "").strip()
    if not code.isdigit():
        return None
    if len(code) not in (8, 12, 13):  # EAN-8, UPC-A, EAN-13
        return None
    if _ean_upc_checksum_ok(code):
        return None
    return "رقم التحقق (checksum) غير صحيح لهذا الباركود — تأكد من كتابته أو مسحه مرة أخرى"


def _edit_distance_at_most_one(a: str, b: str) -> bool:
    """True if ``a`` and ``b`` differ by at most one single-character
    edit (insert, delete, or substitute) -- the classic "off by one
    keystroke or scan glitch" shape, without pulling in a diff library.
    """
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        # Same length: allow exactly one substitution.
        diffs = sum(1 for x, y in zip(a, b) if x != y)
        return diffs <= 1
    # Lengths differ by exactly 1: allow exactly one insertion/deletion.
    shorter, longer = (a, b) if la < lb else (b, a)
    i = j = 0
    skipped = False
    while i < len(shorter) and j < len(longer):
        if shorter[i] == longer[j]:
            i += 1
            j += 1
            continue
        if skipped:
            return False
        skipped = True
        j += 1
    return True


def generate_barcode_value(kind: str, *, prefix: str | None = None) -> str:
    """Produce a fresh random code for one of the app's three barcode
    kinds -- shared by every "generate a barcode" button in the item
    editor (the primary barcode and any secondary/per-unit barcode),
    instead of each button duplicating its own copy of this logic.

    EAN-13 uses the standard mod-10 check digit so generated codes are
    valid to print/scan later; Code128/QR have no fixed length or
    checksum, so this just emits a random alphanumeric token of a sane
    length for those.

    ``prefix`` (EAN-13 only): an optional digit string -- typically the
    admin-configured internal-use prefix from core.barcode_settings --
    baked into the leading digits of the generated code so every
    in-store-generated barcode is recognizable at a glance and can't
    collide with a manufacturer's own EAN-13 range. Non-digit characters
    are dropped and anything past 12 digits is ignored; the remaining
    digits are filled randomly.
    """
    import random
    import string

    kind = kind or "EAN13"
    if kind == "EAN13":
        clean_prefix = "".join(ch for ch in (prefix or "") if ch.isdigit())[:12]
        digits = list(clean_prefix) + [str(random.randint(0, 9)) for _ in range(12 - len(clean_prefix))]
        total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits))
        check = (10 - (total % 10)) % 10
        return "".join(digits) + str(check)
    if kind == "CODE128":
        return "".join(random.choices(string.digits + string.ascii_uppercase, k=12))
    return "".join(random.choices(string.digits + string.ascii_uppercase, k=10))  # QR


def detect_barcode_kind(code: str) -> str | None:
    """Guess which of the app's three barcode kinds (``EAN13``,
    ``CODE128``, ``QR``) a manually-typed or scanned ``code`` most likely
    is, purely from its shape -- so the "نوع الباركود" selector can default
    itself instead of the user picking it by hand every time a code is
    typed or scanned.

    This is a best-effort guess for pre-selecting the generator dropdown,
    not a validator: it never blocks saving and the user can always
    override it manually afterward. Returns ``None`` for an empty code
    (nothing to guess from yet).
    """
    code = (code or "").strip()
    if not code:
        return None
    if code.isdigit() and len(code) in (8, 12, 13):
        return "EAN13"
    # Anything reasonably short and alphanumeric reads as a Code128-style
    # SKU/serial token; longer or punctuation-heavy payloads (URLs, JSON,
    # free text) are far more likely to be a QR code's actual content.
    if len(code) <= 20 and code.replace("-", "").isalnum():
        return "CODE128"
    return "QR"


def find_similar(code: str, candidates: list[tuple[str, str]]) -> list[str]:
    """Given a candidate ``code`` and a list of ``(barcode, item_name)``
    pairs already on file, return the item names whose barcode is a
    likely typo/scan-glitch away from ``code`` (edit distance <= 1) --
    excluding an exact match, which is a duplicate, not a "similar" one.

    This is advisory only: callers should warn, not block, since a
    near-identical code can legitimately belong to a different product
    (e.g. two sizes of the same item from the manufacturer).
    """
    code = (code or "").strip()
    if not code:
        return []
    names: list[str] = []
    for other, name in candidates:
        other = (other or "").strip()
        if not other or other == code:
            continue
        if _edit_distance_at_most_one(code, other):
            names.append(name)
    return names


__all__ = ["checksum_warning", "detect_barcode_kind", "find_similar", "generate_barcode_value"]
