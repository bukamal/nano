from pathlib import Path

root = Path(__file__).resolve().parents[1]
main = (root / "src/main.py").read_text(encoding="utf-8")
admin = (root / "src/nano_offline/views/admin_view.py").read_text(encoding="utf-8")
for needle in ["إنشاء المدير الأول", "تسجيل الدخول المحلي", "actions = {", "allowed_keys", "session.can(k)", "AdminCenter"]:
    assert needle in main, needle
for needle in ["المستخدمون المحليون", "النسخ الاحتياطي والاسترجاع", "سجل التدقيق", "create_backup", "restore_backup"]:
    assert needle in admin, needle
assert ("التفعيل الأونلاين فقط" in admin) or ("نفس سيرفر هوى الشام" in admin)
print("phase5_admin_ui_contract_smoke_test passed")
