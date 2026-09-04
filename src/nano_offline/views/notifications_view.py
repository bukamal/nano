from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

import flet as ft

from nano_offline.core.toast import toast
from nano_offline.core import sound as sound_engine

from nano_offline.components import SelectAllTextField
from nano_offline.components.buttons import header_close_button
from nano_offline.components.form_sheet import new_form_sheet
from nano_offline.core.theme import Colors, IconSize, Radius, SEVERITY_STYLE, Shadow

_RULE_META = [
    ("receivables", "ذمم متأخرة", "تنبيه عند اقتراب أو تجاوز فواتير البيع موعد التحصيل", ft.Icons.RECEIPT_LONG_OUTLINED),
    ("low_stock", "مخزون منخفض", "تنبيه عند وصول صنف إلى الحد الأدنى من الكمية", ft.Icons.INVENTORY_2_OUTLINED),
    ("backup", "النسخ الاحتياطي", "تذكير عند مرور مدة طويلة دون نسخة احتياطية", ft.Icons.CLOUD_UPLOAD_OUTLINED),
    ("license", "الترخيص", "تنبيه قبل اقتراب انتهاء صلاحية الترخيص", ft.Icons.VERIFIED_OUTLINED),
    ("insights", "ملخص ذكي", "رصد انخفاض غير معتاد بمبيعات اليوم مقارنة بمعدل الأسبوع", ft.Icons.INSIGHTS_OUTLINED),
]

# Where an alert navigates when tapped, keyed by NotificationService.Alert
# .entity_type -- kept in sync with DashboardCenter's own copy in
# views/dashboard_view.py (same rule engine, same two navigable entities).
_ALERT_NAV = {"customer": "customers", "item": "items"}

# (chip key, label) for the panel's quick filter row.
_FILTERS: list[tuple[str, str]] = [
    ("all", "الكل"),
    ("unread", "غير مقروء"),
    ("urgent", "عاجل"),
]


