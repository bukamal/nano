from __future__ import annotations

import asyncio

import flet as ft

from nano_offline.core.toast import toast

from nano_offline.components import SelectAllTextField
from nano_offline.services.license_service import HAWAA_ACTIVATION_URL
from nano_offline.version import APP_VERSION
from nano_offline.core.theme import Colors, Radius, Shadow, STATUS_STYLES as _STATUS_STYLES


class ActivationGate:
    """First-run/invalid-license gate using the Hawaa Al-Sham activation server."""

    def __init__(self, page: ft.Page, ctx, *, on_success):
        self.page = page
        self.ctx = ctx
        self.on_success = on_success

        # -- responsive sizing, mirrored from LoginGate: the card caps at
        # 420 on wide/desktop windows but shrinks on narrow phones, and
        # every fixed-width child below derives from the same value so
        # nothing can end up wider than the card and clip off-screen. --
        self._card_width = min(420, page.width - 32) if page.width else 420
        self._content_width = max(240, self._card_width - 52)

        self.key = SelectAllTextField(
            label="مفتاح الترخيص",
            hint_text="XXXX-XXXX-XXXX-XXXX",
            password=True,
            can_reveal_password=True,
            text_align=ft.TextAlign.CENTER,
            border_radius=Radius.MD,
            border_color=Colors.BORDER,
            focused_border_color=Colors.PRIMARY,
            bgcolor=Colors.BACKGROUND_ALT,
            filled=True,
            prefix_icon=ft.Icons.VPN_KEY_ROUNDED,
            width=self._content_width,
        )

        # -- status pill (icon + text; recolors per state instead of a bare Text) --
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
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )

        self.progress = ft.ProgressBar(
            width=self._content_width,
            visible=False,
            color=Colors.PRIMARY,
            bgcolor=Colors.PRIMARY_BG,
            border_radius=20,
        )

        # -- CTA: a gradient "button" container (FilledButton can't carry a
        # gradient fill), matching the gradient language already used for the
        # primary action elsewhere in the app (see sale_fab in main.py). --
        self._activate_icon = ft.Icon(ft.Icons.VERIFIED_USER_ROUNDED, color=Colors.WHITE, size=20)
        self._activate_label = ft.Text("تفعيل الآن", color=Colors.WHITE, weight=ft.FontWeight.BOLD, size=15)
        self.activate_button = ft.Container(
            ft.Row(
                [self._activate_icon, self._activate_label],
                spacing=8,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            width=self._content_width,
            height=50,
            border_radius=Radius.MD,
            gradient=ft.LinearGradient(
                colors=[Colors.PRIMARY, Colors.PURPLE_LIGHT],
                begin=ft.alignment.center_left,
                end=ft.alignment.center_right,
            ),
            shadow=ft.BoxShadow(blur_radius=18, spread_radius=0, color=Colors.PRIMARY_BORDER, offset=ft.Offset(0, 6)),
            alignment=ft.alignment.center,
            ink=True,
            on_click=self._activate,
            animate_opacity=200,
        )

        # entrance-animated wrapper for the whole card
        self._card: ft.Container | None = None

    def _set_status(self, kind: str, text: str) -> None:
        icon, color, bgcolor, border = _STATUS_STYLES.get(kind, _STATUS_STYLES["info"])
        self._status_icon.name = icon
        self._status_icon.color = color
        self._status_text.value = text
        self._status_text.color = color
        self.status.bgcolor = bgcolor
        self.status.border = ft.border.all(1, border)

    def _set_busy(self, busy: bool) -> None:
        self.progress.visible = busy
        self.key.disabled = busy
        self.activate_button.disabled = busy
        self.activate_button.opacity = 0.6 if busy else 1
        self._activate_icon.name = ft.Icons.HOURGLASS_TOP_ROUNDED if busy else ft.Icons.VERIFIED_USER_ROUNDED
        self._activate_label.value = "جارٍ التفعيل..." if busy else "تفعيل الآن"
        self.page.update()

    async def _activate(self, _):
        self._set_busy(True)
        try:
            status = await asyncio.to_thread(self.ctx.license.activate_online, self.key.value or "", APP_VERSION)
            if not status.valid:
                raise RuntimeError(status.reason or "فشل التفعيل")
            self._set_status("success", "تم التفعيل بنجاح. سيعمل التطبيق الآن أوفلاين.")
            self.page.update()
            await asyncio.sleep(0.15)
            self.on_success()
        except Exception as exc:
            self._set_status("error", str(exc))
            self._set_busy(False)

    def _copy_device_id(self, device: str):
        def handler(_=None):
            self.page.set_clipboard(device)
            toast(self.page, "تم نسخ معرّف الجهاز", kind="success", duration=1400)

        return handler

    def show(self) -> None:
        details = self.ctx.license.safe_details()
        if details["valid"]:
            self.on_success()
            return
        device = details["device_id"]
        reason = details["message"]
        if details["activated"]:
            self._set_status("error", reason)
        else:
            self._set_status("info", "أدخل مفتاح الترخيص للمتابعة")

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
            gradient=ft.LinearGradient(
                colors=[Colors.PRIMARY, Colors.PURPLE_LIGHT],
                begin=ft.alignment.top_left,
                end=ft.alignment.bottom_right,
            ),
            shadow=ft.BoxShadow(blur_radius=28, spread_radius=2, color=Colors.PRIMARY_BORDER, offset=ft.Offset(0, 10)),
        )

        server_chip = ft.Container(
            ft.Row(
                [
                    ft.Container(
                        ft.Icon(ft.Icons.DNS_ROUNDED, color=Colors.PRIMARY, size=20),
                        width=40,
                        height=40,
                        alignment=ft.alignment.center,
                        bgcolor=Colors.PRIMARY_BG,
                        border_radius=Radius.SM,
                    ),
                    ft.Column(
                        [
                            ft.Text("سيرفر التفعيل", size=11, color=Colors.TEXT_SECONDARY),
                            ft.Text("هوى الشام", weight=ft.FontWeight.BOLD, size=14),
                            ft.Text(HAWAA_ACTIVATION_URL, size=10, color=Colors.TEXT_FAINT, selectable=True),
                        ],
                        spacing=1,
                        expand=True,
                    ),
                    ft.Icon(ft.Icons.CLOUD_DONE_ROUNDED, color=Colors.SUCCESS, size=18),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=12,
            border=ft.border.all(1, Colors.BORDER_ALT),
            border_radius=Radius.MD,
            bgcolor=Colors.BACKGROUND,
            width=self._content_width,
        )

        device_row = ft.Container(
            ft.Row(
                [
                    ft.Icon(ft.Icons.PERM_DEVICE_INFORMATION_ROUNDED, size=14, color=Colors.TEXT_FAINT),
                    ft.Text(f"معرّف الجهاز: {device[:12]}…{device[-8:]}", size=11, color=Colors.TEXT_SECONDARY, selectable=True),
                    ft.IconButton(
                        icon=ft.Icons.COPY_ROUNDED,
                        icon_size=14,
                        icon_color=Colors.TEXT_FAINT,
                        tooltip="نسخ معرّف الجهاز",
                        on_click=self._copy_device_id(device),
                        width=24,
                        height=24,
                    ),
                ],
                spacing=4,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
        )

        card = ft.Container(
            ft.Column(
                [
                    icon_badge,
                    ft.Text("تفعيل Nano | نانو", size=24, weight=ft.FontWeight.BOLD, color=Colors.PRIMARY_DARK),
                    server_chip,
                    device_row,
                    ft.Container(height=2),
                    self.key,
                    self.activate_button,
                    self.progress,
                    self.status,
                    ft.Text(f"الإصدار {APP_VERSION}", size=10, color=Colors.TEXT_FAINT),
                ],
                spacing=12,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            # Responsive width computed once in __init__ (self._card_width);
            # every field/status/button inside derives from the same value.
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
            ft.Column(
                [card],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            expand=True,
            padding=16,
            alignment=ft.alignment.center,
            gradient=ft.LinearGradient(
                colors=[Colors.PRIMARY_BG, Colors.BACKGROUND, Colors.BACKGROUND],
                begin=ft.alignment.top_center,
                end=ft.alignment.bottom_center,
            ),
        )

        self.page.add(background)
        self.page.update()
        # trigger the entrance transition on the next frame
        card.opacity = 1
        card.scale = 1
        self.page.update()


__all__ = ["ActivationGate"]
