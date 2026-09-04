from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import date
from pathlib import Path

from nano_offline.app_context import AppContext
from nano_offline.services.license_service import _b64url_encode

N = 121222505900373642741046915409968807464465500338188152466633095389824394680923911844926363919352962122395200376195855348468120675963716182479294123759150099474640181547137712220911142461139046029598610675610409620805731453817399060960217377099961130371303784273473490899463375578560276771593390299792373353283
D = 35832009159742408214894805153148843221411197835594868388599055859921543155146833395790370658493760505287697357029862670102757735855609959061124033224930272981232642856762370926184055917967174912642509655521055241138893891641928721697769609763421309649660125963605000660239832002141457420898381291028668426433
E = 65537


def sign(payload: dict) -> str:
    payload_part = _b64url_encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    message = payload_part.encode("ascii")
    digest_info_prefix = bytes.fromhex("3031300d060960864801650304020105000420")
    tail = digest_info_prefix + hashlib.sha256(message).digest()
    k = (N.bit_length() + 7) // 8
    em = b"\x00\x01" + b"\xff" * (k - len(tail) - 3) + b"\x00" + tail
    signature = pow(int.from_bytes(em, "big"), D, N).to_bytes(k, "big")
    return payload_part + "." + _b64url_encode(signature)


with tempfile.TemporaryDirectory(prefix="nano_phase5_license_") as td:
    ctx = AppContext.create(Path(td) / "nano.db")
    ctx.license.configure_public_key(N, E)
    device = ctx.license.device_id()
    payload = {
        "alg": "RS256",
        "license_key": "QED-TEST-1",
        "device_id": device,
        "edition": "pro",
        "expires_at": "2030-12-31",
    }
    token = sign(payload)
    installed = ctx.license.install_signed_token("QED-TEST-1", token, now=date(2026, 8, 19))
    assert installed.valid and installed.edition == "pro"
    # New service instance simulates a later offline app start: no network is used.
    offline_status = type(ctx.license)(ctx.db).status(now=date(2026, 8, 20))
    assert offline_status.valid and offline_status.license_key == "QED-TEST-1"

    bad = token[:-1] + ("A" if token[-1] != "A" else "B")
    try:
        ctx.license.install_signed_token("QED-TEST-1", bad, now=date(2026, 8, 19))
    except ValueError:
        pass
    else:
        raise AssertionError("tampered token accepted")

    other = dict(payload, device_id="other-device")
    try:
        ctx.license.install_signed_token("QED-TEST-1", sign(other), now=date(2026, 8, 19))
    except ValueError as exc:
        assert "جهاز آخر" in str(exc)
    else:
        raise AssertionError("other-device token accepted")

print("phase5_license_offline_smoke_test passed")
