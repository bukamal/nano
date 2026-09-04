from __future__ import annotations

"""Offline Code128 (subset B) barcode renderer.

No network and no extra packages are available on-device, so this renders
straight to an inline SVG string from the standard Code128 pattern table
instead of depending on a barcode-image library.

Subset B covers ASCII 32-126 (space through ``~``), which is everything the
app's barcode fields can contain (scanned codes, EAN-13-style digit strings,
and the app's own generated Code128 tokens).
"""

_START_B = 104
_STOP = 106

# Standard Code128 pattern table: value -> six (or seven, for STOP) bar/space
# widths in units, alternating bar/space starting with a bar. This is the
# fixed symbology table defined by the Code128 specification (not vendor- or
# library-specific), values 0-105 plus the 106 STOP pattern.
_PATTERNS: dict[int, str] = {
    0: "212222", 1: "222122", 2: "222221", 3: "121223", 4: "121322",
    5: "131222", 6: "122213", 7: "122312", 8: "132212", 9: "221213",
    10: "221312", 11: "231212", 12: "112232", 13: "122132", 14: "122231",
    15: "113222", 16: "123122", 17: "123221", 18: "223211", 19: "221132",
    20: "221231", 21: "213212", 22: "223112", 23: "312131", 24: "311222",
    25: "321122", 26: "321221", 27: "312212", 28: "322112", 29: "322211",
    30: "212123", 31: "212321", 32: "232121", 33: "111323", 34: "131123",
    35: "131321", 36: "112313", 37: "132113", 38: "132311", 39: "211313",
    40: "231113", 41: "231311", 42: "112133", 43: "112331", 44: "132131",
    45: "113123", 46: "113321", 47: "133121", 48: "313121", 49: "211331",
    50: "231131", 51: "213113", 52: "213311", 53: "213131", 54: "311123",
    55: "311321", 56: "331121", 57: "312113", 58: "312311", 59: "332111",
    60: "314111", 61: "221411", 62: "431111", 63: "111224", 64: "111422",
    65: "121124", 66: "121421", 67: "141122", 68: "141221", 69: "112214",
    70: "112412", 71: "122114", 72: "122411", 73: "142112", 74: "142211",
    75: "241211", 76: "221114", 77: "413111", 78: "241112", 79: "134111",
    80: "111242", 81: "121142", 82: "121241", 83: "114212", 84: "124112",
    85: "124211", 86: "411212", 87: "421112", 88: "421211", 89: "212141",
    90: "214121", 91: "412121", 92: "111143", 93: "111341", 94: "131141",
    95: "114113", 96: "114311", 97: "411113", 98: "411311", 99: "113141",
    100: "114131", 101: "311141", 102: "411131", 103: "211412",
    104: "211214", 105: "211232", 106: "2331112",
}


def _encodable(data: str) -> str:
    return "".join(c for c in (data or "") if 32 <= ord(c) <= 126)


def code128b_bars(data: str) -> list[tuple[int, bool]]:
    """Return [(width_units, is_bar), ...] for ``data`` using Code128 subset B."""
    text = _encodable(data)
    if not text:
        text = "0"
    values = [_START_B] + [ord(c) - 32 for c in text]
    checksum = (_START_B + sum(v * i for i, v in enumerate(values[1:], start=1))) % 103
    values = values + [checksum, _STOP]
    bars: list[tuple[int, bool]] = []
    is_bar = True
    for value in values:
        for width_char in _PATTERNS[value]:
            bars.append((int(width_char), is_bar))
            is_bar = not is_bar
    return bars


def code128b_svg(data: str, *, width: int = 260, height: int = 70, show_text: bool = True, bar_color: str = "#0F172A") -> str:
    """Render ``data`` as a standalone Code128B SVG string sized to ``width``x``height``."""
    bars = code128b_bars(data)
    total_units = sum(w for w, _ in bars)
    unit = width / total_units if total_units else 1
    text_h = 14 if show_text else 0
    bar_h = height - text_h
    x = 0.0
    rects = []
    for w, is_bar in bars:
        px_w = w * unit
        if is_bar:
            rects.append(f'<rect x="{x:.2f}" y="0" width="{px_w:.2f}" height="{bar_h}" fill="{bar_color}"/>')
        x += px_w
    label = _encodable(data) or data or ""
    text_svg = (
        f'<text x="{width/2:.2f}" y="{height-2}" text-anchor="middle" '
        f'font-family="monospace" font-size="11" fill="{bar_color}">{_escape(label)}</text>'
        if show_text else ""
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>'
        f"{''.join(rects)}{text_svg}</svg>"
    )


def _escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


__all__ = ["code128b_svg", "code128b_bars"]
