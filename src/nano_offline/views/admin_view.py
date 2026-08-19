from __future__ import annotations

from pathlib import Path
from datetime import datetime
import asyncio
import shutil

import flet as ft

from nano_offline.components import SearchSelect
from nano_offline.services.auth_service import ROLE_LABELS
from nano_offline.version import APP_VERSION


class AdminCenter:
    def __init__(self, page: ft.Page, ctx, content: ft.Container, *, on_logout, native_files=None):
        self.page = page
        self.ctx = ctx
        self.content = content
        self.on_logout = on_logout
        self.native_files = native_files

    def _notify(self, text: str):
        self.page.open(ft.SnackBar(ft.Text(text)))

    def _section(self, title: str, controls: list[ft.Control]) -> ft.Container:
        return ft.Container(
            ft.Column([ft.Text(title, size=18, weight=ft.FontWeight.BOLD), *controls], spacing=10),
            padding=14,
            border=ft.border.all(1, "#E5E7EB"),
            border_radius=12,
            bgcolor="#FFFFFF",
        )

    def show_center(self):
        self.ctx.auth.require("admin")
        session = self.ctx.auth.current()
        backups_dir = self.ctx.db.path.parent / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)

        username = ft.TextField(label="اسم المستخدم")
        full_name = ft.TextField(label="الاسم الكامل")
        password = ft.TextField(label="كلمة المرور", password=True, can_reveal_password=True)
        role = SearchSelect(
            label="الدور",
            value="accountant",
            choices=[(k, v) for k, v in ROLE_LABELS.items()],
            allow_clear=False,
        )
        users_list = ft.Column(spacing=8)

        def refresh_users():
            users_list.controls = []
            for user in self.ctx.auth.list_users():
                active = bool(user["is_active"])

                def toggle(e, user_id=int(user["id"])):
                    try:
                        self.ctx.auth.set_active(user_id, bool(e.control.value))
                        refresh_users()
                        self.page.update()
                    except Exception as exc:
                        self._notify(str(exc))
                        refresh_users()
                        self.page.update()

                users_list.controls.append(
                    ft.Container(
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(str(user["full_name"]), weight=ft.FontWeight.BOLD),
                                        ft.Text(
                                            f"{user['username']} • {ROLE_LABELS.get(str(user['role']), user['role'])}",
                                            size=12,
                                            color="#64748B",
                                        ),
                                    ],
                                    expand=True,
                                    spacing=2,
                                ),
                                ft.Switch(value=active, label="نشط", on_change=toggle),
                            ]
                        ),
                        padding=10,
                        border=ft.border.all(1, "#E5E7EB"),
                        border_radius=10,
                    )
                )

        def create_user(_):
            try:
                self.ctx.auth.create_user(
                    username=username.value or "",
                    full_name=full_name.value or "",
                    password=password.value or "",
                    role=role.value or "accountant",
                )
                username.value = full_name.value = password.value = ""
                refresh_users()
                self._notify("تم إنشاء المستخدم")
                self.page.update()
            except Exception as exc:
                self._notify(str(exc))

        refresh_users()

        backup_name = ft.TextField(label="اسم النسخة", value="nano_backup")
        backup_choice = SearchSelect(label="نسخة للاسترجاع")
        backup_info = ft.Text("", size=12, color="#64748B")

        def refresh_backups():
            files = sorted(list(backups_dir.glob("*.nanobackup")) + list(backups_dir.glob("*.qeidbackup")), reverse=True)
            backup_choice.set_choices([(str(p), p.name) for p in files])
            if files and not backup_choice.value:
                backup_choice.value = str(files[0])

        def _backup_target() -> Path:
            stem = (backup_name.value or "nano_backup").strip().replace("/", "_").replace("\\", "_")
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            return backups_dir / f"{stem}_{stamp}.nanobackup"

        async def _create_backup_file() -> Path:
            target = _backup_target()
            result = await asyncio.to_thread(self.ctx.backup.create_backup, target)
            validation = await asyncio.to_thread(self.ctx.backup.validate_backup, result)
            backup_info.value = (
                f"تم إنشاء {result.name} • schema {validation.schema_version} • "
                f"البصمة {validation.db_sha256[:12]}…"
            )
            refresh_backups()
            backup_choice.value = str(result)
            self.page.update()
            return result

        async def make_backup(_):
            try:
                await _create_backup_file()
                self._notify("تم إنشاء النسخة الاحتياطية بنجاح")
            except Exception as exc:
                self._notify(str(exc))

        async def make_and_share_backup(_):
            try:
                result = await _create_backup_file()
                if self.native_files is None:
                    self._notify(f"تم إنشاء النسخة محليًا: {result.name}")
                    return
                shared = await self.native_files.share_file(
                    str(result),
                    mime_type="application/zip",
                    text="نسخة احتياطية من Nano | نانو",
                    subject=result.name,
                )
                if not shared:
                    self._notify(f"تم إنشاء النسخة محليًا: {result.name}")
            except Exception as exc:
                self._notify(str(exc))

        def open_restore_dialog(path: str | Path, *, external_name: str | None = None):
            try:
                path = Path(path)
                validation = self.ctx.backup.validate_backup(path)

                def confirm(_):
                    try:
                        self.page.close(dialog)
                        safety = self.ctx.backup.restore_backup(path)
                        backup_info.value = f"تم الاسترجاع. نسخة الأمان: {Path(safety).name}"
                        self._notify("تم الاسترجاع بنجاح. أعد تشغيل التطبيق لإعادة تحميل جميع الشاشات.")
                        refresh_backups()
                        self.page.update()
                    except Exception as exc:
                        self._notify(str(exc))

                source_label = external_name or path.name
                dialog = ft.AlertDialog(
                    modal=True,
                    title=ft.Text("تأكيد الاسترجاع"),
                    content=ft.Text(
                        f"سيتم استرجاع {source_label} (schema {validation.schema_version}). "
                        "سيُنشأ Backup أمان تلقائيًا، ولن يتم نقل ترخيص جهاز آخر."
                    ),
                    actions=[
                        ft.TextButton("إلغاء", on_click=lambda _: self.page.close(dialog)),
                        ft.FilledButton("استرجاع", icon=ft.Icons.RESTORE, on_click=confirm),
                    ],
                )
                self.page.open(dialog)
            except Exception as exc:
                self._notify(str(exc))

        def restore_backup(_):
            if not backup_choice.value:
                self._notify("اختر نسخة للاسترجاع")
                return
            open_restore_dialog(backup_choice.value)

        async def share_backup(_):
            if not backup_choice.value:
                self._notify("اختر نسخة للمشاركة")
                return
            if self.native_files is None:
                self._notify("مشاركة الملفات الأصلية غير مهيأة في هذا البناء")
                return
            try:
                path = Path(backup_choice.value)
                self.ctx.backup.validate_backup(path)
                await self.native_files.share_file(
                    str(path),
                    mime_type="application/zip",
                    text="نسخة احتياطية من Nano | نانو",
                    subject=path.name,
                )
            except Exception as exc:
                self._notify(str(exc))

        async def import_external_backup(_):
            if self.native_files is None:
                self._notify("استيراد الملفات الأصلي غير مهيأ في هذا البناء")
                return
            try:
                # Android document providers are inconsistent with custom file
                # extensions, so open all files and validate Nano's container
                # ourselves before copying it into persistent local storage.
                picked = await self.native_files.pick_file(
                    extensions=None,
                    dialog_title="اختر النسخة الاحتياطية لـ Nano",
                )
                if not picked:
                    return
                source = Path(str(picked["path"]))
                validation = await asyncio.to_thread(self.ctx.backup.validate_backup, source)
                original_name = str(picked.get("name") or source.name or "imported_backup")
                safe_stem = Path(original_name).stem.replace("/", "_").replace("\\", "_") or "imported_backup"
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                target = backups_dir / f"{safe_stem}_{stamp}.nanobackup"
                await asyncio.to_thread(shutil.copy2, source, target)
                # Validate the persisted copy too; restore never depends on the
                # transient Android picker cache path.
                await asyncio.to_thread(self.ctx.backup.validate_backup, target)
                refresh_backups()
                backup_choice.value = str(target)
                backup_info.value = f"تم استيراد {target.name} • schema {validation.schema_version}"
                self.page.update()
                open_restore_dialog(target, external_name=original_name)
            except Exception as exc:
                self._notify(str(exc))

        refresh_backups()

        license_key = ft.TextField(label="مفتاح الترخيص", password=True, can_reveal_password=True)
        license_state = ft.Text("", size=12)
        license_server = ft.Text(self.ctx.license.activation_url(), size=10, color="#64748B", selectable=True)
        license_device = ft.Text("", size=11, color="#64748B", selectable=True)
        activation_progress = ft.ProgressBar(visible=False)
        activation_button = ft.FilledButton("إعادة التفعيل", icon=ft.Icons.VERIFIED_USER)

        def refresh_license():
            status = self.ctx.license.status()
            license_device.value = f"معرّف الجهاز: {status.device_id}"
            if status.valid:
                license_state.value = f"مفعل • {status.edition or 'standard'} • الانتهاء {status.expires_at or 'دائم/غير محدد'} • {status.protocol or 'hawaa-v1'}"
                license_state.color = "#15803D"
            else:
                license_state.value = f"غير صالح/غير مفعل • {status.reason or ''}"
                license_state.color = "#B91C1C"

        async def activate(_):
            activation_button.disabled = True
            activation_progress.visible = True
            self.page.update()
            try:
                status = await asyncio.to_thread(self.ctx.license.activate_online, license_key.value or "", APP_VERSION)
                refresh_license()
                self._notify("تم التفعيل عبر سيرفر هوى الشام" if status.valid else (status.reason or "فشل التفعيل"))
            except Exception as exc:
                self._notify(str(exc))
            finally:
                activation_button.disabled = False
                activation_progress.visible = False
                self.page.update()

        activation_button.on_click = activate
        refresh_license()

        audit_list = ft.Column(spacing=6)

        def refresh_audit(_=None):
            audit_list.controls = []
            for row in self.ctx.auth.audit_entries(100):
                actor = row.get("username") or "النظام"
                audit_list.controls.append(
                    ft.Container(
                        ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Text(f"{row['action']} • {row['entity_type']} #{row.get('entity_id') or '-'}", weight=ft.FontWeight.BOLD, expand=True),
                                        ft.Text(str(row["created_at"]), size=11, color="#64748B"),
                                    ]
                                ),
                                ft.Text(f"المستخدم: {actor} • {row.get('details') or ''}", size=12, color="#475569"),
                            ],
                            spacing=3,
                        ),
                        padding=8,
                        border=ft.border.all(1, "#E5E7EB"),
                        border_radius=8,
                    )
                )
            self.page.update()

        refresh_audit()

        self.content.content = ft.Column(
            [
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text("الإدارة والأمان", size=24, weight=ft.FontWeight.BOLD),
                                ft.Text(f"المستخدم الحالي: {session.full_name} ({ROLE_LABELS.get(session.role, session.role)})", size=12, color="#64748B"),
                            ],
                            expand=True,
                        ),
                        ft.OutlinedButton("تسجيل الخروج", icon=ft.Icons.LOGOUT, on_click=lambda _: self.on_logout()),
                    ]
                ),
                self._section(
                    "المستخدمون المحليون",
                    [
                        ft.ResponsiveRow(
                            [
                                ft.Container(username, col={"xs": 12, "md": 3}),
                                ft.Container(full_name, col={"xs": 12, "md": 3}),
                                ft.Container(password, col={"xs": 12, "md": 3}),
                                ft.Container(role, col={"xs": 12, "md": 3}),
                            ]
                        ),
                        ft.FilledButton("إنشاء مستخدم", icon=ft.Icons.PERSON_ADD, on_click=create_user),
                        users_list,
                    ],
                ),
                self._section(
                    "النسخ الاحتياطي والاسترجاع",
                    [
                        ft.Text("النسخة تحتوي البيانات والمستخدمين، ولا تحتوي ترخيص الجهاز. يمكن مشاركتها عبر Android واستيراد ملف .nanobackup أو .qeidbackup من أي مزود مستندات. النسخة غير مشفرة؛ احفظها في مكان آمن.", size=12, color="#B45309"),
                        ft.ResponsiveRow(
                            [
                                ft.Container(backup_name, col={"xs": 12, "md": 5}),
                                ft.Container(
                                    ft.FilledButton(
                                        "إنشاء ومشاركة نسخة",
                                        icon=ft.Icons.BACKUP,
                                        on_click=make_and_share_backup,
                                    ),
                                    col={"xs": 12, "md": 4},
                                ),
                                ft.Container(
                                    ft.OutlinedButton("إنشاء محليًا", icon=ft.Icons.SAVE_OUTLINED, on_click=make_backup),
                                    col={"xs": 12, "md": 3},
                                ),
                            ]
                        ),
                        ft.FilledButton(
                            "استيراد نسخة من الجهاز",
                            icon=ft.Icons.UPLOAD_FILE,
                            on_click=import_external_backup,
                        ),
                        backup_choice,
                        ft.Row(
                            [
                                ft.OutlinedButton("مشاركة النسخة", icon=ft.Icons.SHARE_OUTLINED, on_click=share_backup),
                                ft.OutlinedButton("استرجاع النسخة المحلية", icon=ft.Icons.RESTORE, on_click=restore_backup),
                            ],
                            wrap=True,
                        ),
                        backup_info,
                    ],
                ),
                self._section(
                    "التفعيل — نفس سيرفر هوى الشام",
                    [
                        ft.Text("تطبيق Nano يرسل مفتاح الترخيص ومعرّف الجهاز فقط إلى سيرفر تفعيل هوى الشام. لا تُرسل الفواتير أو العملاء أو الموردون أو المخزون. بعد نجاح التفعيل يعمل التطبيق أوفلاين.", size=12, color="#475569"),
                        ft.Text("سيرفر التفعيل", size=11, color="#64748B"),
                        license_server,
                        license_device,
                        ft.ResponsiveRow(
                            [
                                ft.Container(license_key, col={"xs": 12, "md": 8}),
                                ft.Container(activation_button, col={"xs": 12, "md": 4}),
                            ]
                        ),
                        activation_progress,
                        license_state,
                    ],
                ),
                self._section(
                    "سجل التدقيق",
                    [ft.OutlinedButton("تحديث السجل", icon=ft.Icons.REFRESH, on_click=refresh_audit), audit_list],
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            spacing=12,
        )
        self.page.update()
