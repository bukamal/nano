from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import flet as ft
from flet_native_files import NativeFiles

from nano_offline.app_context import AppContext
from nano_offline.core.invoice_signing import verify_payload
from nano_offline.core import backup_settings
from nano_offline.core import sound
from nano_offline.core.paths import database_path, migrate_legacy_database
from nano_offline.core.toast import toast
from nano_offline.views.activation_view import ActivationGate
from nano_offline.views.admin_view import AdminCenter
from nano_offline.views.dashboard_view import DashboardCenter
from nano_offline.views.finance_view import FinanceCenter
from nano_offline.views.invoice_view import InvoiceCenter
from nano_offline.views.items_view import ItemsCenter
from nano_offline.views.login_view import LoginGate
from nano_offline.views.notifications_view import NotificationCenter
from nano_offline.views.parties_view import PartyCenter
from nano_offline.views.pos_view import POSCenter
from nano_offline.views.reports_view import ReportsCenter
from nano_offline.views.security_view import SecurityCenter
from nano_offline.views.splash_view import SplashGate
from nano_offline.views.stocktake_view import StocktakeCenter
from nano_offline.core import theme
from nano_offline.core import theme_settings
from nano_offline.core.theme import Colors, Shadow

APP_DB = database_path()
LEGACY_APP_DB = next((p for p in [Path(__file__).resolve().parent.parent / "data" / "nano.db", Path(__file__).resolve().parent.parent / "data" / "qeid.db"] if p.exists()), Path(__file__).resolve().parent.parent / "data" / "nano.db")

# Optional bundled Arabic typeface. Fully offline (no external font URLs, to
# respect the app's offline-first design) — activates automatically once the
# .ttf files are placed in assets/fonts/, and is a complete no-op otherwise.
# See assets/fonts/README.md for the two files needed and where to get them.
_FONTS_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
_CUSTOM_FONTS = {
    "Plex": "fonts/IBMPlexSansArabic-Regular.ttf",
    "Plex SemiBold": "fonts/IBMPlexSansArabic-SemiBold.ttf",
}
APP_FONTS = {name: rel for name, rel in _CUSTOM_FONTS.items() if (_FONTS_DIR / Path(rel).name).exists()}
APP_FONT_FAMILY = "Plex" if "Plex" in APP_FONTS else None


def _resolve_and_set_theme(page: ft.Page, ctx: AppContext) -> str:
    """Read the stored night-mode preference/schedule and apply it to ``theme``.

    Returns the resolved mode ("light"/"dark") so callers can tell whether
    anything actually changed. ``page.platform_brightness`` is what Flet
    exposes for "what is the OS currently set to" -- wrapped in try/except
    since it isn't populated on every platform/Flet version, in which case
    "system" preference just degrades to light rather than raising.
    """
    try:
        system_dark = page.platform_brightness == ft.Brightness.DARK
    except Exception:
        system_dark = False
    effective = theme_settings.resolve_effective_mode(ctx.settings, system_is_dark=system_dark)
    theme.set_mode(effective)
    return effective


def _apply_theme(page: ft.Page) -> None:
    """Set page.theme/dark_theme with the brand seed color, current mode, and font."""
    if APP_FONTS:
        page.fonts = APP_FONTS
    page.theme = ft.Theme(color_scheme_seed=Colors.PRIMARY, font_family=APP_FONT_FAMILY)
    page.dark_theme = page.theme
    page.theme_mode = ft.ThemeMode.DARK if theme.is_dark() else ft.ThemeMode.LIGHT


