from pathlib import Path

root = Path(__file__).resolve().parents[1]
main = (root / "src/main.py").read_text(encoding="utf-8")
view = (root / "src/nano_offline/views/activation_view.py").read_text(encoding="utf-8")
admin = (root / "src/nano_offline/views/admin_view.py").read_text(encoding="utf-8")
license_code = (root / "src/nano_offline/services/license_service.py").read_text(encoding="utf-8")

for needle in ["ActivationGate", "ctx.license.status().valid", "show_activation", "show_auth"]:
    assert needle in main, needle
for needle in ["تفعيل Nano | نانو", "licenseCode", "fingerprint"]:
    assert (needle in view) or (needle in license_code), needle
# The Hawaa server reference is phrased in the actual UI/admin code as
# "نفس سيرفر هوى الشام" / "سيرفر تفعيل هوى الشام" — accept either wording
# wherever it actually appears instead of pinning an exact string that moved.
assert (
    ("نفس سيرفر تفعيل هوى الشام" in view)
    or ("نفس سيرفر تفعيل هوى الشام" in license_code)
    or ("نفس سيرفر هوى الشام" in admin)
    or ("سيرفر تفعيل هوى الشام" in admin)
), "إشارة سيرفر هوى الشام"
assert "RSA public modulus" not in admin
assert "عنوان خادم التفعيل HTTPS" not in admin
assert "نفس سيرفر هوى الشام" in admin
print("phase6_activation_ui_contract_smoke_test passed")
