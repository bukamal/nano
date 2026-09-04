from __future__ import annotations

"""Offline QR Code (Model 2) encoder -- no network, no extra packages.

Mirrors the approach in ``core.barcode128``: renders straight to SVG from a
from-scratch implementation of the QR symbology, since the device this app
runs on has no internet access and no third-party barcode/QR libraries
installed. Byte-mode only (sufficient for the app's own structured payloads:
JSON tokens, invoice-signature strings, item/customer links).

Supports versions 1-10 (up to 274 bytes of raw byte-mode capacity at the
lowest error-correction level), which comfortably covers every payload this
app generates. If a caller needs more room, shorten the payload -- e.g. drop
optional fields from the signed-invoice JSON -- rather than raising the
version cap blindly, since the block/alignment tables below stop at 10.

References the fixed ISO/IEC 18004 tables (Reed-Solomon block layout,
alignment-pattern centers, BCH generator polynomials for format/version
info). These are the symbology's own constants, not vendor- or
library-specific, exactly like the Code128 pattern table in barcode128.py.
"""

# ---------------------------------------------------------------------------
# GF(256) arithmetic (primitive polynomial 0x11D, generator element 2)
# ---------------------------------------------------------------------------

_EXP = [0] * 512
_LOG = [0] * 256


def _init_gf() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_gf()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator_poly(ecc_len: int) -> list[int]:
    poly = [1]
    for i in range(ecc_len):
        poly.append(0)
        for j in range(len(poly) - 1, 0, -1):
            poly[j] ^= _gf_mul(poly[j - 1], _EXP[i])
    return poly


def _rs_encode(data: list[int], ecc_len: int) -> list[int]:
    gen = _rs_generator_poly(ecc_len)
    remainder = [0] * ecc_len
    for byte in data:
        factor = byte ^ remainder[0]
        remainder = remainder[1:] + [0]
        if factor != 0:
            for i in range(ecc_len):
                remainder[i] ^= _gf_mul(gen[i + 1], factor)
    return remainder


# ---------------------------------------------------------------------------
# Version capacity tables (versions 1-10 only -- see module docstring)
# Each entry: ecc_codewords_per_block, [(num_blocks, data_codewords), ...]
# ---------------------------------------------------------------------------

_BLOCKS: dict[int, dict[str, tuple[int, list[tuple[int, int]]]]] = {
    1: {"L": (7, [(1, 19)]), "M": (10, [(1, 16)]), "Q": (13, [(1, 13)]), "H": (17, [(1, 9)])},
    2: {"L": (10, [(1, 34)]), "M": (16, [(1, 28)]), "Q": (22, [(1, 22)]), "H": (28, [(1, 16)])},
    3: {"L": (15, [(1, 55)]), "M": (26, [(1, 44)]), "Q": (18, [(2, 17)]), "H": (22, [(2, 13)])},
    4: {"L": (20, [(1, 80)]), "M": (18, [(2, 32)]), "Q": (26, [(2, 24)]), "H": (16, [(4, 9)])},
    5: {"L": (26, [(1, 108)]), "M": (24, [(2, 43)]), "Q": (18, [(2, 15), (2, 16)]), "H": (22, [(2, 11), (2, 12)])},
    6: {"L": (18, [(2, 68)]), "M": (16, [(4, 27)]), "Q": (24, [(4, 19)]), "H": (28, [(4, 15)])},
    7: {"L": (20, [(2, 78)]), "M": (18, [(4, 31)]), "Q": (18, [(2, 14), (4, 15)]), "H": (26, [(4, 13), (1, 14)])},
    8: {"L": (24, [(2, 97)]), "M": (22, [(2, 38), (2, 39)]), "Q": (22, [(4, 18), (2, 19)]), "H": (24, [(4, 14), (2, 15)])},
    9: {"L": (30, [(2, 116)]), "M": (22, [(3, 36), (2, 37)]), "Q": (20, [(4, 16), (4, 17)]), "H": (24, [(4, 12), (4, 13)])},
    10: {"L": (18, [(2, 68), (2, 69)]), "M": (26, [(4, 43), (1, 44)]), "Q": (24, [(6, 19), (2, 20)]), "H": (28, [(6, 15), (2, 16)])},
}

_ALIGNMENT: dict[int, list[int]] = {
    2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
}

_REMAINDER_BITS: dict[int, int] = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0}

_LEVEL_BITS = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}
_FORMAT_GEN = 0x537
_FORMAT_MASK = 0x5412
_VERSION_GEN = 0x1F25


def _size_for(version: int) -> int:
    return 17 + 4 * version


def _data_capacity_bytes(version: int, level: str) -> int:
    _ecc, groups = _BLOCKS[version][level]
    return sum(n * dl for n, dl in groups)