def build_shell(page: ft.Page, ctx: AppContext, *, on_logout, native_files: NativeFiles, on_theme_changed):
    page.title = "Nano | نانو"
    page.rtl = True
    _apply_theme(page)
    page.padding = 0
    page.bgcolor = Colors.BACKGROUND

    async def _auto_backup_if_overdue():
        # Best-effort, fire-and-forget, same pattern as the background
        # notification sync in main() below -- runs once per login/session
        # open (build_shell is only ever called from there), never blocks
        # the shell from rendering, and does nothing unless the admin has
        # explicitly opted in via backup_settings.auto_backup_enabled.
        try:
            if not backup_settings.auto_backup_enabled(ctx.settings):
                return
            cfg = ctx.notifications.get_config().get("backup", {})
            if not bool(cfg.get("enabled", True)):
                return
            remind_after = int(cfg.get("remind_after_days", 7))
            last_raw = ctx.notifications.settings.get("last_backup_at", "")
            if last_raw:
                days_since = (datetime.now().astimezone() - datetime.fromisoformat(last_raw).astimezone()).days
                if days_since < remind_after:
                    return
            backups_dir = ctx.db.path.parent / "backups"
            backups_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target = backups_dir / f"auto_backup_{stamp}.nanobackup"
            await asyncio.to_thread(ctx.backup.create_backup, target)
            ctx.notifications.record_backup_completed()
            keep = backup_settings.retention_count(ctx.settings)
            if keep > 0:
                await asyncio.to_thread(ctx.backup.prune_backups, backups_dir, keep)
        except Exception:
            pass

    page.run_task(_auto_backup_if_overdue)

    content = ft.Container(
        expand=True,
        padding=ft.padding.only(left=18, right=18, top=14, bottom=18),
        opacity=1,
        animate_opacity=180,
    )

    header_title = ft.Text("لوحة التحكم", size=22, weight=ft.FontWeight.BOLD, color=Colors.TEXT_PRIMARY)
    header_subtitle = ft.Text("نظرة عامة على أداء عملك", size=12, color=Colors.TEXT_SECONDARY)

    def set_header(title: str, subtitle: str = "") -> None:
        header_title.value = title
        header_subtitle.value = subtitle

    def notify(text: str):
        toast(page, text)

    notification_center = NotificationCenter(
        page, ctx, content, native_files=native_files, on_title_change=set_header,
        on_navigate=lambda key: navigate(key),
    )

    bell_button = ft.Container(
        ft.Stack(
            [
                ft.Container(
                    ft.Icon(ft.Icons.NOTIFICATIONS_NONE_ROUNDED, color=Colors.TEXT_SECONDARY, size=22),
                    width=42, height=42, alignment=ft.alignment.center,
                ),
                ft.Container(notification_center.badge, right=4, top=4),
            ],
        ),
        width=42,
        height=42,
        alignment=ft.alignment.center,
        border=ft.border.all(1, Colors.BORDER),
        border_radius=14,
        bgcolor=Colors.WHITE,
        shadow=Shadow.SM,
        ink=True,
        on_click=notification_center.open_panel,
    )

    top_bar = ft.Container(
        ft.Row(
            [
                ft.Column([header_title, header_subtitle], spacing=1, expand=True),
                bell_button,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.symmetric(horizontal=18, vertical=12),
        bgcolor=Colors.WHITE,
        border=ft.border.only(bottom=ft.BorderSide(1, Colors.BORDER)),
    )

    invoice_center = InvoiceCenter(page, ctx, content, native_files=native_files, on_title_change=set_header)
    pos_center = POSCenter(
        page, ctx, content, native_files=native_files, on_title_change=set_header,
        on_create_item=lambda code: open_items_for_new(code),
        on_fullscreen_enter=lambda: pos_fullscreen_enter(),
        on_fullscreen_exit=lambda: pos_fullscreen_exit(),
    )
    finance_center = FinanceCenter(page, ctx, content, native_files=native_files, on_title_change=set_header)
    reports_center = ReportsCenter(page, ctx, content, native_files=native_files, on_title_change=set_header)
    admin_center = AdminCenter(page, ctx, content, on_logout=on_logout, native_files=native_files, on_theme_changed=on_theme_changed)
    party_center = PartyCenter(page, ctx, content, native_files=native_files, on_title_change=set_header)
    items_center = ItemsCenter(
        page, ctx, content, native_files=native_files, on_title_change=set_header,
        on_open_stocktake=lambda: stocktake_center.show_center(),
    )
    stocktake_center = StocktakeCenter(
        page, ctx, content, native_files=native_files, on_title_change=set_header,
        on_exit=lambda: navigate("items"),
    )
    security_center = SecurityCenter(page, ctx, content, on_title_change=set_header)
    # DashboardCenter needs navigate()/open_sale()/open_purchase(), which are
    # defined further below in this same function. The lambdas below only
    # resolve those names at click-time, once the whole shell is built — the
    # same late-binding the previous inline closures relied on.
    dashboard_center = DashboardCenter(
        page, ctx, content,
        on_title_change=set_header,
        on_navigate=lambda key: navigate(key),
        on_open_sale=lambda: open_sale(),
        on_open_purchase=lambda: open_purchase(),
        on_open_notifications=notification_center.open_panel,
    )
    session = ctx.auth.current()
    if session is None:
        raise RuntimeError("لا توجد جلسة مستخدم")

    page_meta = {
        "dashboard": ("لوحة التحكم", "نظرة عامة على أداء عملك"),
        "items": ("المواد", "إدارة المخزون والخدمات والتصنيفات والوحدات"),
        "customers": ("العملاء", "إدارة العملاء والذمم المدينة"),
        "suppliers": ("الموردون", "إدارة الموردين والذمم الدائنة"),
        "invoices": ("الفواتير", "المبيعات والمشتريات وحالات السداد"),
        "finance": ("المالية", "السندات والمصروفات والحركات المالية"),
        "reports": ("التقارير", "التقارير المالية والمخزون والربحية"),
        "security": ("الأمان والدخول", "PIN والنمط والجلسات المحفوظة"),
        "admin": ("الإدارة", "المستخدمون والنسخ الاحتياطية والترخيص"),
    }

    actions = {
        "dashboard": dashboard_center.show_center,
        "items": items_center.show_center,
        "customers": lambda: party_center.show_center(ctx.customers, "العملاء"),
        "suppliers": lambda: party_center.show_center(ctx.suppliers, "الموردون"),
        "invoices": invoice_center.show_center,
        "finance": finance_center.show_center,
        "reports": reports_center.show_center,
        "security": security_center.show_center,
        "admin": admin_center.show_center,
    }

    icon_map = {
        "dashboard": ft.Icons.HOME_OUTLINED,
        "items": ft.Icons.INVENTORY_2_OUTLINED,
        "customers": ft.Icons.PEOPLE_OUTLINE,
        "suppliers": ft.Icons.LOCAL_SHIPPING_OUTLINED,
        "invoices": ft.Icons.RECEIPT_LONG_OUTLINED,
        "finance": ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED,
        "reports": ft.Icons.QUERY_STATS_OUTLINED,
        "security": ft.Icons.LOCK_OUTLINE,
        "admin": ft.Icons.ADMIN_PANEL_SETTINGS_OUTLINED,
    }
    label_map = {k: v[0] for k, v in page_meta.items()}
    allowed_keys = [k for k in actions if session.can(k)]
    selected_key = {"value": "dashboard"}
    sidebar_buttons: dict[str, ft.Container] = {}
    mobile_buttons: dict[str, tuple[ft.Container, ft.Icon, ft.Text]] = {}

    def refresh_navigation_state() -> None:
        current = selected_key["value"]
        for key, button in sidebar_buttons.items():
            active = key == current
            button.bgcolor = Colors.PRIMARY_BG if active else None
            button.border = ft.border.all(1, Colors.PRIMARY_BORDER) if active else None
            row = button.content
            if isinstance(row, ft.Row):
                for ctrl in row.controls:
                    if isinstance(ctrl, ft.Icon):
                        ctrl.color = Colors.PRIMARY if active else Colors.TEXT_SECONDARY
                    elif isinstance(ctrl, ft.Text):
                        ctrl.color = Colors.PRIMARY if active else Colors.TEXT_MUTED_DARK
        for key, (box, icon, label) in mobile_buttons.items():
            active = key == current
            icon.color = Colors.PRIMARY if active else Colors.TEXT_FAINT
            label.color = Colors.PRIMARY if active else Colors.TEXT_SECONDARY
            label.weight = ft.FontWeight.BOLD if active else ft.FontWeight.W_500
            box.bgcolor = Colors.PRIMARY_BG if active else None

    def navigate(key: str) -> None:
        action = actions.get(key)
        if action is None:
            return
        if key not in allowed_keys:
            notify(f"لا تملك صلاحية الوصول إلى «{label_map.get(key, key)}»")
            return
        selected_key["value"] = key
        title, subtitle = page_meta[key]
        set_header(title, subtitle)
        refresh_navigation_state()
        # Cross-fade: hide the outgoing view *before* the target's
        # show_center() swaps content.content in (it also calls
        # page.update() itself), so the new view first appears at
        # opacity 0, then we fade it in with one more update(). No
        # asyncio/sleep involved — this is Flet's built-in implicit
        # animation (animate_opacity on the container), so there's no
        # timing to get wrong: worst case it simply doesn't animate.
        content.opacity = 0
        try:
            action()
        except Exception as exc:
            # Never leave the shell stuck at opacity 0 if a view fails to build.
            content.opacity = 1
            try:
                content.update()
            except Exception:
                pass
            notify(f"تعذر فتح القسم: {exc}", kind="error")
            return
        content.opacity = 1
        content.update()
        notification_center.refresh_badge()

    # Android hardware back button: by default, with no route/view stack
    # pushed (this shell swaps `content` manually via navigate() instead
    # of using page.views), Flutter's root Navigator has nothing to pop,
    # so the OS treats back as "exit the app" -- one accidental back-press
    # from any section would kill Nano entirely. `page.window.prevent_close`
    # intercepts that close intent instead of letting it through: while any
    # non-dashboard section is open (including the "sale"/"purchase"/"pos"
    # quick-entry screens, which aren't in page_meta/actions but still set
    # selected_key), back sends the user to the dashboard, exactly like
    # tapping the "الرئيسية" sidebar/tab button. Only a second back-press
    # from the dashboard itself actually closes the app. Desktop builds get
    # the same behavior for free (there it's the window's close button).
    page.window.prevent_close = True

    def handle_window_event(e: ft.WindowEvent) -> None:
        if e.type != ft.WindowEventType.CLOSE:
            return
        if selected_key["value"] != "dashboard":
            navigate("dashboard")
            return
        # `page.window.close()` (the previous call here) re-enters the
        # same prevent_close-gated close intent this handler exists to
        # intercept in the first place. On desktop that's fine -- with
        # prevent_close now False it lets the real OS window close --
        # but on Android there is no actual platform "window" behind an
        # Activity, so close() quietly does nothing there. The visible
        # symptom is exactly what was reported: back always lands you
        # on the dashboard and a second press just... doesn't exit.
        # os._exit() forcibly kills this process instead, which is what
        # "exit the app" has to mean on Android, and still exits desktop
        # builds the same way (there's no further UI to unwind at this
        # point, so a hard exit is fine).
        import os

        os._exit(0)

    page.window.on_event = handle_window_event

    def open_sale(_=None) -> None:
        if not session.can("invoices"):
            notify("لا تملك صلاحية الفواتير")
            return
        selected_key["value"] = "sale"
        set_header("فاتورة بيع", "إنشاء فاتورة بيع جديدة — النقدي افتراضيًا")
        refresh_navigation_state()
        content.opacity = 0
        invoice_center.show_editor(None, "sale")
        content.opacity = 1
        content.update()

    def open_purchase(_=None) -> None:
        if not session.can("invoices"):
            notify("لا تملك صلاحية الفواتير")
            return
        selected_key["value"] = "purchase"
        set_header("فاتورة شراء", "إنشاء فاتورة شراء جديدة — النقدي افتراضيًا")
        refresh_navigation_state()
        content.opacity = 0
        invoice_center.show_editor(None, "purchase")
        content.opacity = 1
        content.update()

    def open_pos(_=None) -> None:
        if not session.can("invoices"):
            notify("لا تملك صلاحية الفواتير")
            return
        selected_key["value"] = "pos"
        refresh_navigation_state()
        content.opacity = 0
        pos_center.show_center()
        content.opacity = 1
        content.update()

    def open_items_for_new(barcode_code: str) -> None:
        if not session.can("items"):
            notify("لا تملك صلاحية المواد")
            return
        selected_key["value"] = "items"
        title, subtitle = page_meta["items"]
        set_header(title, subtitle)
        refresh_navigation_state()
        content.opacity = 0
        items_center.show_center(prefill_barcode=barcode_code)
        content.opacity = 1
        content.update()

    def nav_button(key: str, label: str, icon, on_click):
        icon_ctrl = ft.Icon(icon, size=21, color=Colors.TEXT_SECONDARY)
        text_ctrl = ft.Text(label, size=13, weight=ft.FontWeight.W_600, color=Colors.TEXT_MUTED_DARK, expand=True)
        box = ft.Container(
            ft.Row([icon_ctrl, text_ctrl, ft.Icon(ft.Icons.CHEVRON_LEFT, size=15, color=Colors.BORDER_STRONG)], spacing=12),
            padding=ft.padding.symmetric(horizontal=14, vertical=12),
            border_radius=14,
            on_click=on_click,
            ink=True,
        )
        if key in actions:
            sidebar_buttons[key] = box
        return box

    sidebar_controls: list[ft.Control] = []
    for key in allowed_keys:
        sidebar_controls.append(nav_button(key, label_map[key], icon_map[key], lambda _, k=key: navigate(k)))
        if key == "items" and session.can("invoices"):
            sidebar_controls.append(nav_button("pos", "نقطة البيع", ft.Icons.POINT_OF_SALE, open_pos))
            sidebar_controls.append(nav_button("sale", "فاتورة بيع", ft.Icons.SHOPPING_CART_CHECKOUT, open_sale))
            sidebar_controls.append(nav_button("purchase", "فاتورة شراء", ft.Icons.ADD_SHOPPING_CART, open_purchase))

    avatar_text = "".join(part[:1] for part in (session.full_name or session.username).split()[:2]).upper() or "N"
    sidebar = ft.Container(
        ft.Column(
            [
                ft.Container(
                    ft.Row(
                        [
                            ft.Image(src="icon.png", width=48, height=48, fit=ft.ImageFit.CONTAIN),
                            ft.Column([ft.Text("Nano | نانو", size=19, weight=ft.FontWeight.BOLD, color=Colors.TEXT_PRIMARY), ft.Text("نظام المحاسبة الذكي", size=10, color=Colors.TEXT_SECONDARY)], spacing=1, expand=True),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.padding.only(left=18, right=18, top=18, bottom=14),
                    border=ft.border.only(bottom=ft.BorderSide(1, Colors.BORDER)),
                ),
                ft.Container(ft.Column(sidebar_controls, spacing=5, scroll=ft.ScrollMode.AUTO), padding=12, expand=True),
                ft.Container(
                    ft.Row(
                        [
                            ft.Container(ft.Text(avatar_text, color=Colors.WHITE, weight=ft.FontWeight.BOLD), width=40, height=40, alignment=ft.alignment.center, bgcolor=Colors.PRIMARY, border_radius=14),
                            ft.Column([ft.Text(session.full_name, size=12, weight=ft.FontWeight.BOLD), ft.Text(session.username, size=10, color=Colors.TEXT_SECONDARY)], spacing=1, expand=True),
                            ft.IconButton(icon=ft.Icons.LOGOUT, tooltip="تسجيل الخروج", icon_color=Colors.TEXT_SECONDARY, on_click=lambda _: on_logout()),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=12,
                    border=ft.border.only(top=ft.BorderSide(1, Colors.BORDER)),
                ),
            ],
            spacing=0,
            expand=True,
        ),
        width=280,
        bgcolor=Colors.WHITE,
        border=ft.border.only(left=ft.BorderSide(1, Colors.BORDER)),
        shadow=Shadow.LG,
        visible=False,
    )

    body = ft.Column([top_bar, content], spacing=0, expand=True)

    def mobile_item(key: str, label: str, icon_data, on_click):
        icon = ft.Icon(icon_data, size=23, color=Colors.TEXT_FAINT)
        label_ctrl = ft.Text(label, size=10, color=Colors.TEXT_SECONDARY, text_align=ft.TextAlign.CENTER)
        box = ft.Container(
            ft.Column([icon, label_ctrl], spacing=3, horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER),
            width=62, height=58, alignment=ft.alignment.center, border_radius=15, on_click=on_click, ink=True,
        )
        mobile_buttons[key] = (box, icon, label_ctrl)
        return box

    sale_fab = ft.Container(
        ft.Column(
            [
                ft.Container(
                    ft.Icon(ft.Icons.SHOPPING_CART_CHECKOUT, color=Colors.WHITE, size=25),
                    width=58, height=58, alignment=ft.alignment.center,
                    gradient=ft.LinearGradient(colors=[Colors.PRIMARY, Colors.PURPLE_LIGHT], begin=ft.alignment.top_left, end=ft.alignment.bottom_right),
                    border_radius=30,
                    border=ft.border.all(4, Colors.BACKGROUND),
                    shadow=ft.BoxShadow(blur_radius=20, spread_radius=1, color=Colors.PRIMARY_BORDER, offset=ft.Offset(0, 7)),
                ),
                ft.Text("بيع سريع", size=10, color=Colors.PRIMARY, weight=ft.FontWeight.BOLD),
            ],
            spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        width=72, height=78, margin=ft.margin.only(top=-25), on_click=open_pos, ink=True, border_radius=30,
    )

    more_sheet = ft.BottomSheet(content=ft.Container())

    def _show_verify_result(is_valid: bool, reason: str) -> None:
        # Same dismiss-it-yourself AlertDialog pattern used elsewhere in the
        # app (see admin_view._notify_error) -- a tamper warning must not be
        # missable behind an auto-dismissing SnackBar.
        result_dialog = ft.AlertDialog(
            modal=True,
            icon=ft.Icon(
                ft.Icons.CHECK_CIRCLE if is_valid else ft.Icons.ERROR_OUTLINE,
                color=Colors.SUCCESS if is_valid else Colors.DANGER,
                size=42,
            ),
            title=ft.Text(
                "الفاتورة أصلية" if is_valid else "تحذير تلاعب",
                text_align=ft.TextAlign.CENTER,
            ),
            content=ft.Text(reason, text_align=ft.TextAlign.CENTER),
            actions=[ft.FilledButton("حسنًا", on_click=lambda _: page.close(result_dialog))],
            actions_alignment=ft.MainAxisAlignment.CENTER,
        )
        page.open(result_dialog)

    async def _verify_invoice_scan() -> None:
        # "تحقق من فاتورة" is the only "المزيد" entry that hands off to a
        # native Android camera activity right after closing more_sheet --
        # every other entry (فاتورة تفصيلية/شراء/navigate) stays inside
        # Flet/Flutter, so there's nothing racing the sheet's own close
        # animation. Here, the tap fires page.close(more_sheet) then
        # immediately launches the native scanner intent; if the sheet's
        # close update hasn't finished reaching the client before the
        # native activity steals focus, that update can get dropped, so
        # the sheet still looks open on return and the tap has to be
        # repeated. A brief pause lets the close animation land first.
        await asyncio.sleep(0.25)
        try:
            payload = await native_files.scan_barcode()
        except RuntimeError as e:
            toast(page, str(e))
            return
        if not payload:
            return  # user backed out of the scanner -- not an error
        is_valid, reason = verify_payload(ctx.db, payload)
        _show_verify_result(is_valid, reason)

    def open_verify_invoice(_=None) -> None:
        page.run_task(_verify_invoice_scan)

    def show_more(_=None):
        entries: list[tuple[str, str, object, object]] = []
        if session.can("invoices"):
            entries.append(("sale", "فاتورة تفصيلية", ft.Icons.RECEIPT_LONG_OUTLINED, lambda _: (page.close(more_sheet), open_sale())))
            entries.append(("purchase", "شراء", ft.Icons.ADD_SHOPPING_CART, lambda _: (page.close(more_sheet), open_purchase())))
            entries.append(("verify", "تحقق من فاتورة", ft.Icons.QR_CODE_SCANNER_OUTLINED, lambda _: (page.close(more_sheet), open_verify_invoice())))
        for key in ["customers", "suppliers", "finance", "reports", "security", "admin"]:
            if key in allowed_keys:
                entries.append((key, label_map[key], icon_map[key], lambda _, k=key: (page.close(more_sheet), navigate(k))))

        cards = []
        for key, label, icon_data, action in entries:
            cards.append(
                ft.Container(
                    ft.Column(
                        [
                            ft.Container(ft.Icon(icon_data, color=Colors.PRIMARY, size=24), width=48, height=48, alignment=ft.alignment.center, bgcolor=Colors.PRIMARY_BG, border_radius=16),
                            ft.Text(label, size=12, weight=ft.FontWeight.W_600, text_align=ft.TextAlign.CENTER),
                        ],
                        spacing=7, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    col={"xs": 4}, padding=9, border_radius=18, on_click=action, ink=True,
                )
            )
        more_sheet.content = ft.Container(
            ft.Column(
                [
                    ft.Container(width=44, height=5, bgcolor=Colors.BORDER_STRONG, border_radius=10, alignment=ft.alignment.center),
                    ft.Text("المزيد", size=20, weight=ft.FontWeight.BOLD),
                    ft.Text("الوصول السريع إلى بقية أقسام Nano", size=11, color=Colors.TEXT_SECONDARY),
                    ft.ResponsiveRow(cards, spacing=8, run_spacing=8),
                    ft.OutlinedButton("تسجيل الخروج", icon=ft.Icons.LOGOUT, on_click=lambda _: (page.close(more_sheet), on_logout()), width=260),
                ],
                spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.only(left=18, right=18, top=12, bottom=24),
            bgcolor=Colors.WHITE,
            border_radius=ft.border_radius.only(top_left=28, top_right=28),
            shadow=Shadow.LG,
        )
        page.open(more_sheet)

    mobile_bar = ft.Container(
        ft.Row(
            [
                mobile_item("dashboard", "الرئيسية", ft.Icons.HOME_OUTLINED, lambda _: navigate("dashboard")),
                mobile_item("items", "المواد", ft.Icons.INVENTORY_2_OUTLINED, lambda _: navigate("items")),
                sale_fab,
                mobile_item("invoices", "الفواتير", ft.Icons.RECEIPT_LONG_OUTLINED, lambda _: navigate("invoices")),
                mobile_item("more", "المزيد", ft.Icons.MORE_HORIZ, show_more),
            ],
            alignment=ft.MainAxisAlignment.SPACE_AROUND,
            vertical_alignment=ft.CrossAxisAlignment.END,
        ),
        height=78,
        padding=ft.padding.only(left=5, right=5, top=7, bottom=5),
        bgcolor=Colors.WHITE,
        border=ft.border.only(top=ft.BorderSide(1, Colors.BORDER)),
        shadow=ft.BoxShadow(blur_radius=20, color=Colors.BORDER, offset=ft.Offset(0, -5)),
    )

    # The v0.8 shell intentionally replaces the old NavigationRail / NavigationBar
    # with a branded desktop sidebar and a five-action mobile bottom bar.
    main_row = ft.Row([sidebar, body], expand=True, spacing=0)
    root = ft.Column([main_row, mobile_bar], expand=True, spacing=0)
    page.add(ft.SafeArea(root, expand=True))

    _pos_fullscreen = {"value": False}

    def adapt_navigation(_=None):
        if _pos_fullscreen["value"]:
            # A resize (e.g. tablet rotation) mid-sale must not pop the
            # sidebar/tab bar back over the sale screen -- pos_fullscreen_exit()
            # is the only path back to normal chrome.
            return
        desktop = bool(page.width and page.width >= 900)
        sidebar.visible = desktop
        mobile_bar.visible = not desktop
        content.padding = ft.padding.only(left=24 if desktop else 16, right=24 if desktop else 16, top=18 if desktop else 12, bottom=24 if desktop else 16)
        page.update()

    # POS fullscreen: hides *every* piece of the app's own chrome (top
    # header, desktop sidebar, mobile tab bar) so the sale screen owns the
    # whole viewport edge-to-edge, kiosk-style. adapt_navigation() already
    # knows how to correctly re-derive sidebar/mobile_bar/padding for the
    # current width, so exiting just re-runs it instead of duplicating that
    # logic here.
    def pos_fullscreen_enter():
        _pos_fullscreen["value"] = True
        top_bar.visible = False
        sidebar.visible = False
        mobile_bar.visible = False
        content.padding = ft.padding.all(0)
        page.update()

    def pos_fullscreen_exit():
        _pos_fullscreen["value"] = False
        top_bar.visible = True
        adapt_navigation()
        navigate("dashboard")

    page.on_resize = adapt_navigation
    navigate("dashboard")
    adapt_navigation()



def main(page: ft.Page):
    migrate_legacy_database(LEGACY_APP_DB, APP_DB)
    ctx = AppContext.create(APP_DB)
    native_files = NativeFiles()
    page.overlay.append(native_files)
    # Lets core/sound.py's play() -- invoked from inside toast(), which only
    # ever receives `page` -- read sound settings and reach the native
    # AudioPool bridge (native_files.play_sound) without threading them
    # through every one of the ~50 existing toast()/notify() call sites.
    # Set once here, before login/activation screens even build, so every
    # toast in the app (including pre-login ones) gets sound from the start.
    # Must come after `native_files` exists -- attach_context() stores that
    # exact instance, and it needs to already be mounted in page.overlay
    # for invoke_method_async to reach anything on the Dart side.
    sound.attach_context(page, ctx, native_files)

    async def _preload_sound_pools():
        # Best-effort: warms up the four native AudioPools (see
        # extensions/flet_native_files' sound_pool.dart) so the very first
        # toast of the session doesn't pay the one-time asset-decode delay
        # before it can play its tone. Never blocks or fails app startup --
        # sound.play() itself triggers the same load lazily if this hasn't
        # finished yet by the time the first toast fires.
        try:
            await native_files.init_sound()
        except Exception:
            pass

    page.run_task(_preload_sound_pools)

    async def _sync_background_notifications():
        # Best-effort: registers/refreshes the Android WorkManager check that
        # can alert the user while Nano itself isn't running (see
        # NotificationService.native_schedule_payload and
        # flet_native_files' schedule_notifications). Never blocks or fails
        # app startup -- the in-app bell/alerts already work independently
        # of this, on iOS/desktop/web this call is just a no-op.
        try:
            await native_files.schedule_notifications(**ctx.notifications.native_schedule_payload())
        except Exception:
            pass

    page.run_task(_sync_background_notifications)

    page.title = "Nano | نانو"
    page.rtl = True
    _resolve_and_set_theme(page, ctx)
    _apply_theme(page)
    page.padding = 0
    page.bgcolor = Colors.BACKGROUND

    # Which top-level screen is currently mounted -- only "shell" needs a
    # full teardown/rebuild when the theme changes mid-session (the other
    # screens are gates that already call reset_page(), which re-syncs the
    # theme, on their own next transition).
    current_screen = {"value": "splash"}

    def reset_page():
        _resolve_and_set_theme(page, ctx)
        _apply_theme(page)
        page.controls.clear()
        page.navigation_bar = None
        page.update()

    def open_shell():
        current_screen["value"] = "shell"
        reset_page()
        build_shell(page, ctx, on_logout=logout, native_files=native_files, on_theme_changed=open_shell)

    def handle_brightness_change(_=None):
        # Best-effort: only matters at all for users on "تلقائي حسب النظام"
        # (system) with no active dark schedule -- resolve_effective_mode()
        # already ignores this for an explicit light/dark preference or a
        # schedule window in effect. Only pay for a full shell rebuild if
        # the resolved mode actually flipped.
        before = theme.get_mode()
        after = _resolve_and_set_theme(page, ctx)
        if after == before:
            return
        _apply_theme(page)
        if current_screen["value"] == "shell":
            open_shell()
        else:
            page.update()

    try:
        page.on_platform_brightness_change = handle_brightness_change
    except Exception:
        pass

    def logout():
        # Undo the shell's back-button interception (see build_shell's
        # handle_window_event) before tearing it down -- otherwise
        # page.window.on_event would keep pointing at a handler closed
        # over this session's now-discarded navigate()/selected_key,
        # and back-press on the login screen would silently do nothing
        # instead of its normal "exit app" behavior.
        page.window.prevent_close = False
        ctx.auth.logout()
        show_auth()

    def notify(text: str):
        toast(page, text)

    def show_activation():
        current_screen["value"] = "activation"
        reset_page()
        ActivationGate(page, ctx, on_success=show_auth).show()

    def show_auth():
        current_screen["value"] = "auth"
        reset_page()
        LoginGate(page, ctx, on_success=open_shell).show()

    def route_after_splash():
        # Decided here, once the splash's minimum on-screen beat has
        # elapsed, rather than before showing it -- so the very first
        # thing painted is always the branded splash, and *then* it hands
        # off to whichever of activation/login/shell actually applies,
        # never the other way around.
        reset_page()
        if ctx.license.status().valid:
            if ctx.auth.has_users() and ctx.auth.restore_saved_session() is not None:
                open_shell()
            else:
                show_auth()
        else:
            show_activation()

    SplashGate(page, on_ready=route_after_splash).show()


ft.app(target=main)
