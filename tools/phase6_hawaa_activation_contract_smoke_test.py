from __future__ import annotations

import io
import json
import tempfile
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from nano_offline.app_context import AppContext
from nano_offline.services.license_service import HAWAA_ACTIVATION_URL, HAWAA_PROTOCOL, LicenseService


class FakeResponse:
    status = 200

    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


with tempfile.TemporaryDirectory(prefix="nano_phase6_hawaa_license_") as td:
    ctx = AppContext.create(Path(td) / "nano.db")
    captured = {}
    original = urllib.request.urlopen

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["user_agent"] = request.get_header("User-agent")
        return FakeResponse({"expirationDate": "2030-12-31", "edition": "standard"})

    urllib.request.urlopen = fake_urlopen
    try:
        status = ctx.license.activate_online("QED-TEST-HAWAA", "0.6.0")
    finally:
        urllib.request.urlopen = original

    assert captured["url"] == HAWAA_ACTIVATION_URL
    assert set(captured["body"]) == {"licenseCode", "fingerprint"}
    assert captured["body"]["licenseCode"] == "QED-TEST-HAWAA"
    assert captured["body"]["fingerprint"] == ctx.license.device_id()
    assert captured["user_agent"] == "Nano-Offline/0.6.0"
    serialized = json.dumps(captured["body"], ensure_ascii=False).lower()
    for forbidden in ["customer", "supplier", "invoice", "inventory", "report", "user"]:
        assert forbidden not in serialized

    assert status.valid and status.protocol == HAWAA_PROTOCOL
    assert status.license_key == "QED-TEST-HAWAA"

    # Offline restart: status must not perform any HTTP request.
    def network_forbidden(*args, **kwargs):
        raise AssertionError("offline status unexpectedly accessed the network")

    urllib.request.urlopen = network_forbidden
    try:
        offline = LicenseService(ctx.db).status(now=date(2029, 1, 1))
    finally:
        urllib.request.urlopen = original
    assert offline.valid and offline.protocol == HAWAA_PROTOCOL
    assert not LicenseService(ctx.db).status(now=date(2031, 1, 1)).valid

    # Cloudflare Error 1010 must be translated to a concise, actionable message
    # instead of leaking the raw JSON/HTML response into the activation UI.
    cloudflare_1010 = json.dumps({
        "status": 403,
        "error_code": 1010,
        "error_name": "browser_signature_banned",
        "detail": "The site owner has blocked access based on your browser's signature.",
    }).encode("utf-8")

    def blocked_urlopen(request, timeout=0):
        raise urllib.error.HTTPError(
            request.full_url,
            403,
            "Forbidden",
            hdrs=None,
            fp=io.BytesIO(cloudflare_1010),
        )

    urllib.request.urlopen = blocked_urlopen
    try:
        try:
            ctx.license.activate_online("QED-BLOCKED", "0.7.0")
        except RuntimeError as exc:
            error_text = str(exc)
        else:
            raise AssertionError("Cloudflare 1010 unexpectedly succeeded")
    finally:
        urllib.request.urlopen = original
    assert "Error 1010" in error_text
    assert "إعادة المحاولة الآن لن تفيد" in error_text
    assert "browser_signature_banned" not in error_text

    # Local tampering is detected by the device-bound MAC/seal.
    with ctx.db.transaction() as conn:
        token = str(conn.execute("SELECT signed_token FROM license_state WHERE id=1").fetchone()[0])
        conn.execute("UPDATE license_state SET signed_token=? WHERE id=1", (token[:-1] + ("A" if token[-1] != "A" else "B"),))
    assert not LicenseService(ctx.db).status(now=date(2029, 1, 1)).valid

print("phase6_hawaa_activation_contract_smoke_test passed")
