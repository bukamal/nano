from __future__ import annotations

import asyncio

import flet as ft

from qeid_offline.services.license_service import HAWAA_ACTIVATION_URL


class ActivationGate:
    """First-run/invalid-license gate using the Hawaa Al-Sham activation server."""

    def __init__(self, page: ft.Page, ctx, *, on_success):
        self.page = page
        self.ctx = ctx
        self.on_success = on_success
        self.key = ft.TextField(
            label="مفتاح الترخيص",
            hint_text="XXXX-XXXX-XXXX-XXXX",
            password=True,
            can_reveal_password=True,
            text_align=ft.TextAlign.CENTER,
            width=360,
        )
        self.status = ft.Text("", size=12, text_align=ft.TextAlign.CENTER)
        self.progress = ft.ProgressBar(width=360, visible=False)
        self.activate_button = ft.FilledButton(
            "تفعيل الآن",
            icon=ft.Icons.VERIFIED_USER,
            width=360,
            on_click=self._activate,
        )

    def _set_busy(self, busy: bool) -> None:
        self.progress.visible = busy
        self.activate_button.disabled = busy
        self.key.disabled = busy
        self.page.update()

    async def _activate(self, _):
        self._set_busy(True)
        try:
            status = await asyncio.to_thread(self.ctx.license.activate_online, self.key.value or "", "0.7.1")
            if not status.valid:
                raise RuntimeError(status.reason or "فشل التفعيل")
            self.status.value = "تم التفعيل بنجاح. سيعمل التطبيق الآن أوفلاين."
            self.status.color = "#15803D"
            self.page.update()
            await asyncio.sleep(0.15)
            self.on_success()
        except Exception as exc:
            self.status.value = str(exc)
            self.status.color = "#B91C1C"
            self._set_busy(False)

    def show(self) -> None:
        details = self.ctx.license.safe_details()
        if details["valid"]:
            self.on_success()
            return
        device = details["device_id"]
        reason = details["message"]
        self.status.value = reason if details["activated"] else "أدخل مفتاح الترخيص للمتابعة"
        self.status.color = "#B91C1C" if details["activated"] else "#64748B"
        self.page.add(
            ft.Container(
                ft.Column(
                    [
                        ft.Container(
                            ft.Column(
                                [
                                    ft.Icon(ft.Icons.VERIFIED_USER, size=54, color="#0F4C81"),
                                    ft.Text("تفعيل قيد", size=26, weight=ft.FontWeight.BOLD),
                                    ft.Text(
                                        "يستخدم نفس سيرفر تفعيل هوى الشام. الاتصال مطلوب عند التفعيل فقط، وبعد نجاحه تبقى البيانات والمحاسبة محلية على الجهاز.",
                                        size=12,
                                        color="#475569",
                                        text_align=ft.TextAlign.CENTER,
                                    ),
                                    ft.Container(
                                        ft.Column(
                                            [
                                                ft.Text("سيرفر التفعيل", size=11, color="#64748B"),
                                                ft.Text("هوى الشام", weight=ft.FontWeight.BOLD),
                                                ft.Text(HAWAA_ACTIVATION_URL, size=10, color="#64748B", selectable=True),
                                            ],
                                            spacing=2,
                                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                        ),
                                        padding=10,
                                        border=ft.border.all(1, "#E5E7EB"),
                                        border_radius=10,
                                        bgcolor="#F8FAFC",
                                    ),
                                    ft.Text(f"معرّف الجهاز: {device[:12]}…{device[-8:]}", size=11, color="#64748B", selectable=True),
                                    self.key,
                                    self.activate_button,
                                    self.progress,
                                    self.status,
                                    ft.Text(
                                        "لا تُرسل فواتير أو عملاء أو موردون أو مخزون إلى خادم التفعيل.",
                                        size=11,
                                        color="#64748B",
                                        text_align=ft.TextAlign.CENTER,
                                    ),
                                ],
                                spacing=12,
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            width=410,
                            padding=24,
                            border=ft.border.all(1, "#E5E7EB"),
                            border_radius=16,
                            bgcolor="#FFFFFF",
                        )
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                expand=True,
                padding=16,
            )
        )
        self.page.update()


__all__ = ["ActivationGate"]
