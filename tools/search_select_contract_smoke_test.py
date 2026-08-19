from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source_files = [ROOT / "src" / "main.py", *(ROOT / "src" / "nano_offline" / "views").glob("*.py")]
joined = "\n".join(p.read_text(encoding="utf-8") for p in source_files)
component = (ROOT / "src" / "nano_offline" / "components" / "search_select.py").read_text(encoding="utf-8")
main = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
auth = (ROOT / "src" / "nano_offline" / "services" / "auth_service.py").read_text(encoding="utf-8")

assert "ft.Dropdown(" not in joined
assert "dropdown.Option" not in joined
assert "class SearchSelect" in component
assert "اكتب للبحث والاختيار" in component
assert "البقاء مسجلاً على هذا الجهاز" in main
assert "الدخول بـ PIN" in main
assert "الدخول بالنمط" in main
assert "set_quick_auth" in auth and "restore_saved_session" in auth
print("search_select_contract_smoke_test passed")
