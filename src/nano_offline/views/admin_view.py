from __future__ import annotations

from pathlib import Path
from datetime import datetime
import asyncio
import base64
import shutil

import flet as ft

from nano_offline.core.toast import toast

from nano_offline.components import SearchSelect, SegmentedToggle, SegmentOption, SelectAllTextField
from nano_offline.services.auth_service import ROLE_LABELS
from nano_offline.version import APP_VERSION
from nano_offline.core.theme import Colors, Shadow
from nano_offline.core import theme
from nano_offline.core import theme_settings
from nano_offline.core import currency
from nano_offline.core import barcode_settings
from nano_offline.core import invoice_settings
from nano_offline.core import pos_settings
from nano_offline.core import backup_settings
from nano_offline.core import reporting_settings
from nano_offline.core import sound_settings
from nano_offline.core import sound as sound_engine
from nano_offline.core import barcode_quality
from nano_offline.core.barcode128 import code128b_bars


class AdminCenter:
    def __init__(self, page: ft.Page, ctx, content: ft.Container, *, on_logout, native_files=None, on_theme_changed=None):
        self.page = page
        self.ctx = ctx
        self.content = content
        self.on_logout = on_logout
        self.native_files = native_files
        # Called after the night-mode preference/schedule is saved so the
        # whole app can be torn down and rebuilt with the new palette right
        # away (see main.py's build_shell/open_shell) -- optional purely so
        # this view stays constructible in isolation (e.g. future tests).
        self.on_theme_changed = on_theme_changed or (lambda: None)

    def _notify(self, text: str, kind: str | None = None, sound_kind: str | None = None):
        toast(self.page, text, kind=kind, sound_kind=sound_kind)

    def _notify_error(self, text: str):
        # A SnackBar is easy to miss: it auto-dismisses on its own timer and
        # can be visually subtle. Restore/validation failures are exactly
        # the kind of message a user must not miss -- if they do, "restore"
        # looks like it silently did nothing. Use the same
        # dismiss-it-yourself AlertDialog pattern already used for the
        # restore *success* message, so failures get equal visibility.
        # This dialog is built by hand instead of going through toast(), so
        # it used to skip the sound-cue system entirely -- a restore/
        # validation failure landed as a silent dialog with no matching
        # tone even when every other error in the app already had one.
        sound_engine.play(self.page, "error")
        error_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("تعذّر تنفيذ العملية"),
            content=ft.Text(text),
            actions=[ft.FilledButton("حسنًا", on_click=lambda _: self.page.close(error_dialog))],
        )
        self.page.open(error_dialog)

    def _section(self, title: str, controls: list[ft.Control]) -> ft.Container:
        return ft.Container(
            ft.Column([ft.Text(title, size=18, weight=ft.FontWeight.BOLD), *controls], spacing=10),
            padding=14,
            border=ft.border.all(1, Colors.BORDER_ALT),
            border_radius=12,
            bgcolor=Colors.WHITE,
            shadow=Shadow.SM,
        )

    def show_center(self):
        self.ctx.auth.require("admin")
        session = self.ctx.auth.current()
        backups_dir = self.ctx.db.path.parent / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)

        username = SelectAllTextField(label="اسم المستخدم")
        full_name = SelectAllTextField(label="الاسم الكامل")
        password = SelectAllTextField(label="كلمة المرور", password=True, can_reveal_password=True)
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
                        self._notify(str(exc), kind="error")
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
                                            color=Colors.TEXT_SECONDARY,
                                        ),
                                    ],
                                    expand=True,
                                    spacing=2,
                                ),
                                ft.Switch(value=active, label="نشط", on_change=toggle),
                            ]
                        ),
                        padding=10,
                        border=ft.border.all(1, Colors.BORDER_ALT),
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
                self._notify(str(exc), kind="error")

        refresh_users()

        backup_name = SelectAllTextField(label="اسم النسخة", value="nano_backup")
        backup_info = ft.Text("", size=12, color=Colors.TEXT_SECONDARY)
        backup_cards = ft.Column(spacing=8)
        backup_warning_banner = ft.Container(visible=False, padding=10, border_radius=10, bgcolor=Colors.WARNING_BG, border=ft.border.all(1, Colors.WARNING))

        def _human_when(mtime: float) -> str:
            dt = datetime.fromtimestamp(mtime)
            delta = datetime.now() - dt
            if delta.days <= 0:
                hours = int(delta.total_seconds() // 3600)
                return "الآن" if hours <= 0 else f"قبل {hours} ساعة"
            if delta.days == 1:
                return "أمس"
            return f"قبل {delta.days} يوم"

        def _human_size(num_bytes: int) -> str:
            if num_bytes < 1024:
                return f"{num_bytes} B"
            kb = num_bytes / 1024
            if kb < 1024:
                return f"{kb:.0f} KB"
            return f"{kb / 1024:.1f} MB"

        def _backup_card(path: Path) -> ft.Container:
            try:
                stat = path.stat()
            except FileNotFoundError:
                return ft.Container(width=0, height=0)
            try:
                self.ctx.backup.validate_backup(path)
                verified = True
            except Exception:
                verified = False

            def do_restore(_):
                # Reuses open_restore_dialog() exactly as-is -- the single
                # mutated-in-place AlertDialog instance documented above --
                # only the entry point (a card button instead of a shared
                # dropdown + separate button) changed.
                open_restore_dialog(path)

            async def do_share(_):
                if self.native_files is None:
                    self._notify("مشاركة الملفات الأصلية غير مهيأة في هذا البناء")
                    return
                try:
                    self.ctx.backup.validate_backup(path)
                    await self.native_files.share_file(
                        str(path), mime_type="application/zip", text="نسخة احتياطية من Nano | نانو", subject=path.name
                    )
                except Exception as exc:
                    self._notify(str(exc), kind="error")

            def do_delete(_):
                def confirm_delete(_ev=None):
                    self.page.close(confirm_dialog)
                    try:
                        path.unlink(missing_ok=True)
                        self._notify(f"تم حذف {path.name}", kind="success", sound_kind="delete")
                        refresh_backups()
                        self.page.update()
                    except Exception as exc:
                        self._notify(str(exc), kind="error")

                confirm_dialog = ft.AlertDialog(
                    modal=True,
                    title=ft.Text("حذف النسخة الاحتياطية"),
                    content=ft.Text(f"سيتم حذف {path.name} نهائيًا من هذا الجهاز. لا يمكن التراجع."),
                    actions=[
                        ft.TextButton("إلغاء", on_click=lambda _: self.page.close(confirm_dialog)),
                        ft.FilledButton("حذف", icon=ft.Icons.DELETE_OUTLINE, on_click=confirm_delete),
                    ],
                )
                self.page.open(confirm_dialog)

            badge_icon, badge_text, badge_color, badge_bg = (
                (ft.Icons.VERIFIED_ROUNDED, "سليمة", Colors.SUCCESS_DARKER, Colors.SUCCESS_BG)
                if verified
                else (ft.Icons.ERROR_OUTLINE_ROUNDED, "تالفة", Colors.DANGER_DARKER, Colors.DANGER_BG)
            )

            return ft.Container(
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Container(
                                    ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, color=Colors.PRIMARY, size=20),
                                    width=38, height=38, alignment=ft.alignment.center, bgcolor=Colors.PRIMARY_BG, border_radius=12,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(path.name, size=13, weight=ft.FontWeight.W_600, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                        ft.Text(f"{_human_when(stat.st_mtime)} • {_human_size(stat.st_size)}", size=11, color=Colors.TEXT_SECONDARY),
                                    ],
                                    spacing=1, expand=True,
                                ),
                                ft.Container(
                                    ft.Row([ft.Icon(badge_icon, size=12, color=badge_color), ft.Text(badge_text, size=10, color=badge_color)], spacing=3, tight=True),
                                    padding=ft.padding.symmetric(horizontal=8, vertical=4), bgcolor=badge_bg, border_radius=10,
                                ),
                            ],
                            spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Row(
                            [
                                ft.OutlinedButton("استرجاع", icon=ft.Icons.RESTORE, on_click=do_restore, disabled=not verified),
                                ft.OutlinedButton("مشاركة", icon=ft.Icons.SHARE_OUTLINED, on_click=do_share),
                                ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color=Colors.DANGER, on_click=do_delete, tooltip="حذف"),
                            ],
                            spacing=6, wrap=True,
                        ),
                    ],
                    spacing=8,
                ),
                padding=12, border=ft.border.all(1, Colors.BORDER_ALT), border_radius=14, bgcolor=Colors.WHITE, shadow=Shadow.SM,
            )

        def refresh_backups():
            files = sorted(
                list(backups_dir.glob("*.nanobackup")) + list(backups_dir.glob("*.qeidbackup")),
                key=lambda p: p.stat().st_mtime if p.exists() else 0,
                reverse=True,
            )
            backup_cards.controls = (
                [_backup_card(p) for p in files]
                if files
                else [ft.Container(ft.Text("لا توجد نسخ احتياطية بعد — أنشئ أول نسخة أدناه.", size=12, color=Colors.TEXT_SECONDARY), padding=14, alignment=ft.alignment.center)]
            )

            cfg = self.ctx.notifications.get_config()
            backup_cfg = cfg.get("backup", {})
            remind_after = int(backup_cfg.get("remind_after_days", 7))
            last_raw = self.ctx.notifications.settings.get("last_backup_at", "")
            if not last_raw and files:
                # Covers backups that already existed before this setting was
                # introduced, or a settings reset -- fall back to the newest
                # file's own timestamp instead of wrongly claiming "never".
                last_raw = datetime.fromtimestamp(files[0].stat().st_mtime).astimezone().isoformat(timespec="seconds")
            overdue_days = None
            if bool(backup_cfg.get("enabled", True)) and last_raw:
                try:
                    overdue_days = (datetime.now().astimezone() - datetime.fromisoformat(last_raw)).days
                except ValueError:
                    overdue_days = None

            if overdue_days is not None and overdue_days >= remind_after:
                backup_warning_banner.content = ft.Row(
                    [
                        ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=Colors.WARNING_DARK, size=18),
                        ft.Text(f"مرّ {overdue_days} يومًا منذ آخر نسخة احتياطية — يُستحسن إنشاء نسخة جديدة.", size=12, color=Colors.WARNING_DARKER, expand=True),
                    ],
                    spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                backup_warning_banner.visible = True
            else:
                backup_warning_banner.visible = False

        def _backup_target() -> Path:
            stem = (backup_name.value or "nano_backup").strip().replace("/", "_").replace("\\", "_")
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            return backups_dir / f"{stem}_{stamp}.nanobackup"

        async def _create_backup_file() -> Path:
            target = _backup_target()
            result = await asyncio.to_thread(self.ctx.backup.create_backup, target)
            validation = await asyncio.to_thread(self.ctx.backup.validate_backup, result)
            keep = backup_settings.retention_count(self.ctx.settings)
            if keep > 0:
                await asyncio.to_thread(self.ctx.backup.prune_backups, backups_dir, keep)
            backup_info.value = (
                f"تم إنشاء {result.name} • schema {validation.schema_version} • "
                f"البصمة {validation.db_sha256[:12]}…"
            )
            refresh_backups()
            self.page.update()
            # Resets the "لم يتم إنشاء نسخة احتياطية" / "حان وقت نسخة جديدة"
            # smart-notification rule so it doesn't immediately re-fire.
            self.ctx.notifications.record_backup_completed()
            return result

        async def make_backup(_):
            try:
                await _create_backup_file()
                self._notify("تم إنشاء النسخة الاحتياطية بنجاح")
            except Exception as exc:
                self._notify(str(exc), kind="error")

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
                self._notify(str(exc), kind="error")

        def open_restore_dialog(path: str | Path, *, external_name: str | None = None):
            # ROOT-CAUSE NOTE (read before touching this function again):
            # the previous version closed this confirm `dialog` and, in the
            # very same synchronous handler tick, opened a *second*,
            # brand-new AlertDialog (success_dialog / an error dialog from
            # _notify_error) to replace it. A user reported that pressing
            # "استرجاع" then confirming produced literally no visible
            # reaction at all -- not an error, not success, nothing. That
            # symptom is consistent with two different failure points we
            # cannot fully tell apart without an on-device log, and this
            # rewrite removes both at once instead of guessing which one it
            # is:
            #   1. Flet closing one modal and opening a different modal
            #      instance back-to-back, with no render in between, is a
            #      known source of the second dialog never actually
            #      reaching the screen (a close-then-open race).
            #   2. Any exception raised inside a plain `def` on_click
            #      handler before it reaches a UI call can be swallowed by
            #      Flet with nothing printed anywhere the user can see --
            #      this exact failure mode is what turned out to be the
            #      real bug behind the pattern-drawing screen in this app
            #      (see PATTERN_BACKUP_BARCODE_FIXES_AR.md, section 1).
            #
            # The fix for (1): never open a second AlertDialog. Keep a
            # single dialog instance alive for the whole flow and mutate
            # its own title/content/actions in place, then call
            # dialog.update() -- the same "update a control that is
            # already part of the open dialog's tree" approach already
            # used for the barcode scan status line in items_view.py,
            # which does not depend on any open/close transition timing.
            #
            # The fix for (2): every step below is wrapped so it cannot
            # fail silently -- each stage prints a `[nano-restore]` line
            # (visible via `adb logcat` / `flet build` run logs) *before*
            # doing anything that could raise, and the outermost except
            # both prints the traceback and still forces something onto
            # the screen. If this still shows "nothing happens" after this
            # change, the logcat output tells us exactly which of the
            # numbered steps was last reached instead of us guessing again.
            import traceback

            def log(step: str) -> None:
                print(f"[nano-restore] {step}", flush=True)

            try:
                log("0: fetching state for restore dialog")
                path = Path(path)
                validation = self.ctx.backup.validate_backup(path)
                source_label = external_name or path.name

                def set_dialog(*, title: str, content: ft.Control, actions: list[ft.Control]) -> None:
                    dialog.title = ft.Text(title)
                    dialog.content = content
                    dialog.actions = actions
                    dialog.update()

                def confirm(_):
                    try:
                        log("1: confirm pressed")
                        # Disable both buttons and swap the content to a
                        # "working" state immediately, before doing any
                        # file I/O. This alone proves (or disproves) that
                        # the click reached Python at all: if this message
                        # never appears, the problem is upstream of this
                        # function entirely (button wiring / Flet event
                        # delivery), not inside restore_backup().
                        set_dialog(
                            title="جارٍ الاسترجاع…",
                            content=ft.Row(
                                [ft.ProgressRing(width=18, height=18, stroke_width=2), ft.Text("يرجى الانتظار")],
                                spacing=10,
                            ),
                            actions=[],
                        )
                        log("2: calling backup.restore_backup")
                        safety = self.ctx.backup.restore_backup(path)
                        log("3: restore_backup returned, reloading context")
                        # restore_backup() only swaps the .db file on disk. Every
                        # view already holds Python objects it fetched before the
                        # restore, and a couple of services (invoices/expenses)
                        # compute derived state once at startup rather than per
                        # query -- so without this, the restored data silently
                        # never reaches the screen and it looks like "restore does
                        # nothing" even though the file on disk is correct.
                        self.ctx.reload(self.ctx.db.path)
                        log("4: context reloaded, showing success state")
                        # Every view currently on screen was built from
                        # pre-restore data, so the user still needs to go back to
                        # login and let the shell rebuild from scratch against the
                        # restored database -- also re-establishes the session
                        # cleanly if users/roles changed in the restored copy.
                        set_dialog(
                            title="تم الاسترجاع بنجاح",
                            content=ft.Text(f"نسخة الأمان: {Path(safety).name}"),
                            actions=[
                                ft.FilledButton(
                                    "متابعة",
                                    on_click=lambda _: (self.page.close(dialog), self.on_logout()),
                                ),
                            ],
                        )
                        log("5: success state shown, waiting for user to continue")
                    except Exception as exc:
                        log(f"ERROR during confirm: {exc!r}")
                        traceback.print_exc()
                        set_dialog(
                            title="تعذّر تنفيذ الاسترجاع",
                            content=ft.Text(str(exc), color=Colors.DANGER),
                            actions=[ft.FilledButton("حسنًا", on_click=lambda _: self.page.close(dialog))],
                        )

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
                log("dialog built, opening")
                self.page.open(dialog)
                log("page.open(dialog) returned")
            except Exception as exc:
                log(f"ERROR before dialog open: {exc!r}")
                traceback.print_exc()
                self._notify_error(str(exc))

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
                backup_info.value = f"تم استيراد {target.name} • schema {validation.schema_version}"
                self.page.update()
                open_restore_dialog(target, external_name=original_name)
            except Exception as exc:
                self._notify_error(str(exc))

        refresh_backups()

        # License tab: server URL, device ID and status are treated as
        # private data and masked by default, the same way the activation
        # screen (ActivationGate) never shows a full device ID and always
        # keeps the license key itself behind a password field. An explicit
        # reveal toggle is the only way to see the real values here.
        license_key = SelectAllTextField(label="مفتاح الترخيص", password=True, can_reveal_password=True)
        license_state = ft.Text("", size=12)
        license_server = ft.Text("", size=10, color=Colors.TEXT_SECONDARY, selectable=False)
        license_device = ft.Text("", size=11, color=Colors.TEXT_SECONDARY, selectable=False)
        activation_progress = ft.ProgressBar(visible=False)
        activation_button = ft.FilledButton("إعادة التفعيل", icon=ft.Icons.VERIFIED_USER)

        _license_raw = {"server": self.ctx.license.activation_url(), "device": "", "status": ""}
        _license_reveal = {"on": False}

        def _mask_secret(value: str) -> str:
            if not value:
                return ""
            if len(value) <= 10:
                return "•" * len(value)
            return f"{value[:4]}••••••••{value[-4:]}"

        def _apply_license_visibility():
            revealed = _license_reveal["on"]
            license_server.value = _license_raw["server"] if revealed else _mask_secret(_license_raw["server"])
            device = _license_raw["device"]
            license_device.value = "معرّف الجهاز: " + (device if revealed else _mask_secret(device))
            license_server.selectable = revealed
            license_device.selectable = revealed
            license_reveal_button.icon = ft.Icons.VISIBILITY_OFF_OUTLINED if revealed else ft.Icons.VISIBILITY_OUTLINED
            license_reveal_button.tooltip = "إخفاء بيانات الترخيص" if revealed else "إظهار بيانات الترخيص (خاصة)"

        def toggle_license_reveal(_):
            _license_reveal["on"] = not _license_reveal["on"]
            _apply_license_visibility()
            self.page.update()

        license_reveal_button = ft.IconButton(
            icon=ft.Icons.VISIBILITY_OUTLINED,
            icon_size=16,
            icon_color=Colors.TEXT_FAINT,
            tooltip="إظهار بيانات الترخيص (خاصة)",
            on_click=toggle_license_reveal,
            width=28,
            height=28,
        )

        def refresh_license():
            status = self.ctx.license.status()
            _license_raw["device"] = status.device_id or ""
            if status.valid:
                license_state.value = f"مفعل • {status.edition or 'standard'} • الانتهاء {status.expires_at or 'دائم/غير محدد'} • {status.protocol or 'hawaa-v1'}"
                license_state.color = Colors.SUCCESS_DARK
            else:
                license_state.value = f"غير صالح/غير مفعل • {status.reason or ''}"
                license_state.color = Colors.DANGER_DARKER
            _apply_license_visibility()

        async def activate(_):
            activation_button.disabled = True
            activation_progress.visible = True
            self.page.update()
            try:
                status = await asyncio.to_thread(self.ctx.license.activate_online, license_key.value or "", APP_VERSION)
                refresh_license()
                self._notify("تم التفعيل عبر سيرفر هوى الشام" if status.valid else (status.reason or "فشل التفعيل"))
            except Exception as exc:
                self._notify(str(exc), kind="error")
            finally:
                activation_button.disabled = False
                activation_progress.visible = False
                self.page.update()

        activation_button.on_click = activate
        refresh_license()

        # --- Branding: company name/currency + logo + invoice accent color.
        # Printed documents (invoices, statements, barcode labels) all read
        # these from the `settings` table via DocumentService._shell(), so
        # saving here changes every future printed/PDF document immediately
        # -- no restart needed.
        brand_settings = self.ctx.settings.get_all()
        ACCENT_PALETTE = [
            ("#0F766E", "أخضر مزرق"), ("#2563EB", "أزرق"), ("#4F46E5", "نيلي"),
            ("#7C3AED", "بنفسجي"), ("#DB2777", "وردي"), ("#DC2626", "أحمر"),
            ("#D97706", "كهرماني"), ("#334155", "رمادي داكن"),
        ]
        brand_state = {"color": brand_settings.get("invoice_color") or ACCENT_PALETTE[0][0], "logo": brand_settings.get("company_logo") or ""}

        company_name_field = SelectAllTextField(label="اسم الشركة/المتجر", value=brand_settings.get("company_name") or "نانو")
        currency_field = SelectAllTextField(label="العملة المخزَّنة (الأساس)", value=brand_settings.get("currency") or "USD", read_only=True, tooltip="كل الأسعار تُخزَّن داخليًا بهذه العملة، ولا يمكن تغييرها من هنا")
        display_currency_value = currency.get_display_currency(self.ctx.settings)
        SYMBOL_BY_DISPLAY_CURRENCY = {
            currency.DISPLAY_CURRENCY_SYP: currency.DEFAULT_DISPLAY_SYMBOL,
            currency.DISPLAY_CURRENCY_USD: currency.DEFAULT_USD_DISPLAY_SYMBOL,
        }
        display_currency_field = SegmentedToggle(
            options=[
                SegmentOption(currency.DISPLAY_CURRENCY_SYP, "الليرة السورية", ft.Icons.CURRENCY_EXCHANGE),
                SegmentOption(currency.DISPLAY_CURRENCY_USD, "الدولار الأمريكي", ft.Icons.ATTACH_MONEY),
            ],
            value=display_currency_value,
        )
        # The symbol is no longer a separate field the admin types in --
        # each currency has one conventional symbol, so picking the
        # currency above picks its symbol automatically. This just shows
        # which one will be used.
        symbol_preview = ft.Text(
            f"سيظهر بجانب المبالغ الرمز: {SYMBOL_BY_DISPLAY_CURRENCY[display_currency_value]}",
            size=11, color=Colors.TEXT_FAINT,
        )
        display_currency_group = ft.Column(
            [
                ft.Text("العملة المعروضة في الشاشات والفواتير", size=12, color=Colors.TEXT_MUTED_DARK, weight=ft.FontWeight.W_600),
                display_currency_field,
                symbol_preview,
            ],
            spacing=6,
        )
        exchange_rate_field = SelectAllTextField(
            label="سعر صرف الدولار (ل.س لكل 1$)",
            value=brand_settings.get(currency.EXCHANGE_RATE_KEY) or str(int(currency.DEFAULT_EXCHANGE_RATE)),
            keyboard_type=ft.KeyboardType.NUMBER,
            hint_text="مثال: 13500",
            visible=display_currency_value == currency.DISPLAY_CURRENCY_SYP,
        )

        def display_currency_changed(_):
            is_syp = display_currency_field.value == currency.DISPLAY_CURRENCY_SYP
            exchange_rate_field.visible = is_syp
            symbol_preview.value = f"سيظهر بجانب المبالغ الرمز: {SYMBOL_BY_DISPLAY_CURRENCY[display_currency_field.value]}"
            self.page.update()

        display_currency_field.on_change = display_currency_changed
        logo_preview = ft.Container(
            content=ft.Image(src_base64=brand_state["logo"].split(",", 1)[1], fit=ft.ImageFit.CONTAIN) if brand_state["logo"] and "," in brand_state["logo"] else ft.Icon(ft.Icons.IMAGE_OUTLINED, color=Colors.TEXT_FAINT, size=28),
            width=90, height=60, alignment=ft.alignment.center, bgcolor=Colors.BACKGROUND, border=ft.border.all(1, Colors.BORDER_ALT), border_radius=10,
        )
        swatch_boxes: dict[str, ft.Container] = {}

        def update_swatch_styles():
            for hexcode, box in swatch_boxes.items():
                selected = hexcode == brand_state["color"]
                box.border = ft.border.all(3 if selected else 1, Colors.TEXT_PRIMARY if selected else Colors.BORDER_ALT)
                box.content = ft.Icon(ft.Icons.CHECK, color=Colors.WHITE, size=16) if selected else None

        def pick_color(hexcode: str):
            def handler(_):
                brand_state["color"] = hexcode
                update_swatch_styles()
                self.page.update()
            return handler

        def swatch(hexcode: str, label: str) -> ft.Container:
            box = ft.Container(
                width=34, height=34, bgcolor=hexcode, border_radius=17,
                alignment=ft.alignment.center, tooltip=label, ink=True,
                on_click=pick_color(hexcode),
            )
            swatch_boxes[hexcode] = box
            return box

        async def pick_logo(_):
            if self.native_files is None:
                self._notify("اختيار الشعار غير مهيأ في هذا البناء")
                return
            try:
                picked = await self.native_files.pick_file(extensions=["png", "jpg", "jpeg"], dialog_title="اختر شعار الشركة")
                if not picked:
                    return
                source = Path(str(picked["path"]))
                raw = await asyncio.to_thread(source.read_bytes)
                if len(raw) > 900_000:
                    self._notify("الصورة كبيرة جدًا (الحد 900 كيلوبايت) — اختر صورة أصغر")
                    return
                ext = source.suffix.lower().lstrip(".") or "png"
                mime = "image/png" if ext == "png" else "image/jpeg"
                b64 = base64.b64encode(raw).decode("ascii")
                brand_state["logo"] = f"data:{mime};base64,{b64}"
                logo_preview.content = ft.Image(src_base64=b64, fit=ft.ImageFit.CONTAIN)
                self.page.update()
            except Exception as exc:
                self._notify(str(exc), kind="error")

        def clear_logo(_):
            brand_state["logo"] = ""
            logo_preview.content = ft.Icon(ft.Icons.IMAGE_OUTLINED, color=Colors.TEXT_FAINT, size=28)
            self.page.update()

        def save_branding(_):
            try:
                rate_text = (exchange_rate_field.value or "").replace(",", "").strip()
                try:
                    rate_value = float(rate_text)
                except ValueError:
                    rate_value = 0
                if rate_value <= 0:
                    self._notify("سعر الصرف يجب أن يكون رقمًا أكبر من صفر")
                    return
                self.ctx.settings.set_many({
                    "company_name": (company_name_field.value or "نانو").strip(),
                    "currency": (currency_field.value or "USD").strip(),
                    currency.DISPLAY_CURRENCY_KEY: display_currency_field.value or currency.DEFAULT_DISPLAY_CURRENCY,
                    currency.EXCHANGE_RATE_KEY: str(rate_value),
                    currency.DISPLAY_SYMBOL_KEY: currency.DEFAULT_DISPLAY_SYMBOL,
                    currency.USD_DISPLAY_SYMBOL_KEY: currency.DEFAULT_USD_DISPLAY_SYMBOL,
                    "invoice_color": brand_state["color"],
                    "company_logo": brand_state["logo"] or None,
                })
                exchange_rate_field.value = str(rate_value)
                self._notify("تم حفظ هوية الشركة وإعدادات العملة — ستظهر في كل الشاشات والمستندات فورًا")
                self.page.update()
            except Exception as exc:
                self._notify(str(exc), kind="error")

        update_swatch_styles()

        # --- Barcode/QR system: generation defaults, validation strictness,
        # printed-label layout, and POS scan feedback -- all admin-tunable
        # and read via core.barcode_settings everywhere else in the app
        # (item editor, label printing, POS scanning), so a change here
        # takes effect immediately with no restart.
        bset = self.ctx.settings

        barcode_kind_field = SegmentedToggle(
            options=[SegmentOption(k, v) for k, v in barcode_settings.KIND_LABELS.items()],
            value=barcode_settings.default_kind(bset),
        )
        barcode_prefix_field = SelectAllTextField(
            label="بادئة داخلية لأكواد EAN-13 المولّدة (اختياري)",
            value=barcode_settings.internal_prefix(bset),
            hint_text="مثال: 20 — الأرقام 20-29 محجوزة عادة للاستخدام الداخلي",
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        barcode_auto_generate_switch = ft.Switch(
            label="توليد باركود تلقائيًا عند حفظ مادة بلا باركود",
            value=barcode_settings.auto_generate_enabled(bset),
        )
        barcode_similar_switch = ft.Switch(
            label="تنبيه عند تشابه الباركود مع مادة أخرى",
            value=barcode_settings.similar_warning_enabled(bset),
        )
        barcode_checksum_switch = ft.Switch(
            label="تنبيه عند خطأ رقم التحقق (checksum) لأكواد EAN/UPC",
            value=barcode_settings.checksum_warning_enabled(bset),
        )
        barcode_layout_field = SegmentedToggle(
            options=[SegmentOption(k, v) for k, v in barcode_settings.LABEL_LAYOUT_LABELS.items()],
            value=barcode_settings.label_layout(bset),
        )
        barcode_roll_width_field = SegmentedToggle(
            options=[SegmentOption(k, v) for k, v in barcode_settings.LABEL_ROLL_WIDTH_LABELS.items()],
            value=barcode_settings.label_roll_width(bset),
        )
        barcode_columns_field = SegmentedToggle(
            options=[SegmentOption(str(n), f"{n} أعمدة") for n in barcode_settings.VALID_LABEL_COLUMNS],
            value=str(barcode_settings.label_columns(bset)),
        )
        barcode_size_field = SegmentedToggle(
            options=[SegmentOption(k, v) for k, v in barcode_settings.LABEL_SIZE_LABELS.items()],
            value=barcode_settings.label_size(bset),
        )
        # Sheet-only controls (columns/size) hide when the roll profile is
        # selected -- a thermal roll is always one continuous strip, so
        # "columns" and a fixed sticker size don't apply to it.
        barcode_sheet_only_box = ft.Column(
            [
                ft.Text("عدد الأعمدة", size=11, color=Colors.TEXT_SECONDARY),
                barcode_columns_field,
                ft.Text("حجم الملصق", size=11, color=Colors.TEXT_SECONDARY),
                barcode_size_field,
            ],
            spacing=8, visible=barcode_layout_field.value == "sheet",
        )
        barcode_roll_only_box = ft.Column(
            [
                ft.Text("عرض اللفة", size=11, color=Colors.TEXT_SECONDARY),
                barcode_roll_width_field,
            ],
            spacing=8, visible=barcode_layout_field.value == "roll",
        )

        def on_barcode_layout_change(_=None) -> None:
            barcode_sheet_only_box.visible = barcode_layout_field.value == "sheet"
            barcode_roll_only_box.visible = barcode_layout_field.value == "roll"
            barcode_sheet_only_box.update()
            barcode_roll_only_box.update()

        barcode_layout_field.on_change = on_barcode_layout_change
        barcode_show_text_switch = ft.Switch(
            label="إظهار الرقم أسفل شريط الباركود",
            value=barcode_settings.label_show_text(bset),
        )
        barcode_price_qr_switch = ft.Switch(
            label="تفعيل رمز QR للسعر افتراضيًا عند الطباعة",
            value=barcode_settings.label_price_qr_default(bset),
        )
        barcode_scan_feedback_field = SegmentedToggle(
            options=[SegmentOption(k, v) for k, v in barcode_settings.SCAN_FEEDBACK_LABELS.items()],
            value=barcode_settings.scan_feedback_mode(bset),
        )

        barcode_preview = ft.Container(
            padding=10, bgcolor=Colors.BACKGROUND, border=ft.border.all(1, Colors.BORDER_ALT), border_radius=10,
            alignment=ft.alignment.center,
        )

        def _bars_preview(data: str, width: int, height: int, show_text: bool) -> ft.Control:
            # Rendered with plain Flet Container "rects" (not the SVG string
            # from core.barcode128, which is print-HTML output only) --
            # Flet's Image control has no built-in SVG renderer, so this
            # redraws the same bar-width table as thin colored bars for an
            # honest live in-app preview.
            bars = code128b_bars(data)
            total_units = sum(w for w, _ in bars) or 1
            unit = width / total_units
            text_h = 14 if show_text else 0
            bar_h = height - text_h
            bar_controls = []
            for w, is_bar in bars:
                px_w = max(0.4, w * unit)
                bar_controls.append(
                    ft.Container(width=px_w, height=bar_h, bgcolor="#0F172A" if is_bar else "transparent")
                )
            column_children: list[ft.Control] = [ft.Row(bar_controls, spacing=0, tight=True)]
            if show_text:
                column_children.append(ft.Text(data, size=10, font_family="monospace", color=Colors.TEXT_PRIMARY))
            return ft.Container(
                ft.Column(column_children, spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
                width=width, bgcolor=Colors.WHITE, padding=4,
            )

        def refresh_barcode_preview() -> None:
            width, height = barcode_settings.LABEL_SIZE_DIMENSIONS.get(barcode_size_field.value or "medium", (210, 54))
            sample = barcode_quality.generate_barcode_value(
                barcode_kind_field.value or "EAN13",
                prefix=(barcode_prefix_field.value or "") if barcode_kind_field.value == "EAN13" else None,
            )
            if barcode_kind_field.value == "QR":
                barcode_preview.content = ft.Column(
                    [ft.Icon(ft.Icons.QR_CODE_2, size=48, color=Colors.TEXT_SECONDARY), ft.Text(sample, size=11, color=Colors.TEXT_SECONDARY)],
                    spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True,
                )
            else:
                barcode_preview.content = _bars_preview(sample, width, height, bool(barcode_show_text_switch.value))
            if barcode_preview.page is not None:
                barcode_preview.update()

        def barcode_control_changed(_=None) -> None:
            refresh_barcode_preview()
            self.page.update()

        barcode_kind_field.on_change = barcode_control_changed
        barcode_prefix_field.on_change = barcode_control_changed
        barcode_size_field.on_change = barcode_control_changed
        barcode_show_text_switch.on_change = barcode_control_changed
        refresh_barcode_preview()

        def save_barcode_settings(_):
            try:
                self.ctx.settings.set_many({
                    barcode_settings.KIND_KEY: barcode_kind_field.value or barcode_settings.DEFAULT_KIND,
                    barcode_settings.PREFIX_KEY: (barcode_prefix_field.value or "").strip(),
                    barcode_settings.AUTO_GENERATE_KEY: "1" if barcode_auto_generate_switch.value else "0",
                    barcode_settings.SIMILAR_WARNING_KEY: "1" if barcode_similar_switch.value else "0",
                    barcode_settings.CHECKSUM_WARNING_KEY: "1" if barcode_checksum_switch.value else "0",
                    barcode_settings.LABEL_LAYOUT_KEY: barcode_layout_field.value or barcode_settings.DEFAULT_LABEL_LAYOUT,
                    barcode_settings.LABEL_ROLL_WIDTH_KEY: barcode_roll_width_field.value or barcode_settings.DEFAULT_LABEL_ROLL_WIDTH,
                    barcode_settings.LABEL_COLUMNS_KEY: barcode_columns_field.value or str(barcode_settings.DEFAULT_LABEL_COLUMNS),
                    barcode_settings.LABEL_SIZE_KEY: barcode_size_field.value or barcode_settings.DEFAULT_LABEL_SIZE,
                    barcode_settings.LABEL_SHOW_TEXT_KEY: "1" if barcode_show_text_switch.value else "0",
                    barcode_settings.LABEL_PRICE_QR_KEY: "1" if barcode_price_qr_switch.value else "0",
                    barcode_settings.SCAN_FEEDBACK_KEY: barcode_scan_feedback_field.value or barcode_settings.DEFAULT_SCAN_FEEDBACK,
                })
                self._notify("تم حفظ إعدادات الباركود — تُطبَّق فورًا في المواد ونقطة البيع والطباعة")
                self.page.update()
            except Exception as exc:
                self._notify(str(exc), kind="error")

        # --- Invoice document system: numbering display, due-date/overdue
        # tracking, printed footer terms, and sign/verify boxes -- all
        # admin-tunable and read via core.invoice_settings everywhere else
        # (invoice list, invoice print/PDF), so a change here applies
        # immediately and retroactively without touching stored invoices.
        iset = self.ctx.settings

        invoice_prefix_field = SelectAllTextField(
            label="بادئة رقم الفاتورة المعروض (اختياري)",
            value=invoice_settings.number_prefix(iset),
            hint_text="مثال: INV- — لا يغيّر الرقم الداخلي أو الباركود، فقط العرض والطباعة",
        )
        invoice_padding_labels = {0: "بدون", 4: "4 أرقام", 5: "5 أرقام", 6: "6 أرقام"}
        invoice_padding_field = SegmentedToggle(
            options=[SegmentOption(str(n), invoice_padding_labels[n]) for n in invoice_settings.VALID_NUMBER_PADDING],
            value=str(invoice_settings.number_padding(iset)),
        )
        invoice_due_days_field = SelectAllTextField(
            label="مهلة الاستحقاق الافتراضية (أيام)",
            value=str(invoice_settings.default_due_days(iset)),
            hint_text="0 = بلا تاريخ استحقاق مطبوع (فواتير نقدية)",
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        invoice_overdue_days_field = SelectAllTextField(
            label="عدد الأيام لاعتبار الفاتورة متأخرة السداد",
            value=str(invoice_settings.overdue_days(iset)),
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        invoice_footer_field = SelectAllTextField(
            label="نص ثابت أسفل كل فاتورة مطبوعة (شروط، ملاحظة، ...)",
            value=invoice_settings.footer_text(iset),
            multiline=True,
            min_lines=2,
            max_lines=4,
        )
        invoice_sign_boxes_switch = ft.Switch(
            label="إظهار مربعي \"توقيع المستلم\" و\"ختم الشركة\" عند الطباعة",
            value=invoice_settings.show_sign_boxes(iset),
        )
        invoice_verify_qr_switch = ft.Switch(
            label="إظهار رمز التحقق (QR) من صحة الفاتورة عند الطباعة",
            value=invoice_settings.show_verify_qr(iset),
        )

        def save_invoice_settings(_):
            try:
                try:
                    due_days = max(0, int((invoice_due_days_field.value or "0").strip()))
                except ValueError:
                    due_days = invoice_settings.DEFAULT_DUE_DAYS
                try:
                    overdue_after = int((invoice_overdue_days_field.value or "").strip())
                    if overdue_after <= 0:
                        overdue_after = invoice_settings.DEFAULT_OVERDUE_DAYS
                except ValueError:
                    overdue_after = invoice_settings.DEFAULT_OVERDUE_DAYS
                self.ctx.settings.set_many({
                    invoice_settings.NUMBER_PREFIX_KEY: (invoice_prefix_field.value or "").strip(),
                    invoice_settings.NUMBER_PADDING_KEY: invoice_padding_field.value or str(invoice_settings.DEFAULT_NUMBER_PADDING),
                    invoice_settings.DEFAULT_DUE_DAYS_KEY: str(due_days),
                    invoice_settings.OVERDUE_DAYS_KEY: str(overdue_after),
                    invoice_settings.FOOTER_TEXT_KEY: (invoice_footer_field.value or "").strip(),
                    invoice_settings.SHOW_SIGN_BOXES_KEY: "1" if invoice_sign_boxes_switch.value else "0",
                    invoice_settings.SHOW_VERIFY_QR_KEY: "1" if invoice_verify_qr_switch.value else "0",
                })
                invoice_due_days_field.value = str(due_days)
                invoice_overdue_days_field.value = str(overdue_after)
                self._notify("تم حفظ إعدادات الفواتير — تُطبَّق فورًا في القائمة والطباعة")
                self.page.update()
            except Exception as exc:
                self._notify(str(exc), kind="error")

        # --- Point of sale: payment-sheet defaults and quick-cash button
        # count -- admin-tunable and read via core.pos_settings each time
        # the POS screen builds its payment sheet, so a change here applies
        # the next time any cashier opens POS (no restart needed).
        pset = self.ctx.settings

        pos_auto_print_switch = ft.Switch(
            label="تشغيل \"طباعة تلقائية بعد الدفع\" افتراضيًا في كل عملية بيع",
            value=pos_settings.auto_print_default(pset),
        )
        pos_quick_cash_field = SegmentedToggle(
            options=[SegmentOption(str(n), f"{n} أزرار") for n in pos_settings.VALID_QUICK_CASH_COUNT],
            value=str(pos_settings.quick_cash_count(pset)),
        )

        def save_pos_settings(_):
            try:
                self.ctx.settings.set_many({
                    pos_settings.AUTO_PRINT_DEFAULT_KEY: "1" if pos_auto_print_switch.value else "0",
                    pos_settings.QUICK_CASH_COUNT_KEY: pos_quick_cash_field.value or str(pos_settings.DEFAULT_QUICK_CASH_COUNT),
                })
                self._notify("تم حفظ إعدادات نقطة البيع — تُطبَّق في المرة القادمة لفتح نقطة البيع")
                self.page.update()
            except Exception as exc:
                self._notify(str(exc), kind="error")

        # --- Stocktake: continuous-scan cooldown and sound feedback --
        # admin-tunable and read via core.barcode_settings each time the
        # stocktake screen's scan loop runs, so a change here applies the
        # next time anyone opens "جرد بالمسح المستمر" (no restart needed).
        stkset = self.ctx.settings
        STOCKTAKE_COOLDOWN_CHOICES = [500, 800, 1200, 2000, 3000]

        stocktake_cooldown_field = SegmentedToggle(
            options=[SegmentOption(str(n), f"{n} مل.ث") for n in STOCKTAKE_COOLDOWN_CHOICES],
            value=str(barcode_settings.stocktake_cooldown_ms(stkset)),
        )
        stocktake_sound_switch = ft.Switch(
            label="تنبيه صوتي عند كل مسح ناجح",
            value=barcode_settings.stocktake_sound_enabled(stkset),
        )

        def save_stocktake_settings(_):
            try:
                self.ctx.settings.set_many({
                    barcode_settings.STOCKTAKE_COOLDOWN_KEY: (
                        stocktake_cooldown_field.value or str(barcode_settings.DEFAULT_STOCKTAKE_COOLDOWN_MS)
                    ),
                    barcode_settings.STOCKTAKE_SOUND_KEY: "1" if stocktake_sound_switch.value else "0",
                })
                self._notify("تم حفظ إعدادات الجرد — تُطبَّق في المرة القادمة لفتح شاشة الجرد")
                self.page.update()
            except Exception as exc:
                self._notify(str(exc), kind="error")

        # --- App-wide sound system: master switch, volume, and per-category
        # (success/error/warning/info) toggles -- admin-tunable and read via
        # core.sound_settings from core/sound.py, which is hooked into the
        # single toast() choke point every notify() in the app already goes
        # through. A change here applies to the very next toast, anywhere in
        # the app, with no restart needed.
        sset = self.ctx.settings

        sound_enabled_switch = ft.Switch(
            label="تفعيل النظام الصوتي",
            value=sound_settings.sound_enabled(sset),
        )
        sound_volume_field = ft.Slider(
            min=0, max=100, divisions=10, round=0,
            value=sound_settings.sound_volume_percent(sset),
            label="{value}%",
        )
        sound_kind_success_switch = ft.Switch(
            label="صوت عند النجاح (حفظ، إتمام عملية، مسح ناجح...)",
            value=sound_settings.kind_enabled(sset, "success"),
        )
        sound_kind_error_switch = ft.Switch(
            label="صوت عند الخطأ (فشل عملية، تحقق مرفوض...)",
            value=sound_settings.kind_enabled(sset, "error"),
        )
        sound_kind_warning_switch = ft.Switch(
            label="صوت عند التنبيه (حقل ناقص، تأكيد مطلوب...)",
            value=sound_settings.kind_enabled(sset, "warning"),
        )
        sound_kind_info_switch = ft.Switch(
            label="صوت عند الإشعارات العادية",
            value=sound_settings.kind_enabled(sset, "info"),
        )
        sound_kind_scan_switch = ft.Switch(
            label="صوت عند مسح الباركود (نغمة مخصصة سريعة)",
            value=sound_settings.kind_enabled(sset, "scan"),
        )
        sound_kind_save_switch = ft.Switch(
            label="صوت عند حفظ فاتورة أو دفعة (نغمة مخصصة)",
            value=sound_settings.kind_enabled(sset, "save"),
        )
        sound_kind_delete_switch = ft.Switch(
            label="صوت عند حذف فاتورة/مادة/طرف (نغمة مخصصة منخفضة)",
            value=sound_settings.kind_enabled(sset, "delete"),
        )
        sound_kind_login_switch = ft.Switch(
            label="صوت عند تسجيل الدخول (نغمة ترحيب)",
            value=sound_settings.kind_enabled(sset, "login"),
        )
        sound_kind_notify_switch = ft.Switch(
            label="صوت عند وصول تنبيه جديد لمركز الإشعارات",
            value=sound_settings.kind_enabled(sset, "notify"),
        )
        sound_kind_barcode_error_switch = ft.Switch(
            label="صوت عند مسح باركود غير موجود (نغمة مختلفة عن الخطأ العام)",
            value=sound_settings.kind_enabled(sset, "barcode_error"),
        )

        def preview_sound(kind: str):
            # Plays directly at whatever the volume slider is set to right
            # now, bypassing the enabled/kind switches entirely -- so an
            # admin can audition a tone while adjusting it, even before
            # saving or if that kind is currently switched off. See
            # sound.play_preview()'s docstring.
            def _handler(_=None):
                sound_engine.play_preview(self.page, kind, int(sound_volume_field.value))
            return _handler

        def save_sound_settings(_):
            try:
                self.ctx.settings.set_many({
                    sound_settings.ENABLED_KEY: "1" if sound_enabled_switch.value else "0",
                    sound_settings.VOLUME_KEY: str(int(sound_volume_field.value)),
                    sound_settings.KIND_SUCCESS_KEY: "1" if sound_kind_success_switch.value else "0",
                    sound_settings.KIND_ERROR_KEY: "1" if sound_kind_error_switch.value else "0",
                    sound_settings.KIND_WARNING_KEY: "1" if sound_kind_warning_switch.value else "0",
                    sound_settings.KIND_INFO_KEY: "1" if sound_kind_info_switch.value else "0",
                    sound_settings.KIND_SCAN_KEY: "1" if sound_kind_scan_switch.value else "0",
                    sound_settings.KIND_SAVE_KEY: "1" if sound_kind_save_switch.value else "0",
                    sound_settings.KIND_DELETE_KEY: "1" if sound_kind_delete_switch.value else "0",
                    sound_settings.KIND_LOGIN_KEY: "1" if sound_kind_login_switch.value else "0",
                    sound_settings.KIND_NOTIFY_KEY: "1" if sound_kind_notify_switch.value else "0",
                    sound_settings.KIND_BARCODE_ERROR_KEY: "1" if sound_kind_barcode_error_switch.value else "0",
                })
                self._notify("تم حفظ إعدادات الصوت — تُطبَّق فورًا في كل أنحاء التطبيق")
                self.page.update()
            except Exception as exc:
                self._notify(str(exc), kind="error")

        # --- Sound diagnostics panel -------------------------------------
        # Walks the exact same failure points listed in core/sound.py's
        # play() (settings gate, missing native bridge) plus what only the
        # native side can see (asset load / playback-start errors per
        # tone, captured by sound_pool.dart's diagnoseSoundPools) -- so an
        # admin stuck on "the sound just doesn't play" gets a concrete
        # reason instead of having to pull adb logcat themselves.
        _KIND_LABELS_AR = {
            "success": "نجاح", "error": "خطأ", "warning": "تنبيه", "info": "عادي",
            "scan": "مسح باركود", "save": "حفظ فاتورة/دفعة", "delete": "حذف",
            "login": "تسجيل دخول", "notify": "تنبيه جديد بمركز الإشعارات", "barcode_error": "باركود غير موجود",
        }

        def _diag_row(ok: bool | None, text: str) -> ft.Row:
            # ok=None -> neutral/info line (grey dot), not a pass/fail check.
            icon = ft.Icons.CHECK_CIRCLE if ok else (ft.Icons.CANCEL if ok is False else ft.Icons.CIRCLE)
            color = Colors.SUCCESS if ok else (Colors.DANGER if ok is False else Colors.TEXT_SECONDARY)
            return ft.Row(
                [ft.Icon(icon, color=color, size=16), ft.Text(text, size=12, expand=True, selectable=True)],
                vertical_alignment=ft.CrossAxisAlignment.START, spacing=8,
            )

        async def build_diagnosis(retry: bool) -> list[ft.Control]:
            rows: list[ft.Control] = []
            sset_now = self.ctx.settings
            enabled = sound_settings.sound_enabled(sset_now)
            volume_pct = sound_settings.sound_volume_percent(sset_now)
            rows.append(_diag_row(enabled, "المفتاح الرئيسي للنظام الصوتي: " + ("مفعّل" if enabled else "مُعطَّل — لن يُشغَّل أي صوت تلقائي حتى لو كان الجهاز سليمًا")))
            rows.append(_diag_row(volume_pct > 0, f"مستوى الصوت في الإعدادات: {volume_pct}%" + ("" if volume_pct > 0 else " — صفر يعني صمت حتى مع كل شيء آخر سليم")))
            for kind, label in _KIND_LABELS_AR.items():
                k_on = sound_settings.kind_enabled(sset_now, kind)
                rows.append(_diag_row(k_on, f"نوع «{label}»: " + ("مفعّل" if k_on else "مُعطَّل من إعدادات هذا التبويب")))

            if self.native_files is None:
                rows.append(_diag_row(False, "جسر التشغيل الأصلي (native bridge) غير متاح في هذا البناء — النسخة قد تكون بُنيت قبل إضافة نظام الأصوات."))
                return rows

            diag = await self.native_files.diagnose_sound(retry=retry)
            if not diag or diag.get("bridge_error") is not None:
                rows.append(_diag_row(False, "تعذّر الوصول لجسر التشغيل الأصلي: " + str((diag or {}).get("bridge_error") or "لا استجابة — قد تكون تُجرّب نسخة APK قديمة لا تحتوي هذه الميزة بعد.")))
                return rows

            rows.append(_diag_row(True, f"جسر التشغيل الأصلي متصل (المنصّة: {diag.get('platform', '?')})."))
            kinds = diag.get("kinds") or {}
            for kind, label in _KIND_LABELS_AR.items():
                info = kinds.get(kind) or {}
                loaded = info.get("loaded")
                if not loaded:
                    rows.append(_diag_row(False, f"صوت «{label}» ({info.get('asset', '?')}): فشل التحميل — {info.get('load_error') or 'سبب غير معروف'}"))
                    continue
                play_err = info.get("play_error")
                if play_err:
                    rows.append(_diag_row(False, f"صوت «{label}»: تحمّل بنجاح لكن فشل التشغيل الفعلي — {play_err}"))
                else:
                    rows.append(_diag_row(True, f"صوت «{label}»: محمّل وجاهز، واختبار تشغيل صامت نجح."))
            return rows

        async def refresh_diagnosis(body: ft.Column, retry: bool):
            body.controls = [ft.Row([ft.ProgressRing(width=16, height=16), ft.Text("يفحص الآن...", size=12)])]
            self.page.update()
            try:
                rows = await build_diagnosis(retry)
            except Exception as exc:
                rows = [_diag_row(False, f"تعذّر إتمام الفحص: {exc!r}")]
            body.controls = rows
            self.page.update()

        async def open_sound_diagnosis(_):
            body = ft.Column(spacing=10, tight=True, scroll=ft.ScrollMode.AUTO)
            diag_dialog = ft.AlertDialog(
                title=ft.Text("تشخيص النظام الصوتي"),
                content=ft.Container(body, width=380, height=360),
                actions=[
                    # Re-fills the same dialog's body rather than opening a
                    # second AlertDialog on top -- see the "never open a
                    # second AlertDialog" note elsewhere in this file.
                    ft.TextButton("إعادة الفحص", on_click=lambda e: self.page.run_task(refresh_diagnosis, body, True)),
                    ft.FilledButton("حسنًا", on_click=lambda e: self.page.close(diag_dialog)),
                ],
            )
            self.page.open(diag_dialog)
            await refresh_diagnosis(body, False)

        # --- Backups: automatic creation on login when overdue, and local
        # retention pruning -- admin-tunable and read via core.backup_settings
        # (auto-check happens once per login in main.py; retention pruning
        # happens right after every backup, manual or automatic).
        bkset = self.ctx.settings

        backup_auto_switch = ft.Switch(
            label="إنشاء نسخة احتياطية تلقائيًا عند تسجيل الدخول إذا تجاوزت الموعد المحدد في إعدادات الإشعارات",
            value=backup_settings.auto_backup_enabled(bkset),
        )
        backup_retention_field = SegmentedToggle(
            options=[
                SegmentOption(str(n), "بلا حد" if n == 0 else f"آخر {n}")
                for n in backup_settings.VALID_RETENTION_COUNTS
            ],
            value=str(backup_settings.retention_count(bkset)),
        )

        def save_backup_settings(_):
            try:
                self.ctx.settings.set_many({
                    backup_settings.AUTO_BACKUP_ENABLED_KEY: "1" if backup_auto_switch.value else "0",
                    backup_settings.RETENTION_COUNT_KEY: backup_retention_field.value or str(backup_settings.DEFAULT_RETENTION_COUNT),
                })
                self._notify("تم حفظ إعدادات النسخ الاحتياطي")
                self.page.update()
            except Exception as exc:
                self._notify(str(exc), kind="error")

        # --- Reports center: which report and date range are pre-selected
        # the moment it opens -- admin-tunable and read via
        # core.reporting_settings each time ReportsCenter.show_center()
        # builds its filter row.
        rset = self.ctx.settings

        reports_default_type_field = SegmentedToggle(
            options=[SegmentOption(k, v) for k, v in reporting_settings.REPORT_TYPE_LABELS.items()],
            value=reporting_settings.default_report(rset),
        )
        reports_default_range_field = SegmentedToggle(
            options=[SegmentOption(k, v) for k, v in reporting_settings.RANGE_LABELS.items()],
            value=reporting_settings.default_range(rset),
        )

        def save_reporting_settings(_):
            try:
                self.ctx.settings.set_many({
                    reporting_settings.DEFAULT_REPORT_KEY: reports_default_type_field.value or reporting_settings.DEFAULT_REPORT_TYPE,
                    reporting_settings.DEFAULT_RANGE_KEY: reports_default_range_field.value or reporting_settings.DEFAULT_RANGE,
                })
                self._notify("تم حفظ إعدادات التقارير — تُطبَّق في المرة القادمة لفتح مركز التقارير")
                self.page.update()
            except Exception as exc:
                self._notify(str(exc), kind="error")

        audit_list = ft.Column(spacing=6)
        audit_filter = {"entity": "all", "query": ""}
        audit_search = SelectAllTextField(
            label="بحث في السجل",
            hint_text="إجراء، نوع، مستخدم، تفاصيل…",
            prefix_icon=ft.Icons.SEARCH,
        )
        audit_entity_dd = ft.Dropdown(
            label="النوع",
            value="all",
            options=[
                ft.dropdown.Option("all", "الكل"),
                ft.dropdown.Option("item", "مواد"),
                ft.dropdown.Option("user", "مستخدمون"),
                ft.dropdown.Option("customer", "عملاء"),
                ft.dropdown.Option("supplier", "موردون"),
                ft.dropdown.Option("invoice", "فواتير"),
                ft.dropdown.Option("payment", "دفعات"),
                ft.dropdown.Option("voucher", "سندات"),
                ft.dropdown.Option("expense", "مصروفات"),
                ft.dropdown.Option("settings", "إعدادات"),
            ],
            filled=True,
            bgcolor=Colors.BACKGROUND_ALT,
            width=160,
        )
        audit_count_label = ft.Text("", size=11, color=Colors.TEXT_FAINT)

        _ACTION_AR = {
            "create": "إنشاء",
            "update": "تعديل",
            "delete": "حذف",
            "password_reset": "إعادة تعيين كلمة المرور",
            "login": "تسجيل دخول",
            "logout": "تسجيل خروج",
            "restore": "استعادة نسخة",
            "backup": "نسخة احتياطية",
            "day_close": "إغلاق يوم الصندوق",
        }
        _ENTITY_AR = {
            "item": "مادة",
            "user": "مستخدم",
            "customer": "عميل",
            "supplier": "مورد",
            "invoice": "فاتورة",
            "payment": "دفعة",
            "voucher": "سند",
            "expense": "مصروف",
            "settings": "إعدادات",
            "stocktake": "جرد",
            "cash": "صندوق",
        }
        _ACTION_COLOR = {
            "create": Colors.SUCCESS,
            "update": Colors.PRIMARY,
            "delete": Colors.DANGER,
            "password_reset": Colors.WARNING_DARK,
            "login": Colors.PURPLE_LIGHT,
            "logout": Colors.TEXT_SECONDARY,
        }

        def _audit_action_label(action: str) -> str:
            return _ACTION_AR.get(str(action or ""), str(action or "—"))

        def _audit_entity_label(entity: str) -> str:
            return _ENTITY_AR.get(str(entity or ""), str(entity or "—"))

        def refresh_audit(_=None):
            audit_list.controls = []
            try:
                rows = self.ctx.auth.audit_entries(300)
            except Exception as exc:
                audit_list.controls.append(ft.Text(str(exc), color=Colors.DANGER))
                audit_count_label.value = ""
                self.page.update()
                return
            q = (audit_search.value or "").strip().casefold()
            ent = audit_entity_dd.value or "all"
            shown = 0
            for row in rows:
                entity = str(row.get("entity_type") or "")
                if ent != "all" and entity != ent:
                    continue
                action = str(row.get("action") or "")
                actor = row.get("username") or "النظام"
                details = str(row.get("details") or "")
                hay = " ".join([action, entity, actor, details, str(row.get("entity_id") or "")]).casefold()
                if q and q not in hay:
                    continue
                accent = _ACTION_COLOR.get(action, Colors.TEXT_SECONDARY)
                title = f"{_audit_action_label(action)} • {_audit_entity_label(entity)}"
                if row.get("entity_id") not in (None, ""):
                    title += f" #{row.get('entity_id')}"
                audit_list.controls.append(
                    ft.Container(
                        ft.Row(
                            [
                                ft.Container(width=4, height=42, bgcolor=accent, border_radius=4),
                                ft.Column(
                                    [
                                        ft.Row(
                                            [
                                                ft.Text(title, weight=ft.FontWeight.BOLD, size=13, expand=True),
                                                ft.Text(str(row.get("created_at") or ""), size=10, color=Colors.TEXT_FAINT),
                                            ],
                                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        ),
                                        ft.Text(
                                            f"{actor}" + (f" — {details}" if details else ""),
                                            size=11,
                                            color=Colors.TEXT_SECONDARY,
                                        ),
                                    ],
                                    spacing=3,
                                    expand=True,
                                ),
                            ],
                            spacing=10,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=10,
                        bgcolor=Colors.BACKGROUND,
                        border=ft.border.all(1, Colors.BORDER),
                        border_radius=12,
                    )
                )
                shown += 1
            if shown == 0:
                audit_list.controls.append(
                    ft.Container(
                        ft.Text("لا توجد أحداث مطابقة", size=12, color=Colors.TEXT_FAINT),
                        padding=16,
                    )
                )
            audit_count_label.value = f"عرض {shown} من أصل {len(rows)}"
            self.page.update()

        audit_search.on_change = refresh_audit
        audit_entity_dd.on_change = refresh_audit
        refresh_audit()

        # --- Modern layout: one focused section at a time behind a
        # scrollable pill tab bar, instead of 5 cards permanently expanded
        # and stacked (the old layout, which meant constant scrolling just
        # to reach "سجل التدقيق"). A slim status strip up top gives an
        # at-a-glance read (users/license/backup/company) without opening
        # anything. None of the section content, handlers, or variables
        # above this point changed -- only how they're arranged and shown.
        all_users_now = self.ctx.auth.list_users()
        active_users_count = sum(1 for u in all_users_now if u["is_active"])
        total_users_count = len(all_users_now)
        license_status_now = self.ctx.license.status()
        backup_files_now = sorted(
            list(backups_dir.glob("*.nanobackup")) + list(backups_dir.glob("*.qeidbackup")), reverse=True
        )
        last_backup_label = backup_files_now[0].name if backup_files_now else "لا توجد بعد"
        if len(last_backup_label) > 22:
            last_backup_label = last_backup_label[:20] + "…"

        def _stat_chip(icon: str, label: str, value: str, value_color: str = Colors.TEXT_PRIMARY) -> ft.Container:
            return ft.Container(
                ft.Row(
                    [
                        ft.Icon(icon, size=16, color=Colors.TEXT_SECONDARY),
                        ft.Column(
                            [
                                ft.Text(label, size=10, color=Colors.TEXT_FAINT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text(value, size=13, weight=ft.FontWeight.BOLD, color=value_color, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                            ],
                            spacing=0,
                            tight=True,
                            # Bounds the label/value so a long value (a backup
                            # filename, a long company name) truncates with an
                            # ellipsis instead of spilling out past the chip's
                            # rounded border once it's wider than the pill.
                            width=128,
                        ),
                    ],
                    spacing=8,
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.symmetric(horizontal=12, vertical=9),
                bgcolor=Colors.WHITE,
                border=ft.border.all(1, Colors.BORDER_ALT),
                border_radius=12,
            )

        status_strip = ft.Row(
            [
                _stat_chip(ft.Icons.PEOPLE_ALT_OUTLINED, "المستخدمون النشطون", f"{active_users_count}/{total_users_count}"),
                _stat_chip(
                    ft.Icons.VERIFIED_USER_OUTLINED,
                    "الترخيص",
                    "مفعل" if license_status_now.valid else "غير مفعل",
                    Colors.SUCCESS_DARK if license_status_now.valid else Colors.DANGER_DARKER,
                ),
                _stat_chip(ft.Icons.BACKUP_OUTLINED, "آخر نسخة احتياطية", last_backup_label),
                _stat_chip(ft.Icons.STOREFRONT_OUTLINED, "الشركة", company_name_field.value or "نانو"),
                # Trailing spacer: without it the last chip sits flush
                # against the scroll viewport's edge with zero breathing
                # room, which -- combined with no fade/shadow cue -- reads
                # as the row being cut off rather than intentionally
                # scrollable.
                ft.Container(width=8),
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        )

        # --- Appearance / night mode ------------------------------------#
        # Two independent knobs (see core/theme_settings.py):
        #   1. mode: فاتح / داكن / تلقائي حسب النظام
        #   2. an optional smart schedule that forces dark mode between two
        #      hours regardless of (1) -- the "modern" touch on top of a
        #      plain toggle, since it activates on its own on a timer.
        # Saving rebuilds the whole app shell immediately via
        # ``on_theme_changed`` so the new palette is visible without a
        # restart, the same "tear down and rebuild everything" pattern
        # already used elsewhere in this app after a backup restore.
        theme_mode_toggle = SegmentedToggle(
            options=[
                SegmentOption(theme_settings.MODE_LIGHT, theme_settings.MODE_LABELS[theme_settings.MODE_LIGHT], ft.Icons.LIGHT_MODE_OUTLINED),
                SegmentOption(theme_settings.MODE_DARK, theme_settings.MODE_LABELS[theme_settings.MODE_DARK], ft.Icons.DARK_MODE_OUTLINED),
                SegmentOption(theme_settings.MODE_SYSTEM, theme_settings.MODE_LABELS[theme_settings.MODE_SYSTEM], ft.Icons.BRIGHTNESS_AUTO_OUTLINED),
            ],
            value=theme_settings.get_mode_preference(sset),
        )

        _hour_choices = [(f"{h:02d}", f"{h:02d}:00") for h in range(24)]
        _sched_start, _sched_end = theme_settings.schedule_hours(sset)

        theme_schedule_switch = ft.Switch(
            label="تفعيل الوضع الليلي تلقائيًا حسب الوقت",
            value=theme_settings.schedule_enabled(sset),
        )
        theme_schedule_start_field = SearchSelect(
            label="من الساعة", value=f"{_sched_start:02d}", choices=_hour_choices, allow_clear=False,
        )
        theme_schedule_end_field = SearchSelect(
            label="إلى الساعة", value=f"{_sched_end:02d}", choices=_hour_choices, allow_clear=False,
        )
        theme_schedule_row = ft.Row(
            [theme_schedule_start_field, theme_schedule_end_field], spacing=10,
        )

        def _sync_schedule_row_visibility(_=None):
            theme_schedule_row.visible = bool(theme_schedule_switch.value)
            self.page.update()

        theme_schedule_switch.on_change = _sync_schedule_row_visibility
        theme_schedule_row.visible = theme_schedule_switch.value

        def save_theme_settings(_):
            theme_settings.set_mode_preference(sset, theme_mode_toggle.value)
            theme_settings.set_schedule(
                sset,
                enabled=bool(theme_schedule_switch.value),
                start_hour=int(theme_schedule_start_field.value or theme_settings.DEFAULT_SCHEDULE_START),
                end_hour=int(theme_schedule_end_field.value or theme_settings.DEFAULT_SCHEDULE_END),
            )
            self._notify("تم حفظ إعدادات المظهر", kind="success")
            self.on_theme_changed()

        section_panels: dict[str, ft.Container] = {
            "appearance": self._section(
                "المظهر والوضع الليلي",
                [
                    ft.Text(
                        "اختر مظهر التطبيق، أو اتركه يتبع النظام تلقائيًا. يمكن أيضًا "
                        "تفعيل وضع ليلي ذكي يعمل تلقائيًا خلال ساعات محددة من اليوم "
                        "بغض النظر عن الاختيار أعلاه — مثاليًا للعمل المسائي دون إجهاد للعين.",
                        size=12, color=Colors.TEXT_SECONDARY,
                    ),
                    ft.Text("مظهر التطبيق", size=12, weight=ft.FontWeight.W_600),
                    theme_mode_toggle,
                    ft.Divider(height=1, color=Colors.BACKGROUND_ALT),
                    theme_schedule_switch,
                    theme_schedule_row,
                    ft.FilledButton("حفظ إعدادات المظهر", icon=ft.Icons.SAVE_OUTLINED, on_click=save_theme_settings),
                ],
            ),
            "users": self._section(
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
            "backup": self._section(
                "النسخ الاحتياطي والاسترجاع",
                [
                    ft.Text("النسخة تحتوي البيانات والمستخدمين، ولا تحتوي ترخيص الجهاز. يمكن مشاركتها عبر Android واستيراد ملف .nanobackup أو .qeidbackup من أي مزود مستندات. النسخة غير مشفرة؛ احفظها في مكان آمن.", size=12, color=Colors.WARNING_DARKER),
                    backup_warning_banner,
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
                    ft.Text("النسخ المحفوظة", size=13, weight=ft.FontWeight.BOLD, color=Colors.TEXT_SECONDARY),
                    backup_cards,
                    backup_info,
                    ft.Divider(height=1, color=Colors.BACKGROUND_ALT),
                    ft.Text("إعدادات النسخ الاحتياطي", size=13, weight=ft.FontWeight.BOLD, color=Colors.TEXT_SECONDARY),
                    backup_auto_switch,
                    ft.Text("الاحتفاظ بآخر عدد من النسخ محليًا (يُحذف الأقدم تلقائيًا)", size=12, color=Colors.TEXT_SECONDARY),
                    backup_retention_field,
                    ft.FilledButton("حفظ إعدادات النسخ الاحتياطي", icon=ft.Icons.SAVE_OUTLINED, on_click=save_backup_settings),
                ],
            ),
            "license": self._section(
                "التفعيل — نفس سيرفر هوى الشام",
                [
                    ft.Text("تطبيق Nano يرسل مفتاح الترخيص ومعرّف الجهاز فقط إلى سيرفر تفعيل هوى الشام. لا تُرسل الفواتير أو العملاء أو الموردون أو المخزون. بعد نجاح التفعيل يعمل التطبيق أوفلاين.", size=12, color=Colors.TEXT_MUTED),
                    ft.Row(
                        [
                            ft.Text("سيرفر التفعيل ومعرّف الجهاز (بيانات خاصة)", size=11, color=Colors.TEXT_SECONDARY),
                            license_reveal_button,
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
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
            "branding": self._section(
                "هوية الشركة والفواتير",
                [
                    ft.Text("تُطبَّق على كل الفواتير وكشوف الحساب وملصقات الباركود المطبوعة أو المُصدَّرة كـ PDF.", size=12, color=Colors.TEXT_SECONDARY),
                    ft.ResponsiveRow(
                        [
                            ft.Container(company_name_field, col={"xs": 12, "md": 6}),
                            ft.Container(currency_field, col={"xs": 12, "md": 6}),
                            ft.Container(display_currency_group, col={"xs": 12, "md": 6}),
                            ft.Container(exchange_rate_field, col={"xs": 12, "md": 6}),
                        ]
                    ),
                    ft.Text(
                        "كل الأسعار محفوظة داخليًا بالدولار دائمًا؛ اختيار \"الليرة السورية\" يعرض المبالغ مضروبة بسعر الصرف، واختيار \"الدولار الأمريكي\" يعرضها كما هي مخزَّنة دون تحويل. تغيير أي من هذين الخيارين لا يُعيد حساب أي بيانات قديمة — إنه تغيير في العرض فقط.",
                        size=11, color=Colors.TEXT_FAINT,
                    ),
                    ft.Text("شعار الشركة", size=12, weight=ft.FontWeight.W_600),
                    ft.Row(
                        [
                            logo_preview,
                            ft.Column(
                                [
                                    ft.OutlinedButton("رفع شعار", icon=ft.Icons.UPLOAD_OUTLINED, on_click=pick_logo),
                                    ft.TextButton("إزالة الشعار", icon=ft.Icons.DELETE_OUTLINE, on_click=clear_logo),
                                ],
                                spacing=2,
                            ),
                        ],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text("لون الفواتير", size=12, weight=ft.FontWeight.W_600),
                    ft.Row([swatch(h, l) for h, l in ACCENT_PALETTE], spacing=8, wrap=True),
                    ft.FilledButton("حفظ الهوية", icon=ft.Icons.SAVE_OUTLINED, on_click=save_branding),
                ],
            ),
            "audit": self._section(
                "سجل التدقيق",
                [
                    ft.Text(
                        "آخر العمليات الحساسة على البيانات والمستخدمين — مفيد لمعرفة من عدّل أو حذف وماذا.",
                        size=12,
                        color=Colors.TEXT_SECONDARY,
                    ),
                    ft.Row(
                        [
                            ft.Container(audit_search, expand=True),
                            audit_entity_dd,
                            ft.OutlinedButton("تحديث", icon=ft.Icons.REFRESH, on_click=refresh_audit),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    audit_count_label,
                    audit_list,
                ],
            ),
            "barcode": self._section(
                "إعدادات الباركود",
                [
                    ft.Text("تُطبَّق فورًا على المواد ونقطة البيع وملصقات الطباعة دون إعادة تشغيل.", size=12, color=Colors.TEXT_SECONDARY),
                    ft.Row([barcode_preview], alignment=ft.MainAxisAlignment.CENTER),
                    ft.Text("نوع الباركود الافتراضي عند التوليد", size=12, weight=ft.FontWeight.W_600),
                    barcode_kind_field,
                    barcode_prefix_field,
                    ft.Divider(height=1, color=Colors.BACKGROUND_ALT),
                    ft.Text("التحقق والتنبيهات", size=12, weight=ft.FontWeight.W_600),
                    barcode_auto_generate_switch,
                    barcode_similar_switch,
                    barcode_checksum_switch,
                    ft.Divider(height=1, color=Colors.BACKGROUND_ALT),
                    ft.Text("ملصقات الطباعة", size=12, weight=ft.FontWeight.W_600),
                    ft.Text("نوع الطابعة", size=11, color=Colors.TEXT_SECONDARY),
                    barcode_layout_field,
                    barcode_sheet_only_box,
                    barcode_roll_only_box,
                    barcode_show_text_switch,
                    barcode_price_qr_switch,
                    ft.Divider(height=1, color=Colors.BACKGROUND_ALT),
                    ft.Text("تنبيه المسح في نقطة البيع", size=12, weight=ft.FontWeight.W_600),
                    barcode_scan_feedback_field,
                    ft.FilledButton("حفظ إعدادات الباركود", icon=ft.Icons.SAVE_OUTLINED, on_click=save_barcode_settings),
                ],
            ),
            "invoice": self._section(
                "إعدادات الفواتير",
                [
                    ft.Text("تُطبَّق فورًا على قائمة الفواتير والطباعة/PDF لكل الفواتير القديمة والجديدة.", size=12, color=Colors.TEXT_SECONDARY),
                    ft.Text("رقم الفاتورة المعروض", size=12, weight=ft.FontWeight.W_600),
                    invoice_prefix_field,
                    ft.Text("عدد الأرقام", size=11, color=Colors.TEXT_SECONDARY),
                    invoice_padding_field,
                    ft.Divider(height=1, color=Colors.BACKGROUND_ALT),
                    ft.Text("الاستحقاق والتأخر", size=12, weight=ft.FontWeight.W_600),
                    ft.ResponsiveRow(
                        [
                            ft.Container(invoice_due_days_field, col={"xs": 12, "md": 6}),
                            ft.Container(invoice_overdue_days_field, col={"xs": 12, "md": 6}),
                        ]
                    ),
                    ft.Divider(height=1, color=Colors.BACKGROUND_ALT),
                    ft.Text("محتوى الطباعة", size=12, weight=ft.FontWeight.W_600),
                    invoice_footer_field,
                    invoice_sign_boxes_switch,
                    invoice_verify_qr_switch,
                    ft.FilledButton("حفظ إعدادات الفواتير", icon=ft.Icons.SAVE_OUTLINED, on_click=save_invoice_settings),
                ],
            ),
            "pos": self._section(
                "إعدادات نقطة البيع",
                [
                    ft.Text("تُطبَّق في المرة القادمة التي يفتح فيها أي مستخدم نقطة البيع.", size=12, color=Colors.TEXT_SECONDARY),
                    pos_auto_print_switch,
                    ft.Divider(height=1, color=Colors.BACKGROUND_ALT),
                    ft.Text("عدد أزرار المبالغ الجاهزة في شاشة الدفع", size=12, weight=ft.FontWeight.W_600),
                    pos_quick_cash_field,
                    ft.FilledButton("حفظ إعدادات نقطة البيع", icon=ft.Icons.SAVE_OUTLINED, on_click=save_pos_settings),
                ],
            ),
            "stocktake": self._section(
                "إعدادات الجرد",
                [
                    ft.Text("تُطبَّق في المرة القادمة التي يفتح فيها أي مستخدم شاشة الجرد بالمسح المستمر.", size=12, color=Colors.TEXT_SECONDARY),
                    ft.Text("مهلة تجاهل إعادة مسح نفس الباركود", size=12, weight=ft.FontWeight.W_600),
                    stocktake_cooldown_field,
                    ft.Divider(height=1, color=Colors.BACKGROUND_ALT),
                    stocktake_sound_switch,
                    ft.FilledButton("حفظ إعدادات الجرد", icon=ft.Icons.SAVE_OUTLINED, on_click=save_stocktake_settings),
                ],
            ),
            "sound": self._section(
                "النظام الصوتي",
                [
                    ft.Text(
                        "نغمات قصيرة تصاحب كل رسالة نجاح/خطأ/تنبيه في التطبيق تلقائيًا "
                        "(نقطة البيع، الجرد، الفواتير، تسجيل الدخول، إلخ)، بالإضافة إلى ست نغمات "
                        "مخصصة لأكثر الأحداث تكرارًا: مسح الباركود، حفظ الفاتورة/الدفعة، حذف "
                        "فاتورة/مادة/طرف، تسجيل الدخول، تنبيه جديد بمركز الإشعارات، وباركود غير "
                        "موجود — تُطبَّق فورًا دون إعادة تشغيل.",
                        size=12, color=Colors.TEXT_SECONDARY,
                    ),
                    sound_enabled_switch,
                    ft.Text("مستوى الصوت", size=12, weight=ft.FontWeight.W_600),
                    sound_volume_field,
                    ft.Divider(height=1, color=Colors.BACKGROUND_ALT),
                    ft.Text("تفعيل حسب نوع الرسالة", size=12, weight=ft.FontWeight.W_600),
                    sound_kind_success_switch,
                    sound_kind_error_switch,
                    sound_kind_warning_switch,
                    sound_kind_info_switch,
                    ft.Divider(height=1, color=Colors.BACKGROUND_ALT),
                    ft.Text("نغمات مخصصة لأحداث معينة", size=12, weight=ft.FontWeight.W_600),
                    sound_kind_scan_switch,
                    sound_kind_save_switch,
                    sound_kind_delete_switch,
                    sound_kind_login_switch,
                    sound_kind_notify_switch,
                    sound_kind_barcode_error_switch,
                    ft.Divider(height=1, color=Colors.BACKGROUND_ALT),
                    ft.Text("معاينة", size=12, weight=ft.FontWeight.W_600),
                    ft.Row(
                        [
                            ft.OutlinedButton("نجاح", icon=ft.Icons.CHECK_CIRCLE_OUTLINE, on_click=preview_sound("success")),
                            ft.OutlinedButton("خطأ", icon=ft.Icons.ERROR_OUTLINE, on_click=preview_sound("error")),
                            ft.OutlinedButton("تنبيه", icon=ft.Icons.WARNING_AMBER_OUTLINED, on_click=preview_sound("warning")),
                            ft.OutlinedButton("عادي", icon=ft.Icons.INFO_OUTLINE, on_click=preview_sound("info")),
                            ft.OutlinedButton("مسح باركود", icon=ft.Icons.QR_CODE_SCANNER, on_click=preview_sound("scan")),
                            ft.OutlinedButton("حفظ", icon=ft.Icons.SAVE_OUTLINED, on_click=preview_sound("save")),
                            ft.OutlinedButton("حذف", icon=ft.Icons.DELETE_OUTLINE, on_click=preview_sound("delete")),
                            ft.OutlinedButton("تسجيل دخول", icon=ft.Icons.LOGIN_ROUNDED, on_click=preview_sound("login")),
                            ft.OutlinedButton("تنبيه جديد", icon=ft.Icons.NOTIFICATIONS_ACTIVE_OUTLINED, on_click=preview_sound("notify")),
                            ft.OutlinedButton("باركود غير موجود", icon=ft.Icons.QR_CODE_2_OUTLINED, on_click=preview_sound("barcode_error")),
                        ],
                        spacing=8, wrap=True,
                    ),
                    ft.Row(
                        [
                            ft.FilledButton("حفظ إعدادات الصوت", icon=ft.Icons.SAVE_OUTLINED, on_click=save_sound_settings),
                            ft.OutlinedButton("تشخيص المشكلة", icon=ft.Icons.HEALTH_AND_SAFETY_OUTLINED, on_click=open_sound_diagnosis),
                        ],
                        spacing=8, wrap=True,
                    ),
                ],
            ),
            "reports": self._section(
                "إعدادات التقارير",
                [
                    ft.Text("تُطبَّق في المرة القادمة التي يفتح فيها أي مستخدم مركز التقارير.", size=12, color=Colors.TEXT_SECONDARY),
                    ft.Text("التقرير الافتراضي عند الفتح", size=12, weight=ft.FontWeight.W_600),
                    reports_default_type_field,
                    ft.Text("المدى الزمني الافتراضي", size=12, weight=ft.FontWeight.W_600),
                    reports_default_range_field,
                    ft.FilledButton("حفظ إعدادات التقارير", icon=ft.Icons.SAVE_OUTLINED, on_click=save_reporting_settings),
                ],
            ),
        }

        TABS = [
            ("appearance", "المظهر", ft.Icons.DARK_MODE_OUTLINED),
            ("users", "المستخدمون", ft.Icons.PEOPLE_ALT_OUTLINED),
            ("backup", "النسخ الاحتياطي", ft.Icons.BACKUP_OUTLINED),
            ("license", "الترخيص", ft.Icons.VERIFIED_USER_OUTLINED),
            ("branding", "الهوية والعملة", ft.Icons.PALETTE_OUTLINED),
            ("barcode", "الباركود", ft.Icons.QR_CODE_2_OUTLINED),
            ("invoice", "الفواتير", ft.Icons.RECEIPT_LONG_OUTLINED),
            ("pos", "نقطة البيع", ft.Icons.POINT_OF_SALE_OUTLINED),
            ("stocktake", "الجرد", ft.Icons.FACT_CHECK_OUTLINED),
            ("sound", "الصوت", ft.Icons.VOLUME_UP_OUTLINED),
            ("reports", "التقارير", ft.Icons.BAR_CHART_OUTLINED),
            ("audit", "سجل التدقيق", ft.Icons.HISTORY),
        ]
        tab_state = {"active": "users"}
        tab_chips: dict[str, ft.Container] = {}

        for key, panel in section_panels.items():
            panel.visible = key == tab_state["active"]

        def switch_tab(key: str):
            if key == tab_state["active"]:
                return
            tab_state["active"] = key
            for k, panel in section_panels.items():
                panel.visible = k == key
            for k, chip in tab_chips.items():
                is_active = k == key
                chip.bgcolor = Colors.PRIMARY if is_active else Colors.WHITE
                chip.border = ft.border.all(1, Colors.PRIMARY if is_active else Colors.BORDER)
                row: ft.Row = chip.content
                row.controls[0].color = Colors.WHITE if is_active else Colors.TEXT_MUTED
                row.controls[1].color = Colors.WHITE if is_active else Colors.TEXT_MUTED
                row.controls[1].weight = ft.FontWeight.BOLD if is_active else ft.FontWeight.W_500
            self.page.update()

        def _tab_chip(key: str, label: str, icon: str) -> ft.Container:
            is_active = key == tab_state["active"]
            chip = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(icon, size=15, color=Colors.WHITE if is_active else Colors.TEXT_MUTED),
                        ft.Text(
                            label,
                            size=12.5,
                            color=Colors.WHITE if is_active else Colors.TEXT_MUTED,
                            weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.W_500,
                        ),
                    ],
                    spacing=6,
                    tight=True,
                ),
                padding=ft.padding.symmetric(horizontal=14, vertical=9),
                bgcolor=Colors.PRIMARY if is_active else Colors.WHITE,
                border=ft.border.all(1, Colors.PRIMARY if is_active else Colors.BORDER),
                border_radius=20,
                ink=True,
                animate=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
                on_click=lambda _, k=key: switch_tab(k),
            )
            tab_chips[key] = chip
            return chip

        tab_bar = ft.Row(
            [_tab_chip(key, label, icon) for key, label, icon in TABS] + [ft.Container(width=8)],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
        )

        self.content.content = ft.Column(
            [
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text("الإدارة والأمان", size=24, weight=ft.FontWeight.BOLD),
                                ft.Text(f"المستخدم الحالي: {session.full_name} ({ROLE_LABELS.get(session.role, session.role)})", size=12, color=Colors.TEXT_SECONDARY),
                            ],
                            expand=True,
                        ),
                        ft.OutlinedButton("تسجيل الخروج", icon=ft.Icons.LOGOUT, on_click=lambda _: self.on_logout()),
                    ]
                ),
                status_strip,
                tab_bar,
                ft.Column(list(section_panels.values()), spacing=12),
            ],
            scroll=ft.ScrollMode.AUTO,
            spacing=14,
        )
        self.page.update()
