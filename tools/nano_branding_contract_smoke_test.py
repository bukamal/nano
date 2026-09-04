from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
main = (ROOT / "src/main.py").read_text(encoding="utf-8")
pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
activation = (ROOT / "src/nano_offline/views/activation_view.py").read_text(encoding="utf-8")
license_service = (ROOT / "src/nano_offline/services/license_service.py").read_text(encoding="utf-8")

assert 'name = "nano-offline"' in pyproject
assert 'product = "Nano | نانو"' in pyproject
assert 'org = "com.nano"' in pyproject
assert 'src="icon.png"' in main
assert 'src="icon.png"' in activation
assert 'f"Nano-Offline/{version_token}"' in license_service

assets = ROOT / "src/assets"
for name in [
    "icon.png", "icon_android.png", "icon_ios.png", "icon_web.png",
    "icon_macos.png", "icon_windows.ico", "splash.png", "splash_dark.png",
]:
    assert (assets / name).is_file(), name

# Navigation contract: materials are next to home and sale is the central mobile action.
assert 'mobile_item("dashboard", "الرئيسية"' in main
assert 'mobile_item("items", "المواد"' in main
assert 'sale_fab' in main
assert 'mobile_item("invoices", "الفواتير"' in main
assert 'mobile_item("more", "المزيد"' in main

print("nano_branding_contract_smoke_test passed")
