from __future__ import annotations

import flet as ft

from nano_offline.core.toast import toast

from nano_offline.components import PatternPad, SelectAllTextField
from nano_offline.core.theme import Colors, Radius, Shadow


class SecurityCenter:
    """Quick-auth (PIN/pattern) setup and saved-login status for the current user.

    Extracted from ``main.py`` (previously the inline ``show_security`` closure).
    """

    def __init__(self, page: ft.Page, ctx, content: ft.Container, *, on_title_change=None):
        self.page = page
        self.ctx = ctx
        self.content = content
        self.on_title_change = on_title_change

    def _set_header(self, title: str, subtitle: str = "") -> None:
        if self.on_title_change:
            self.on_title_change(title, subtitle)

    def notify(self, text: str, kind: str | None = None, sound_kind: str | None = None) -> None:
        toast(self.page, text, kind=kind, sound_kind=sound_kind)

    # -- shared bottom-sheet shell -----------------------------------------
    # Matches the modal bottom sheet already established in main.py
    # (``more_sheet``): drag handle, rounded top corners, white surface,
    # LG shadow. Centralized here so pin/pattern/clear all look identical.

    @staticmethod
    def _icon_bubble(icon: str, *, color: str = Colors.PRIMARY, bgcolor: str = Colors.PRIMARY_BG) -> ft.Container:
        return ft.Container(
            ft.Icon(icon, color=color, size=24),
            width=48,
            height=48,
            alignment=ft.alignment.center,
            bgcolor=bgcolor,
            border_radius=Radius.MD,
        )

    def _open_sheet(self, *, icon: str, icon_color: str, icon_bg: str, title: str, subtitle: str, body: ft.Control, actions: list[ft.Control]) -> ft.BottomSheet:
        sheet = ft.BottomSheet(content=ft.Container(), is_scroll_controlled=True, enable_drag=True, maintain_bottom_view_insets_padding=True)
        sheet.content = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [ft.Container(width=44, height=5, bgcolor=Colors.BORDER_STRONG, border_radius=10)],
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [
                            self._icon_bubble(icon, color=icon_color, bgcolor=icon_bg),
                            ft.Column(
                                [
                                    ft.Text(title, size=18, weight=ft.FontWeight.BOLD),
                                    ft.Text(subtitle, size=11, color=Colors.TEXT_SECONDARY),
                                ],
                                spacing=1,
                                expand=True,
                            ),
                        ],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Divider(height=1, color=Colors.BORDER_ALT),
                    body,
                    ft.Row(actions, spacing=10, alignment=ft.MainAxisAlignment.END),
                ],
                spacing=16,
                tight=True,
                scroll=ft.ScrollMode.AUTO,
            ),
            padding=ft.padding.only(left=20, right=20, top=12, bottom=26),
            bgcolor=Colors.WHITE,
            border_radius=ft.border_radius.only(top_left=28, top_right=28),
            shadow=Shadow.LG,
        )
        self.page.open(sheet)
        return sheet

    @staticmethod
    def _styled_field(**kwargs) -> ft.TextField:
        defaults = dict(
            border_radius=Radius.MD,
            filled=True,
            bgcolor=Colors.BACKGROUND_ALT,
            border_color=Colors.BORDER,
            focused_border_color=Colors.PRIMARY,
        )
        defaults.update(kwargs)
        return SelectAllTextField(**defaults)

    def show_center(self) -> None:
        page = self.page
        ctx = self.ctx
        content = self.content
        notify = self.notify
        self._set_header("الأمان والدخول", "إدارة PIN والنمط والجلسة المحفوظة على هذا الجهاز")
        session = ctx.auth.current()
        if session is None:
            raise RuntimeError("لا توجد جلسة مستخدم")
        quick_kind = ctx.auth.quick_auth_info(session.username)
        quick_label = {"pin": "PIN", "pattern": "نمط"}.get(quick_kind, "غير مفعّل")
        quick_status = ft.Text(f"الدخول السريع الحالي: {quick_label}", color=Colors.TEXT_MUTED)
        saved_status = ft.Text(
            "الدخول التلقائي مفعّل على هذا الجهاز" if ctx.auth.saved_login_enabled(session.username) else "الدخول التلقائي غير مفعّل",
            color=Colors.TEXT_MUTED,
        )

        def refresh_security():
            kind = ctx.auth.quick_auth_info(session.username)
            quick_status.value = "الدخول السريع الحالي: " + {"pin": "PIN", "pattern": "نمط"}.get(kind, "غير مفعّل")
            saved_status.value = "الدخول التلقائي مفعّل على هذا الجهاز" if ctx.auth.saved_login_enabled(session.username) else "الدخول التلقائي غير مفعّل"
            page.update()

        def pin_dialog(_=None):
            current_password = self._styled_field(label="كلمة المرور الحالية", password=True, can_reveal_password=True, prefix_icon=ft.Icons.LOCK_OUTLINE_ROUNDED)
            pin = self._styled_field(
                label="PIN جديد (4–8 أرقام)",
                password=True,
                can_reveal_password=True,
                keyboard_type=ft.KeyboardType.NUMBER,
                prefix_icon=ft.Icons.PIN_ROUNDED,
            )
            confirm = self._styled_field(
                label="تأكيد PIN",
                password=True,
                can_reveal_password=True,
                keyboard_type=ft.KeyboardType.NUMBER,
                prefix_icon=ft.Icons.PIN_ROUNDED,
            )

            def close(_=None):
                page.close(sheet)

            def save(_=None):
                try:
                    if (pin.value or "") != (confirm.value or ""):
                        raise ValueError("تأكيد PIN غير مطابق")
                    ctx.auth.set_quick_auth("pin", pin.value or "", current_password.value or "")
                    page.close(sheet)
                    notify("تم تفعيل الدخول بـ PIN")
                    refresh_security()
                except Exception as exc:
                    notify(str(exc), kind="error")

            sheet = self._open_sheet(
                icon=ft.Icons.LOCK_ROUNDED,
                icon_color=Colors.PRIMARY,
                icon_bg=Colors.PRIMARY_BG,
                title="إعداد الدخول بـ PIN",
                subtitle="رقم سرّي قصير لفتح Nano بسرعة على هذا الجهاز",
                body=ft.Column([current_password, pin, confirm], spacing=10, tight=True),
                actions=[
                    ft.TextButton("إلغاء", on_click=close),
                    ft.FilledButton("حفظ PIN", icon=ft.Icons.CHECK_ROUNDED, on_click=save),
                ],
            )

        def pattern_dialog(_=None):
            # Two-step wizard (draw, then re-draw to confirm) instead of showing
            # both grids at once: a single 252x252 canvas fits without the
            # sheet needing to scroll while drawing, and a scrollable ancestor
            # around a drag-based canvas is exactly what stops the pattern
            # from being drawable at all -- Flutter's gesture arena can hand a
            # vertical drag to the nearest scrollable ancestor instead of the
            # pad. This also mirrors how Android/iOS actually ask for pattern
            # confirmation: one grid at a time, not two stacked together.
            current_password = self._styled_field(label="كلمة المرور الحالية", password=True, can_reveal_password=True, prefix_icon=ft.Icons.LOCK_OUTLINE_ROUNDED)
            state = {"first_value": None}
            body = ft.Column(spacing=14, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

            def close(_=None):
                page.close(sheet)

            def show_step1():
                state["first_value"] = None

                def captured(value: str):
                    state["first_value"] = value
                    show_step2()

                pad = PatternPad(on_complete=captured)
                body.controls = [
                    current_password,
                    ft.Text("ارسم نمطًا جديدًا (4 نقاط على الأقل)", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                    pad,
                ]
                page.update()

            def show_step2():
                def confirmed(value: str):
                    try:
                        if not (current_password.value or "").strip():
                            raise ValueError("أدخل كلمة المرور الحالية")
                        if value != state["first_value"]:
                            notify("النمط غير مطابق -- ارسم من جديد")
                            show_step1()
                            return
                        ctx.auth.set_quick_auth("pattern", value, current_password.value or "")
                        page.close(sheet)
                        notify("تم تفعيل الدخول بالنمط")
                        refresh_security()
                    except Exception as exc:
                        notify(str(exc), kind="error")

                pad = PatternPad(on_complete=confirmed)
                body.controls = [
                    current_password,
                    ft.Text("أعد رسم نفس النمط للتأكيد", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                    pad,
                    ft.TextButton("رسم نمط جديد بدل هذا", icon=ft.Icons.REFRESH, on_click=lambda _: show_step1()),
                ]
                page.update()

            sheet = self._open_sheet(
                icon=ft.Icons.APPS_ROUNDED,
                icon_color=Colors.PURPLE,
                icon_bg=Colors.PURPLE_BG,
                title="إعداد نمط الدخول",
                subtitle="ارسم نمطًا يربط 4 نقاط على الأقل لفتح Nano بسرعة",
                body=body,
                actions=[ft.TextButton("إلغاء", on_click=close)],
            )
            show_step1()

        def clear_dialog(_=None):
            current_password = self._styled_field(label="كلمة المرور الحالية", password=True, can_reveal_password=True, prefix_icon=ft.Icons.LOCK_OUTLINE_ROUNDED)

            def close(_=None):
                page.close(sheet)

            def clear(_=None):
                try:
                    ctx.auth.clear_quick_auth(current_password.value or "")
                    page.close(sheet)
                    notify("تم إلغاء PIN / النمط")
                    refresh_security()
                except Exception as exc:
                    notify(str(exc), kind="error")

            sheet = self._open_sheet(
                icon=ft.Icons.REFRESH_ROUNDED,
                icon_color=Colors.DANGER,
                icon_bg=Colors.DANGER_BG,
                title="إلغاء الدخول السريع",
                subtitle="سيعود تسجيل الدخول إلى كلمة المرور الكاملة فقط",
                body=ft.Column([current_password], spacing=10, tight=True),
                actions=[
                    ft.TextButton("إلغاء", on_click=close),
                    ft.FilledButton(
                        "إلغاء الدخول السريع",
                        icon=ft.Icons.REMOVE_CIRCLE_OUTLINE_ROUNDED,
                        on_click=clear,
                    ),
                ],
            )

        content.content = ft.Column(
            [
                ft.Container(
                    ft.Column(
                        [
                            ft.Text(f"المستخدم: {session.full_name} ({session.username})", weight=ft.FontWeight.BOLD),
                            quick_status,
                            saved_status,
                            ft.Text(
                                "لا يتم حفظ كلمة المرور كنص. خيار البقاء مسجلاً يستخدم رمز جلسة عشوائيًا محليًا، بينما PIN والنمط يحفظان كبصمة مشفرة مرتبطة بهذا الجهاز.",
                                size=11,
                                color=Colors.TEXT_SECONDARY,
                            ),
                        ],
                        spacing=6,
                    ),
                    padding=14,
                    border=ft.border.all(1, Colors.BORDER),
                    border_radius=14,
                    bgcolor=Colors.WHITE,
                    shadow=Shadow.SM,
                ),
                ft.ResponsiveRow(
                    [
                        ft.Container(ft.FilledButton("إعداد PIN", icon=ft.Icons.LOCK, on_click=pin_dialog), col={"xs": 6, "md": 3}),
                        ft.Container(ft.OutlinedButton("إعداد نمط", icon=ft.Icons.APPS_ROUNDED, on_click=pattern_dialog), col={"xs": 6, "md": 3}),
                        ft.Container(ft.TextButton("إلغاء PIN / النمط", icon=ft.Icons.REFRESH, on_click=clear_dialog), col={"xs": 12, "md": 3}),
                    ],
                    spacing=8,
                    run_spacing=8,
                ),
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )
        page.update()


__all__ = ["SecurityCenter"]