def _pick_version(byte_len: int, level: str) -> int:
    for v in range(1, 11):
        cap = _data_capacity_bytes(v, level)
        header = 4 + (8 if v <= 9 else 16)  # mode + count indicator bits
        if cap * 8 >= header + byte_len * 8:
            return v
    raise ValueError(
        f"qr_gen: payload too large ({byte_len} bytes) for the supported version range "
        "(1-10). Shorten the encoded data."
    )


# ---------------------------------------------------------------------------
# Bit buffer -> codewords
# ---------------------------------------------------------------------------


def _build_codewords(data: bytes, version: int, level: str) -> list[int]:
    bits: list[int] = []

    def push(value: int, n: int) -> None:
        for i in range(n - 1, -1, -1):
            bits.append((value >> i) & 1)

    push(0b0100, 4)  # byte-mode indicator
    count_bits = 8 if version <= 9 else 16
    push(len(data), count_bits)
    for b in data:
        push(b, 8)

    cap_bits = _data_capacity_bytes(version, level) * 8
    terminator = min(4, cap_bits - len(bits))
    if terminator > 0:
        push(0, terminator)
    while len(bits) % 8 != 0:
        bits.append(0)

    codewords: list[int] = []
    for i in range(0, len(bits), 8):
        byte = 0
        for b in bits[i : i + 8]:
            byte = (byte << 1) | b
        codewords.append(byte)

    pad_bytes = (0xEC, 0x11)
    i = 0
    while len(codewords) < cap_bits // 8:
        codewords.append(pad_bytes[i % 2])
        i += 1

    ecc_len, groups = _BLOCKS[version][level]
    blocks_data: list[list[int]] = []
    blocks_ecc: list[list[int]] = []
    pos = 0
    for num_blocks, data_len in groups:
        for _ in range(num_blocks):
            block = codewords[pos : pos + data_len]
            pos += data_len
            blocks_data.append(block)
            blocks_ecc.append(_rs_encode(block, ecc_len))

    result: list[int] = []
    max_data_len = max(len(b) for b in blocks_data)
    for i in range(max_data_len):
        for block in blocks_data:
            if i < len(block):
                result.append(block[i])
    for i in range(ecc_len):
        for block in blocks_ecc:
            result.append(block[i])

    return result


# ---------------------------------------------------------------------------
# Matrix construction
# ---------------------------------------------------------------------------


def _poly_rem(dividend: int, divisor: int) -> int:
    """GF(2) polynomial remainder of ``dividend`` mod ``divisor`` (bit-packed)."""
    d_deg = divisor.bit_length() - 1
    while dividend.bit_length() - 1 >= d_deg and dividend != 0:
        shift = dividend.bit_length() - 1 - d_deg
        dividend ^= divisor << shift
    return dividend


def _format_bits(level: str, mask: int) -> int:
    data = (_LEVEL_BITS[level] << 3) | mask
    rem = _poly_rem(data << 10, _FORMAT_GEN)
    combined = (data << 10) | rem
    return combined ^ _FORMAT_MASK


def _version_bits(version: int) -> int:
    rem = _poly_rem(version << 12, _VERSION_GEN)
    return (version << 12) | rem