class NotificationCenter:
    """Bell icon panel (recent alerts) + a customizable settings screen.

    ``badge`` is the small unread-count bubble drawn over the top-bar bell
    in main.py; call :meth:`refresh_badge` after navigation so it stays
    current without any background polling.
    """

    def __init__(
        self,
        page: ft.Page,
        ctx,
        content: ft.Container,
        *,
        native_files=None,
        on_title_change: Callable | None = None,
        on_navigate: Callable[[str], None] | None = None,
    ):
        self.page = page
        self.ctx = ctx
        self.content = content
        self.native_files = native_files
        self.on_title_change = on_title_change
        self.on_navigate = on_navigate
        self.badge = ft.Container(
            width=17, height=17, border_radius=9, bgcolor=Colors.DANGER, visible=False,
            alignment=ft.alignment.center,
            content=ft.Text("", size=9, weight=ft.FontWeight.BOLD, color=Colors.WHITE),
        )
        # Tracks the last unread total refresh_badge() saw, so the 'notify'
        # tone only fires when a genuinely *new* alert has landed -- not on
        # every refresh_badge() call, which also fires on every ordinary
        # tab navigation in main.py (would otherwise ding on every click).
        # None means "not yet observed this session" -- the very first
        # refresh just establishes the baseline silently, since whatever
        # is unread at that point isn't new, it's just however many alerts
        # already existed before this screen/session started watching.
        self._last_unread_total: int | None = None

    def _set_header(self, title: str, subtitle: str = "") -> None:
        if self.on_title_change:
            self.on_title_change(title, subtitle)

    def notify(self, text: str) -> None:
        toast(self.page, text)

    def _sync_background_notifications(self) -> None:
        """Re-push the current config to the Android background check.

        Fire-and-forget: called right after any config save so a changed
        threshold or quiet-hours window takes effect for the closed-app
        check immediately, not just next app launch.
        """
        if not self.native_files:
            return

        async def _run():
            try:
                await self.native_files.schedule_notifications(**self.ctx.notifications.native_schedule_payload())
            except Exception:
                pass

        self.page.run_task(_run)

    # -- badge -------------------------------------------------------------
    def refresh_badge(self) -> None:
        """Reflect both *how many* alerts are unread and *how urgent* the
        worst of them is -- a red "3" reads very differently from an amber
        "3", and a lone urgent alert should stand out even among several
        low-priority ones."""
        try:
            summary = self.ctx.notifications.unread_summary()
        except Exception:
            summary = {"total": 0, "urgent": 0, "warning": 0, "info": 0}
        total = int(summary.get("total") or 0)
        # Only the *first* increase over what we last saw counts as "a new
        # alert arrived" -- a rule going from unmatched to matched and
        # generating a fresh row bumps total up; the admin reading/
        # dismissing one bumps it back down, which should stay silent, not
        # ding on the way down too. See _last_unread_total's docstring for
        # why the very first call in a session never plays anything.
        if self._last_unread_total is not None and total > self._last_unread_total:
            sound_engine.play(self.page, "notify")
        self._last_unread_total = total
        self.badge.visible = total > 0
        if summary.get("urgent"):
            self.badge.bgcolor = Colors.DANGER
        elif summary.get("warning"):
            self.badge.bgcolor = Colors.WARNING_DARK
        else:
            self.badge.bgcolor = Colors.PRIMARY
        self.badge.content.value = "9+" if total > 9 else (str(total) if total else "")
        try:
            self.badge.update()
        except Exception:
            pass

    # -- relative time / grouping helpers -----------------------------------
    @staticmethod
    def _parse_created_at(created_at) -> datetime | None:
        try:
            return datetime.fromisoformat(str(created_at).replace(" ", "T"))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _relative_time(cls, created_at) -> str:
        dt = cls._parse_created_at(created_at)
        if dt is None:
            return ""
        seconds = (datetime.utcnow() - dt).total_seconds()
        if seconds < 60:
            return "الآن"
        minutes = int(seconds // 60)
        if minutes < 60:
            return f"قبل {minutes} د"
        hours = int(minutes // 60)
        if hours < 24:
            return f"قبل {hours} س"
        days = int(hours // 24)
        return "أمس" if days == 1 else f"قبل {days} يوم"

    @classmethod
    def _day_group(cls, created_at) -> str:
        dt = cls._parse_created_at(created_at)
        if dt is None:
            return "أقدم"
        today = datetime.utcnow().date()
        d = dt.date()
        if d == today:
            return "اليوم"
        if d == today - timedelta(days=1):
            return "أمس"
        return "أقدم"

    # -- bell panel ----------------------------------------------------------
    def open_panel(self, _=None) -> None:
        all_rows = self.ctx.notifications.recent(limit=30)
        sheet = new_form_sheet()
        state = {"filter": "all"}
        chip_refs: dict[str, ft.Container] = {}
        list_column = ft.Column([], spacing=8, scroll=ft.ScrollMode.AUTO, height=420)
        count_text = ft.Text("", size=11, color=Colors.TEXT_FAINT)

        def close(_=None):
            self.page.close(sheet)

        def open_settings(_=None):
            close()
            self.show_settings()

        def filtered_rows(filter_key: str) -> list[dict]:
            if filter_key == "unread":
                return [r for r in all_rows if r.get("read_at") is None]
            if filter_key == "urgent":
                return [r for r in all_rows if r.get("severity") == "urgent"]
            return all_rows

        def row_click(row: dict):
            def _click(_e=None):
                if row.get("read_at") is None:
                    self.ctx.notifications.mark_read(row["id"])
                    row["read_at"] = "1"
                    self.refresh_badge()
                target = _ALERT_NAV.get(row.get("entity_type"))
                if target and self.on_navigate:
                    close()
                    self.on_navigate(target)
                else:
                    render_list(state["filter"])
            return _click

        def render_list(filter_key: str) -> None:
            state["filter"] = filter_key
            for key, chip in chip_refs.items():
                active = key == filter_key
                chip.bgcolor = Colors.PRIMARY if active else Colors.BACKGROUND_ALT
                chip.content.color = Colors.WHITE if active else Colors.TEXT_MUTED
            rows = filtered_rows(filter_key)
            count_text.value = f"{len(rows)} تنبيه" if filter_key != "all" else f"{len(all_rows)} تنبيه"
            controls: list[ft.Control] = []
            if not rows:
                controls.append(
                    ft.Container(
                        ft.Column(
                            [
                                ft.Icon(ft.Icons.NOTIFICATIONS_NONE_ROUNDED, size=30, color=Colors.TEXT_FAINT),
                                ft.Text(
                                    "لا توجد تنبيهات حاليًا" if filter_key == "all" else "لا يوجد ما يطابق هذا التصفية",
                                    size=12, color=Colors.TEXT_MUTED,
                                ),
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8,
                        ),
                        alignment=ft.alignment.center, padding=ft.padding.symmetric(vertical=28),
                    )
                )
            else:
                last_group = None
                for row in rows:
                    group = self._day_group(row.get("created_at"))
                    if group != last_group:
                        controls.append(ft.Text(group, size=11, weight=ft.FontWeight.BOLD, color=Colors.TEXT_FAINT))
                        last_group = group
                    controls.append(self._alert_row(row, on_click=row_click(row)))
            list_column.controls = controls
            try:
                self.page.update()
            except Exception:
                pass

        def mark_all(_=None):
            self.ctx.notifications.mark_all_read()
            for row in all_rows:
                row["read_at"] = "1"
            self.refresh_badge()
            render_list(state["filter"])

        def make_chip(key: str, label: str) -> ft.Container:
            text = ft.Text(label, size=12, weight=ft.FontWeight.W_600, color=Colors.TEXT_MUTED)
            box = ft.Container(
                text, padding=ft.padding.symmetric(horizontal=13, vertical=7),
                bgcolor=Colors.BACKGROUND_ALT, border_radius=Radius.MD,
                on_click=lambda _e, k=key: render_list(k), ink=True,
            )
            chip_refs[key] = box
            return box

        filter_row = ft.Row([make_chip(k, l) for k, l in _FILTERS], spacing=6)

        body = ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("التنبيهات", size=16, weight=ft.FontWeight.BOLD, expand=True),
                        ft.IconButton(ft.Icons.SETTINGS_OUTLINED, icon_size=IconSize.HEADER, icon_color=Colors.TEXT_SECONDARY, on_click=open_settings, tooltip="تخصيص التنبيهات"),
                        ft.IconButton(ft.Icons.DONE_ALL_ROUNDED, icon_size=IconSize.HEADER, icon_color=Colors.TEXT_SECONDARY, on_click=mark_all, tooltip="تعليم الكل كمقروء"),
                        header_close_button(close),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(width=44, height=5, bgcolor=Colors.BORDER_STRONG, border_radius=10),
                ft.Row([filter_row, count_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                list_column,
            ],
            spacing=14, tight=True,
        )
        sheet.content = ft.Container(
            body,
            padding=ft.padding.only(left=18, right=18, top=14, bottom=22),
            bgcolor=Colors.WHITE,
            border_radius=ft.border_radius.only(top_left=28, top_right=28),
            shadow=Shadow.LG,
        )
        render_list("all")
        self.page.open(sheet)

    def _alert_row(self, row: dict, *, on_click: Callable | None = None) -> ft.Container:
        color, bg, icon = SEVERITY_STYLE.get(row.get("severity", "info"), SEVERITY_STYLE["info"])
        unread = row.get("read_at") is None
        navigable = row.get("entity_type") in _ALERT_NAV
        return ft.Container(
            ft.Row(
                [
                    ft.Container(
                        ft.Icon(icon, size=18, color=color),
                        width=38, height=38, alignment=ft.alignment.center,
                        bgcolor=bg, border_radius=Radius.MD,
                    ),
                    ft.Column(
                        [
                            ft.Text(
                                str(row.get("title") or ""), size=13,
                                weight=ft.FontWeight.BOLD if unread else ft.FontWeight.W_500,
                                color=Colors.TEXT_PRIMARY,
                            ),
                            ft.Text(str(row.get("body") or ""), size=11, color=Colors.TEXT_SECONDARY),
                            ft.Text(self._relative_time(row.get("created_at")), size=9, color=Colors.TEXT_FAINT),
                        ],
                        spacing=2, expand=True,
                    ),
                    ft.Column(
                        [
                            ft.Container(width=8, height=8, border_radius=4, bgcolor=Colors.PRIMARY, visible=unread),
                            ft.Icon(ft.Icons.CHEVRON_LEFT_ROUNDED, size=16, color=Colors.TEXT_FAINT) if navigable else ft.Container(width=8, height=8),
                        ],
                        spacing=8, horizontal_alignment=ft.CrossAxisAlignment.END,
                    ),
                ],
                spacing=10, vertical_alignment=ft.CrossAxisAlignment.START,
            ),
            padding=12,
            bgcolor=Colors.PRIMARY_BG if unread else Colors.WHITE,
            border=ft.border.all(1, Colors.PRIMARY_BORDER if unread else Colors.BORDER_ALT),
            border_radius=Radius.MD,
            on_click=on_click,
            ink=bool(on_click),
        )

    # -- settings screen -----------------------------------------------------
    def show_settings(self) -> None:
        self._set_header("الإشعارات الذكية", "خصّص كل نوع تنبيه على حدة")
        cfg = self.ctx.notifications.get_config()
        field_refs: dict[str, ft.Control] = {}

        # Ask for Android 13+'s notification permission right here, not at
        # app launch -- a person opening notification settings has already
        # signaled they want alerts, so the system prompt has context instead
        # of appearing out of nowhere on first open.
        if self.native_files:
            self.page.run_task(self.native_files.request_notification_permission)

        # (seconds, label) -- "فورًا" keeps the original immediate check (app
        # stays open, only proves the notification channel itself works);
        # the rest register a one-off delayed test so the admin can close
        # the app and confirm delivery actually happens while it's not
        # running, which is what closed-app alerts depend on.
        _TEST_DELAY_OPTIONS = [
            ("0", "فورًا (والتطبيق مفتوح)"),
            ("30", "بعد 30 ثانية"),
            ("60", "بعد دقيقة واحدة"),
            ("300", "بعد 5 دقائق"),
        ]
        test_delay_dropdown = ft.Dropdown(
            width=190, value="30", dense=True, border_radius=Radius.SM,
            filled=True, bgcolor=Colors.BACKGROUND_ALT, border_color=Colors.BORDER,
            content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
            options=[ft.dropdown.Option(key=v, text=t) for v, t in _TEST_DELAY_OPTIONS],
        )

        def send_test_notification(_=None):
            if not self.native_files:
                # Desktop/dev preview -- there's no Android notification
                # panel to land in, so say so plainly instead of pretending
                # it worked.
                self.notify("الإشعارات الفعلية تعمل على أندرويد فقط")
                return

            delay_seconds = int(test_delay_dropdown.value or "0")

            async def _run():
                try:
                    if delay_seconds <= 0:
                        ok = await self.native_files.send_test_notification(
                            title="إشعار اختبار",
                            body="وصل هذا الإشعار بنجاح -- نظام التنبيهات يعمل.",
                        )
                        self.notify("تم إرسال إشعار الاختبار -- تحقق من لوحة الإشعارات" if ok else "تعذر إرسال إشعار الاختبار")
                    else:
                        ok = await self.native_files.schedule_test_notification(
                            delay_seconds=delay_seconds,
                            title="إشعار اختبار مؤجّل",
                            body="وصل هذا الإشعار بعد إغلاق التطبيق -- التنبيهات تعمل في الخلفية.",
                        )
                        if ok:
                            label = dict(_TEST_DELAY_OPTIONS).get(str(delay_seconds), f"{delay_seconds} ثانية")
                            self.notify(f"تمت الجدولة -- أغلق التطبيق الآن وانتظر ({label}) لترى الإشعار")
                        else:
                            self.notify("تعذر جدولة إشعار الاختبار")
                except Exception:
                    self.notify("تعذر إرسال إشعار الاختبار")

            self.page.run_task(_run)

        test_notification_card = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(ft.Icon(ft.Icons.NOTIFICATIONS_ACTIVE_OUTLINED, size=18, color=Colors.PRIMARY), width=36, height=36, alignment=ft.alignment.center, bgcolor=Colors.PRIMARY_BG, border_radius=Radius.MD),
                            ft.Column([ft.Text("تجربة الإشعارات", size=14, weight=ft.FontWeight.BOLD), ft.Text("اختر مدة، ثم أغلق التطبيق قبل انتهائها للتأكد من وصول الإشعار وأنت خارج التطبيق", size=11, color=Colors.TEXT_SECONDARY)], spacing=1, expand=True),
                        ],
                        spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row(
                        [test_delay_dropdown, ft.OutlinedButton("اختبار", icon=ft.Icons.SEND_OUTLINED, on_click=send_test_notification)],
                        spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=12,
            ),
            padding=14, bgcolor=Colors.WHITE, border=ft.border.all(1, Colors.BORDER), border_radius=Radius.LG, shadow=Shadow.SM,
        )


        def numeric_field(key: str, value, *, suffix: str, width: int = 90) -> ft.TextField:
            f = SelectAllTextField(
                value=str(value), suffix_text=suffix, width=width, text_align=ft.TextAlign.CENTER,
                keyboard_type=ft.KeyboardType.NUMBER, border_radius=Radius.SM, filled=True,
                bgcolor=Colors.BACKGROUND_ALT, border_color=Colors.BORDER, content_padding=ft.padding.symmetric(horizontal=10, vertical=8),
            )
            field_refs[key] = f
            return f

        def rule_card(key: str, title: str, description: str, icon: str, extra_row: ft.Control) -> ft.Container:
            rule = cfg.get(key, {})
            switch = ft.Switch(value=bool(rule.get("enabled", True)), active_color=Colors.PRIMARY)
            field_refs[f"{key}.enabled"] = switch
            return ft.Container(
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Container(ft.Icon(icon, size=18, color=Colors.PRIMARY), width=36, height=36, alignment=ft.alignment.center, bgcolor=Colors.PRIMARY_BG, border_radius=Radius.MD),
                                ft.Column([ft.Text(title, size=14, weight=ft.FontWeight.BOLD), ft.Text(description, size=11, color=Colors.TEXT_SECONDARY)], spacing=1, expand=True),
                                switch,
                            ],
                            spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        extra_row,
                    ],
                    spacing=12,
                ),
                padding=14, bgcolor=Colors.WHITE, border=ft.border.all(1, Colors.BORDER), border_radius=Radius.LG, shadow=Shadow.SM,
            )

        receivables_extra = ft.Row(
            [
                ft.Text("تذكير قبل التأخر بـ", size=12, color=Colors.TEXT_MUTED),
                numeric_field("receivables.remind_before_days", cfg["receivables"]["remind_before_days"], suffix="يوم"),
                ft.Text("تُعتبر متأخرة بعد", size=12, color=Colors.TEXT_MUTED),
                numeric_field("receivables.overdue_after_days", cfg["receivables"]["overdue_after_days"], suffix="يوم"),
            ],
            spacing=8, wrap=True,
        )
        low_stock_extra = ft.Row(
            [
                ft.Text("الحد الأدنى الافتراضي للكمية", size=12, color=Colors.TEXT_MUTED),
                numeric_field("low_stock.default_threshold", cfg["low_stock"]["default_threshold"], suffix="وحدة"),
            ],
            spacing=8, wrap=True,
        )
        backup_extra = ft.Row(
            [
                ft.Text("التذكير بعد", size=12, color=Colors.TEXT_MUTED),
                numeric_field("backup.remind_after_days", cfg["backup"]["remind_after_days"], suffix="يوم"),
            ],
            spacing=8, wrap=True,
        )
        license_extra = ft.Row(
            [
                ft.Text("التنبيه قبل الانتهاء بـ", size=12, color=Colors.TEXT_MUTED),
                numeric_field("license.remind_before_days", cfg["license"]["remind_before_days"], suffix="يوم"),
            ],
            spacing=8, wrap=True,
        )
        insights_extra = ft.Row(
            [
                ft.Text("نبّه إذا انخفضت المبيعات أكثر من", size=12, color=Colors.TEXT_MUTED),
                numeric_field("insights.drop_percent", cfg["insights"]["drop_percent"], suffix="%"),
            ],
            spacing=8, wrap=True,
        )

        quiet_switch = ft.Switch(value=bool(cfg["quiet_hours"]["enabled"]), active_color=Colors.PRIMARY)
        field_refs["quiet_hours.enabled"] = quiet_switch
        quiet_start = numeric_field("quiet_hours.start_hour", cfg["quiet_hours"]["start_hour"], suffix="س", width=70)
        quiet_end = numeric_field("quiet_hours.end_hour", cfg["quiet_hours"]["end_hour"], suffix="س", width=70)
        quiet_card = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(ft.Icon(ft.Icons.BEDTIME_OUTLINED, size=18, color=Colors.PURPLE), width=36, height=36, alignment=ft.alignment.center, bgcolor=Colors.PURPLE_BG, border_radius=Radius.MD),
                            ft.Column([ft.Text("ساعات الهدوء", size=14, weight=ft.FontWeight.BOLD), ft.Text("لا تُرسل تنبيهات غير عاجلة خلال هذا الوقت", size=11, color=Colors.TEXT_SECONDARY)], spacing=1, expand=True),
                            quiet_switch,
                        ],
                        spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Row([ft.Text("من الساعة", size=12, color=Colors.TEXT_MUTED), quiet_start, ft.Text("إلى", size=12, color=Colors.TEXT_MUTED), quiet_end], spacing=8),
                ],
                spacing=12,
            ),
            padding=14, bgcolor=Colors.WHITE, border=ft.border.all(1, Colors.BORDER), border_radius=Radius.LG, shadow=Shadow.SM,
        )

        daily_hour_field = numeric_field("daily_check_hour", cfg.get("daily_check_hour", 9), suffix="س", width=70)
        daily_hour_card = ft.Container(
            ft.Row(
                [
                    ft.Container(ft.Icon(ft.Icons.SCHEDULE_OUTLINED, size=18, color=Colors.PRIMARY), width=36, height=36, alignment=ft.alignment.center, bgcolor=Colors.PRIMARY_BG, border_radius=Radius.MD),
                    ft.Column([ft.Text("وقت الفحص اليومي", size=14, weight=ft.FontWeight.BOLD), ft.Text("أول فحص في اليوم يتمحور حول هذه الساعة تقريبًا عندما يكون التطبيق مغلقًا", size=11, color=Colors.TEXT_SECONDARY)], spacing=1, expand=True),
                    daily_hour_field,
                ],
                spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=14, bgcolor=Colors.WHITE, border=ft.border.all(1, Colors.BORDER), border_radius=Radius.LG, shadow=Shadow.SM,
        )

        cards = [
            rule_card("receivables", *_RULE_META[0][1:], receivables_extra),
            rule_card("low_stock", *_RULE_META[1][1:], low_stock_extra),
            rule_card("backup", *_RULE_META[2][1:], backup_extra),
            rule_card("license", *_RULE_META[3][1:], license_extra),
            rule_card("insights", *_RULE_META[4][1:], insights_extra),
            quiet_card,
            daily_hour_card,
            test_notification_card,
        ]

        def _int(key: str, fallback: int) -> int:
            try:
                return int(float(field_refs[key].value))
            except (TypeError, ValueError):
                return fallback

        def save(_=None):
            new_cfg = self.ctx.notifications.get_config()
            new_cfg["receivables"]["enabled"] = field_refs["receivables.enabled"].value
            new_cfg["receivables"]["remind_before_days"] = _int("receivables.remind_before_days", new_cfg["receivables"]["remind_before_days"])
            new_cfg["receivables"]["overdue_after_days"] = _int("receivables.overdue_after_days", new_cfg["receivables"]["overdue_after_days"])
            new_cfg["low_stock"]["enabled"] = field_refs["low_stock.enabled"].value
            new_cfg["low_stock"]["default_threshold"] = _int("low_stock.default_threshold", new_cfg["low_stock"]["default_threshold"])
            new_cfg["backup"]["enabled"] = field_refs["backup.enabled"].value
            new_cfg["backup"]["remind_after_days"] = _int("backup.remind_after_days", new_cfg["backup"]["remind_after_days"])
            new_cfg["license"]["enabled"] = field_refs["license.enabled"].value
            new_cfg["license"]["remind_before_days"] = _int("license.remind_before_days", new_cfg["license"]["remind_before_days"])
            new_cfg["insights"]["enabled"] = field_refs["insights.enabled"].value
            new_cfg["insights"]["drop_percent"] = _int("insights.drop_percent", new_cfg["insights"]["drop_percent"])
            new_cfg["quiet_hours"]["enabled"] = field_refs["quiet_hours.enabled"].value
            new_cfg["quiet_hours"]["start_hour"] = _int("quiet_hours.start_hour", new_cfg["quiet_hours"]["start_hour"])
            new_cfg["quiet_hours"]["end_hour"] = _int("quiet_hours.end_hour", new_cfg["quiet_hours"]["end_hour"])
            new_cfg["daily_check_hour"] = max(0, min(23, _int("daily_check_hour", new_cfg.get("daily_check_hour", 9))))
            self.ctx.notifications.save_config(new_cfg)
            self.refresh_badge()
            self._sync_background_notifications()
            self.notify("تم حفظ إعدادات الإشعارات")

        self.content.content = ft.Column(
            [
                ft.Text(
                    "كل نوع تنبيه يعتمد على بياناتك الحالية مباشرة (الفواتير، المخزون، الترخيص) — بدون أي اتصال إضافي بالإنترنت.",
                    size=11, color=Colors.TEXT_SECONDARY,
                ),
                *cards,
                ft.FilledButton("حفظ الإعدادات", icon=ft.Icons.SAVE_OUTLINED, on_click=save),
            ],
            spacing=12, scroll=ft.ScrollMode.AUTO, expand=True,
        )
        self.content.update()


__all__ = ["NotificationCenter"]
