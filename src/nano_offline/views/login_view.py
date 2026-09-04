from __future__ import annotations

import flet as ft

from nano_offline.core.toast import toast

from nano_offline.components import PatternPad, SelectAllTextField
from nano_offline.version import APP_VERSION
from nano_offline.core.theme import Colors, Radius, Shadow, STATUS_STYLES


class LoginGate:
    """Local sign-in / first-run admin setup.

    Extracted from ``main.py`` (previously the inline ``show_auth``
    closure) and restyled to match ``ActivationGate`` -- the two screens a
    fresh install walks through back-to-back -- so the auth flow reads as
    one continuous, deliberate experience instead of a polished activation
    screen handing off to a bare form: same gradient background, same icon
    badge, same animated card entrance, same gradient CTA, and the same
    status-pill styling for errors (now shared via ``theme.STATUS_STYLES``).
    """

    def __init__(self, page: ft.Page, ctx, *, on_success):
        self.page = page
        self.ctx = ctx
        self.on_success = on_success
        self.first_run = not ctx.auth.has_users()
        self.remembered = ctx.auth.remembered_username() if not self.first_run else ""
        self._step = 0  # first-run wizard only: 0 = account, 1 = password
        self._quick_kind: str | None = None
        self._card: ft.Container | None = None

        # -- responsive sizing: the card caps at 420 on wide/desktop windows
        # but shrinks to fit narrow phone screens (page.width is already
        # used the same way for the desktop-shell check in main.py), and
        # every fixed-width child inside the card is derived from it so
        # nothing (fields, buttons, the status pill) can end up wider than
        # the card itself and clip off-screen. --
        self._card_width = min(420, page.width - 32) if page.width else 420
        self._content_width = max(240, self._card_width - 52)

        # -- status pill (icon + text; recolors per state, shared token set) --
        self._status_icon = ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, size=16, color=Colors.TEXT_SECONDARY)
        self._status_text = ft.Text("", size=12, text_align=ft.TextAlign.CENTER, expand=True)
        self.status = ft.Container(
            ft.Row(
                [self._status_icon, self._status_text],
                spacing=6,
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            border_radius=Radius.SM,
            bgcolor=Colors.BACKGROUND_ALT,
            border=ft.border.all(1, Colors.BORDER),
            width=self._content_width,
            visible=False,
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )
        self.progress = ft.ProgressBar(width=self._content_width, visible=False, color=Colors.PRIMARY, bgcolor=Colors.PRIMARY_BG, border_radius=20)

        # -- fields (created once, re-used/re-shown across steps) --
        style = self._field_style()
        self.username = SelectAllTextField(
            label="اسم المستخدم",
            value=self.remembered,
            autofocus=not bool(self.remembered),
            prefix_icon=ft.Icons.PERSON_OUTLINE_ROUNDED,
            on_change=self._refresh_quick,
            **style,
        )
        self.full_name = SelectAllTextField(label="الاسم الكامل", prefix_icon=ft.Icons.BADGE_OUTLINED, **style)
        self.password = SelectAllTextField(
            label="كلمة المرور",
            password=True,
            can_reveal_password=True,
            prefix_icon=ft.Icons.LOCK_OUTLINE_ROUNDED,
            on_submit=lambda _: self._submit(None),
            **style,
        )
        self.confirm = SelectAllTextField(
            label="تأكيد كلمة المرور", password=True, can_reveal_password=True, prefix_icon=ft.Icons.LOCK_OUTLINE_ROUNDED, **style
        )

        # -- modern switches instead of plain checkboxes --
        self.remember_name_switch = ft.Switch(value=bool(self.remembered) or self.first_run, active_color=Colors.PRIMARY)
        self.stay_signed_switch = ft.Switch(value=False, active_color=Colors.PRIMARY)

        # -- quick-login chip (avatar bubble + label), replaces the plain
        # OutlinedButton; only shown once a saved user has PIN/pattern set --
        self.quick_chip = ft.Container(visible=False, ink=True, border_radius=Radius.MD, on_click=self._open_quick_login)

        # -- gradient CTA, identical recipe to ActivationGate.activate_button --
        self._submit_icon = ft.Icon(ft.Icons.LOGIN_ROUNDED, color=Colors.WHITE, size=20)
        self._submit_label = ft.Text("", color=Colors.WHITE, weight=ft.FontWeight.BOLD, size=15)
        self.submit_button = ft.Container(
            ft.Row([self._submit_icon, self._submit_label], spacing=8, alignment=ft.MainAxisAlignment.CENTER),
            # expand (not a fixed width) so it always shares the row with
            # back_button correctly instead of forcing a combined width
            # that can exceed the card's inner width and clip off-screen.
            expand=True,
            height=50,
            border_radius=Radius.MD,
            gradient=ft.LinearGradient(colors=[Colors.PRIMARY, Colors.PURPLE_LIGHT], begin=ft.alignment.center_left, end=ft.alignment.center_right),
            shadow=ft.BoxShadow(blur_radius=18, spread_radius=0, color=Colors.PRIMARY_BORDER, offset=ft.Offset(0, 6)),
            alignment=ft.alignment.center,
            ink=True,
            on_click=self._submit,
            animate_opacity=200,
        )
        self.back_button = ft.OutlinedButton("رجوع", icon=ft.Icons.ARROW_BACK_ROUNDED, on_click=self._go_back, visible=False, width=100, height=50)

        # -- first-run step indicator (two pill-dots) --
        self.step_dots = ft.Row([self._dot(), self._dot()], spacing=6, alignment=ft.MainAxisAlignment.CENTER, visible=self.first_run)

        self._body = ft.Column(spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    # -- styling helpers ------------------------------------------------

    def _field_style(self) -> dict:
        return dict(
            border_radius=Radius.MD,
            border_color=Colors.BORDER,
            focused_border_color=Colors.PRIMARY,
            bgcolor=Colors.BACKGROUND_ALT,
            filled=True,
            width=self._content_width,
        )

    @staticmethod
    def _dot() -> ft.Container:
        return ft.Container(width=8, height=8, border_radius=4, bgcolor=Colors.BORDER_STRONG, animate=ft.Animation(150, ft.AnimationCurve.EASE_OUT))

    def _toggle_row(self, label: str, subtitle: str, switch: ft.Switch) -> ft.Container:
        return ft.Container(
            ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(label, size=13, weight=ft.FontWeight.W_500),
                            ft.Text(subtitle, size=10, color=Colors.TEXT_FAINT),
                        ],
                        spacing=1,
                        expand=True,
                    ),
                    switch,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=4, vertical=2),
            width=self._content_width,
        )

    def _set_status(self, kind: str, text: str) -> None:
        icon, color, bgcolor, border = STATUS_STYLES.get(kind, STATUS_STYLES["info"])
        self._status_icon.name = icon
        self._status_icon.color = color
        self._status_text.value = text
        self._status_text.color = color
        self.status.bgcolor = bgcolor
        self.status.border = ft.border.all(1, border)
        self.status.visible = True
        self.page.update()

    def _clear_status(self) -> None:
        self.status.visible = False

    def _set_busy(self, busy: bool) -> None:
        self.progress.visible = busy
        for field in (self.username, self.full_name, self.password, self.confirm):
            field.disabled = busy
        self.submit_button.disabled = busy
        self.submit_button.opacity = 0.6 if busy else 1
        self.back_button.disabled = busy
        self._submit_icon.name = ft.Icons.HOURGLASS_TOP_ROUNDED if busy else ft.Icons.LOGIN_ROUNDED
        self.page.update()

    # -- quick-login chip -------------------------------------------------

    def _refresh_quick(self, _=None) -> None:
        if self.first_run:
            self.quick_chip.visible = False
            self.page.update()
            return
        kind = self.ctx.auth.quick_auth_info(self.username.value or "")
        self._quick_kind = kind
        self.quick_chip.visible = kind in {"pin", "pattern"}
        if kind:
            initial = (self.username.value or "?").strip()[:1].upper() or "?"
            label = "الدخول السريع بـ PIN" if kind == "pin" else "الدخول السريع بالنمط"
            icon = ft.Icons.PIN_ROUNDED if kind == "pin" else ft.Icons.APPS_ROUNDED
            self.quick_chip.content = ft.Row(
                [
                    ft.Container(
                        ft.Text(initial, color=Colors.WHITE, weight=ft.FontWeight.BOLD, size=14),
                        width=32,
                        height=32,
                        alignment=ft.alignment.center,
                        bgcolor=Colors.PRIMARY,
                        border_radius=16,
                    ),
                    ft.Column(
                        [ft.Text(label, size=13, weight=ft.FontWeight.BOLD), ft.Text(self.username.value or "", size=10, color=Colors.TEXT_FAINT)],
                        spacing=0,
                        expand=True,
                    ),
                    ft.Icon(icon, color=Colors.PRIMARY, size=18),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
            self.quick_chip.padding = 10
            self.quick_chip.bgcolor = Colors.PRIMARY_BG
            self.quick_chip.border = ft.border.all(1, Colors.PRIMARY_BORDER)
            self.quick_chip.width = self._content_width
        self.page.update()

    def _open_quick_login(self, _=None) -> None:
        kind = self._quick_kind
        if not kind:
            return
        username = self.username.value or ""

        def close(_=None):
            self.page.close(sheet)

        if kind == "pin":

            def attempt(secret: str) -> bool:
                try:
                    self.ctx.auth.login_quick(username, "pin", secret)
                except Exception as exc:
                    toast(self.page, str(exc), kind="error", duration=1800)
                    return False
                self.page.close(sheet)
                self.on_success()
                return True

            body = self._pin_keypad(on_submit=attempt)
            sheet = self._bottom_sheet(
                icon=ft.Icons.PIN_ROUNDED,
                icon_color=Colors.PRIMARY,
                icon_bg=Colors.PRIMARY_BG,
                title="الدخول بـ PIN",
                subtitle=f"أدخل رمز {username}",
                body=body,
                actions=[ft.TextButton("إلغاء", on_click=close)],
            )
        else:

            def attempt_pattern(value: str) -> None:
                try:
                    self.ctx.auth.login_quick(username, "pattern", value)
                except Exception as exc:
                    toast(self.page, str(exc), kind="error", duration=1800)
                    return
                self.page.close(sheet)
                self.on_success()

            pad = PatternPad(on_complete=attempt_pattern)
            sheet = self._bottom_sheet(
                icon=ft.Icons.APPS_ROUNDED,
                icon_color=Colors.PURPLE,
                icon_bg=Colors.PURPLE_BG,
                title="الدخول بالنمط",
                subtitle=f"ارسم نمط {username}",
                body=ft.Container(pad, alignment=ft.alignment.center),
                actions=[ft.TextButton("إلغاء", on_click=close)],
            )

    def _pin_keypad(self, *, on_submit) -> ft.Column:
        state = {"value": ""}
        digits_text = ft.Text("—", size=28, weight=ft.FontWeight.BOLD, color=Colors.PRIMARY, text_align=ft.TextAlign.CENTER)
        submit_btn = ft.FilledButton("دخول", icon=ft.Icons.CHECK_ROUNDED, disabled=True)

        def refresh() -> None:
            digits_text.value = ("●  " * len(state["value"])).strip() if state["value"] else "—"
            submit_btn.disabled = len(state["value"]) < 4
            submit_btn.opacity = 1 if not submit_btn.disabled else 0.5

        def key_press(digit: str) -> None:
            if len(state["value"]) >= 8:
                return
            state["value"] += digit
            refresh()
            self.page.update()

        def backspace(_=None) -> None:
            state["value"] = state["value"][:-1]
            refresh()
            self.page.update()

        def submit(_=None) -> None:
            if len(state["value"]) < 4:
                return
            if not on_submit(state["value"]):
                state["value"] = ""
                refresh()
                self.page.update()

        submit_btn.on_click = submit

        def key_button(label: str, *, icon: str | None = None, handler=None) -> ft.Container:
            return ft.Container(
                ft.Text(label, size=20, weight=ft.FontWeight.BOLD) if icon is None else ft.Icon(icon, size=20, color=Colors.TEXT_MUTED),
                width=64,
                height=64,
                border_radius=32,
                bgcolor=Colors.BACKGROUND_ALT,
                alignment=ft.alignment.center,
                ink=True,
                on_click=handler,
            )

        layout = [["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"], ["", "0", "back"]]
        rows: list[ft.Row] = []
        for keys in layout:
            row_controls: list[ft.Control] = []
            for k in keys:
                if k == "":
                    row_controls.append(ft.Container(width=64, height=64))
                elif k == "back":
                    row_controls.append(key_button("", icon=ft.Icons.BACKSPACE_OUTLINED, handler=backspace))
                else:
                    row_controls.append(key_button(k, handler=lambda _, d=k: key_press(d)))
            rows.append(ft.Row(row_controls, spacing=14, alignment=ft.MainAxisAlignment.CENTER))

        refresh()
        return ft.Column(
            [digits_text, *rows, submit_btn],
            spacing=14,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        )

    def _bottom_sheet(self, *, icon: str, icon_color: str, icon_bg: str, title: str, subtitle: str, body: ft.Control, actions: list[ft.Control]) -> ft.BottomSheet:
        # Mirrors SecurityCenter._open_sheet's shell (drag handle, rounded
        # top corners, icon bubble + title/subtitle, LG shadow) so quick
        # login uses the same modal language as the rest of the app instead
        # of a bare AlertDialog.
        sheet = ft.BottomSheet(content=ft.Container(), is_scroll_controlled=True, enable_drag=True, maintain_bottom_view_insets_padding=True)
        icon_bubble = ft.Container(ft.Icon(icon, color=icon_color, size=24), width=48, height=48, alignment=ft.alignment.center, bgcolor=icon_bg, border_radius=Radius.MD)
        sheet.content = ft.Container(
            ft.Column(
                [
                    ft.Row([ft.Container(width=44, height=5, bgcolor=Colors.BORDER_STRONG, border_radius=10)], alignment=ft.MainAxisAlignment.CENTER),
                    ft.Row(
                        [icon_bubble, ft.Column([ft.Text(title, size=18, weight=ft.FontWeight.BOLD), ft.Text(subtitle, size=11, color=Colors.TEXT_SECONDARY)], spacing=1, expand=True)],
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

    # -- first-run wizard steps -------------------------------------------

    def _refresh_dots(self) -> None:
        for i, dot in enumerate(self.step_dots.controls):
            active = i == self._step
            dot.width = 18 if active else 8
            dot.bgcolor = Colors.PRIMARY if active else Colors.BORDER_STRONG
        self.page.update()

    def _go_next(self, _) -> None:
        self._step = 1
        self._refresh_dots()
        self._render_step()

    def _go_back(self, _) -> None:
        self._step = 0
        self._refresh_dots()
        self._render_step()

    def _render_step(self) -> None:
        if self.first_run:
            if self._step == 0:
                self._body.controls = [self.username, self.full_name]
                self._submit_label.value = "التالي"
                self._submit_icon.name = ft.Icons.ARROW_FORWARD_ROUNDED
                self.back_button.visible = False
            else:
                self._body.controls = [self.password, self.confirm]
                self._submit_label.value = "إنشاء المدير والدخول"
                self._submit_icon.name = ft.Icons.LOGIN_ROUNDED
                self.back_button.visible = True
        else:
            toggles = ft.Column(
                [
                    self._toggle_row("تذكر اسم المستخدم", "يُعبَّأ اسم المستخدم تلقائيًا في المرة القادمة", self.remember_name_switch),
                    self._toggle_row("البقاء مسجلاً على هذا الجهاز", "يحفظ رمز جلسة محليًا بدل كلمة المرور نفسها", self.stay_signed_switch),
                ],
                spacing=2,
            )
            self._body.controls = [self.username, self.quick_chip, self.password, toggles]
            self._submit_label.value = "دخول بكلمة المرور"
            self._submit_icon.name = ft.Icons.LOGIN_ROUNDED
            self.back_button.visible = False
        self.page.update()

    # -- submit -------------------------------------------------------------

    def _submit(self, _) -> None:
        if self.submit_button.disabled:
            return
        if self.first_run and self._step == 0:
            if len((self.username.value or "").strip()) < 3:
                self._set_status("error", "اسم المستخدم يجب ألا يقل عن 3 أحرف")
                return
            if not (self.full_name.value or "").strip():
                self._set_status("error", "أدخل الاسم الكامل")
                return
            self._clear_status()
            self._go_next(None)
            return
        self._set_busy(True)
        try:
            if self.first_run:
                if (self.password.value or "") != (self.confirm.value or ""):
                    raise ValueError("تأكيد كلمة المرور غير مطابق")
                self.ctx.auth.create_initial_admin(self.username.value or "", self.full_name.value or "", self.password.value or "")
            self.ctx.auth.login(
                self.username.value or "",
                self.password.value or "",
                remember_login=bool(self.stay_signed_switch.value),
                remember_username=bool(self.remember_name_switch.value),
            )
            self.on_success()
        except Exception as exc:
            self._set_busy(False)
            self._set_status("error", str(exc))

    # -- entry point ----------------------------------------------------------

    def show(self) -> None:
        icon_badge = ft.Container(
            ft.Container(
                ft.Image(src="icon.png", width=64, height=64, fit=ft.ImageFit.CONTAIN),
                width=96,
                height=96,
                alignment=ft.alignment.center,
                bgcolor=Colors.WHITE,
                border_radius=28,
                shadow=ft.BoxShadow(blur_radius=14, spread_radius=0, color=Colors.BORDER, offset=ft.Offset(0, 4)),
            ),
            width=112,
            height=112,
            alignment=ft.alignment.center,
            border_radius=32,
            gradient=ft.LinearGradient(colors=[Colors.PRIMARY, Colors.PURPLE_LIGHT], begin=ft.alignment.top_left, end=ft.alignment.bottom_right),
            shadow=ft.BoxShadow(blur_radius=28, spread_radius=2, color=Colors.PRIMARY_BORDER, offset=ft.Offset(0, 10)),
        )
        subtitle = "إنشاء المدير الأول" if self.first_run else "تسجيل الدخول المحلي"
        security_note = ft.Text(
            "يمكن تفعيل PIN أو نمط من قسم الأمان بعد تسجيل الدخول. كلمة المرور لا تُحفظ كنص صريح.",
            size=11,
            color=Colors.TEXT_SECONDARY,
            text_align=ft.TextAlign.CENTER,
        )
        trust_note = ft.Text(
            "كل المستخدمين والبيانات محليون على هذا الجهاز. لا يعتمد التشغيل المحاسبي على خدمات خارجية أو قاعدة بيانات أونلاين.",
            size=11,
            color=Colors.TEXT_SECONDARY,
            text_align=ft.TextAlign.CENTER,
        )

        self._render_step()
        self._refresh_dots()
        self._refresh_quick()

        card = ft.Container(
            ft.Column(
                [
                    icon_badge,
                    ft.Text("Nano | نانو", size=24, weight=ft.FontWeight.BOLD, color=Colors.PRIMARY_DARK),
                    ft.Text(subtitle, size=12, color=Colors.TEXT_MUTED),
                    self.step_dots,
                    self._body,
                    ft.Row([self.back_button, self.submit_button], spacing=10, alignment=ft.MainAxisAlignment.CENTER),
                    self.progress,
                    self.status,
                    security_note,
                    trust_note,
                    ft.Text(f"الإصدار {APP_VERSION}", size=10, color=Colors.TEXT_FAINT),
                ],
                spacing=12,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                scroll=ft.ScrollMode.AUTO,
            ),
            # Responsive width computed once in __init__ (self._card_width);
            # every field/status/toggle inside derives from the same value
            # so nothing can end up wider than the card and clip off-screen.
            width=self._card_width,
            padding=ft.padding.only(left=26, right=26, top=30, bottom=26),
            border_radius=Radius.XL + 4,
            bgcolor=Colors.WHITE,
            shadow=Shadow.LG,
            opacity=0,
            scale=0.96,
            animate_opacity=ft.Animation(360, ft.AnimationCurve.EASE_OUT),
            animate_scale=ft.Animation(360, ft.AnimationCurve.EASE_OUT),
        )
        self._card = card

        background = ft.Container(
            ft.Column([card], alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            expand=True,
            padding=16,
            alignment=ft.alignment.center,
            gradient=ft.LinearGradient(colors=[Colors.PRIMARY_BG, Colors.BACKGROUND, Colors.BACKGROUND], begin=ft.alignment.top_center, end=ft.alignment.bottom_center),
        )

        self.page.add(ft.SafeArea(background, expand=True))
        self.page.update()
        card.opacity = 1
        card.scale = 1
        self.page.update()


__all__ = ["LoginGate"]