def _mask_fn(pattern: int):
    return [
        lambda r, c: (r + c) % 2 == 0,
        lambda r, c: r % 2 == 0,
        lambda r, c: c % 3 == 0,
        lambda r, c: (r + c) % 3 == 0,
        lambda r, c: (r // 2 + c // 3) % 2 == 0,
        lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
        lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
        lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
    ][pattern]


def _alignment_centers(version: int) -> list[tuple[int, int]]:
    positions = _ALIGNMENT.get(version)
    if not positions:
        return []
    first, last = positions[0], positions[-1]
    out = []
    for r in positions:
        for c in positions:
            if (r, c) in ((first, first), (first, last), (last, first)):
                continue
            out.append((r, c))
    return out


def _build_matrix(version: int, level: str, codewords: list[int], mask: int):
    size = _size_for(version)
    module = [[None] * size for _ in range(size)]  # None=free, True=dark, False=light
    is_function = [[False] * size for _ in range(size)]

    def set_m(r: int, c: int, dark: bool, func: bool = True) -> None:
        if 0 <= r < size and 0 <= c < size:
            module[r][c] = dark
            if func:
                is_function[r][c] = True

    def draw_finder(top: int, left: int) -> None:
        for r in range(-1, 8):
            for c in range(-1, 8):
                rr, cc = top + r, left + c
                if not (0 <= rr < size and 0 <= cc < size):
                    continue
                dark = (0 <= r <= 6 and c in (0, 6)) or (0 <= c <= 6 and r in (0, 6)) or (2 <= r <= 4 and 2 <= c <= 4)
                set_m(rr, cc, dark)

    draw_finder(0, 0)
    draw_finder(0, size - 7)
    draw_finder(size - 7, 0)

    for i in range(8, size - 8):
        set_m(6, i, i % 2 == 0)
        set_m(i, 6, i % 2 == 0)

    for r, c in _alignment_centers(version):
        for dr in range(-2, 3):
            for dc in range(-2, 3):
                dark = max(abs(dr), abs(dc)) != 1
                set_m(r + dr, c + dc, dark)

    set_m(4 * version + 9, 8, True)  # dark module

    fmt = _format_bits(level, mask)
    fmt_bits = [(fmt >> i) & 1 for i in range(15)]
    # around top-left finder: bit 14 starts at col 0 and counts down along row 8
    # (skipping col 6), then continues down bit 6..0 up col 8 (skipping row 6).
    tl_cols = [0, 1, 2, 3, 4, 5, 7, 8]
    for idx, col in enumerate(tl_cols):
        set_m(8, col, bool(fmt_bits[14 - idx]))
    tl_rows2 = [7, 5, 4, 3, 2, 1, 0]
    for idx, row in enumerate(tl_rows2):
        set_m(row, 8, bool(fmt_bits[6 - idx]))
    # top-right (row 8, rightmost 8 cols) -- bits 0..6 (msb side)
    for i in range(8):
        set_m(8, size - 1 - i, bool(fmt_bits[i]))
    # bottom-left (col 8, bottom 7 rows) -- bits 7..14
    for i in range(7):
        set_m(size - 1 - i, 8, bool(fmt_bits[14 - i]))

    if version >= 7:
        vbits = _version_bits(version)
        vb = [(vbits >> i) & 1 for i in range(18)]
        for i in range(18):
            r = i // 3
            c = i % 3
            set_m(size - 11 + c, r, bool(vb[i]))
            set_m(r, size - 11 + c, bool(vb[i]))

    # data placement (zigzag, right-to-left in 2-col strips, skipping col 6)
    bit_stream: list[int] = []
    for byte in codewords:
        for i in range(7, -1, -1):
            bit_stream.append((byte >> i) & 1)
    total_bits_needed = size * size
    while len(bit_stream) < total_bits_needed:
        bit_stream.append(0)  # remainder padding safety net

    mfn = _mask_fn(mask)
    bit_idx = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        for i in range(size):
            row = (size - 1 - i) if upward else i
            for c in (col, col - 1):
                if is_function[row][c]:
                    continue
                if bit_idx < len(bit_stream):
                    bit = bit_stream[bit_idx]
                    bit_idx += 1
                else:
                    bit = 0
                dark = bool(bit)
                if mfn(row, c):
                    dark = not dark
                module[row][c] = dark
        upward = not upward
        col -= 2

    return module


def _penalty(module) -> int:
    size = len(module)
    score = 0
    for r in range(size):
        run = 1
        for c in range(1, size):
            if module[r][c] == module[r][c - 1]:
                run += 1
            else:
                if run >= 5:
                    score += run - 2
                run = 1
        if run >= 5:
            score += run - 2
    for c in range(size):
        run = 1
        for r in range(1, size):
            if module[r][c] == module[r - 1][c]:
                run += 1
            else:
                if run >= 5:
                    score += run - 2
                run = 1
        if run >= 5:
            score += run - 2
    for r in range(size - 1):
        for c in range(size - 1):
            v = module[r][c]
            if v == module[r][c + 1] == module[r + 1][c] == module[r + 1][c + 1]:
                score += 3
    dark = sum(1 for row in module for v in row if v)
    total = size * size
    pct = dark * 100 // total
    score += (abs(pct - 50) // 5) * 10
    return score


def _encode_matrix(data: bytes, version: int, level: str):
    codewords = _build_codewords(data, version, level)
    best = None
    best_score = None
    for mask in range(8):
        m = _build_matrix(version, level, codewords, mask)
        s = _penalty(m)
        if best_score is None or s < best_score:
            best_score = s
            best = m
    return best


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def qr_matrix(text: str, *, level: str = "M") -> list[list[bool]]:
    """Return the boolean module matrix for ``text`` (True = dark)."""
    data = text.encode("utf-8")
    version = _pick_version(len(data), level)
    return _encode_matrix(data, version, level)


def qr_svg(text: str, *, size: int = 220, level: str = "M", quiet_zone: int = 4, dark: str = "#0F172A") -> str:
    """Render ``text`` as a standalone QR Code SVG string sized to ``size``x``size``."""
    matrix = qr_matrix(text, level=level)
    n = len(matrix)
    total = n + quiet_zone * 2
    unit = size / total
    rects = []
    for r in range(n):
        for c in range(n):
            if matrix[r][c]:
                x = (c + quiet_zone) * unit
                y = (r + quiet_zone) * unit
                rects.append(f'<rect x="{x:.3f}" y="{y:.3f}" width="{unit:.3f}" height="{unit:.3f}" fill="{dark}"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}" shape-rendering="crispEdges">'
        f'<rect x="0" y="0" width="{size}" height="{size}" fill="#ffffff"/>'
        f"{''.join(rects)}</svg>"
    )


__all__ = ["qr_svg", "qr_matrix"]
