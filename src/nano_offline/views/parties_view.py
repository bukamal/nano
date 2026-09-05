from __future__ import annotations

import flet as ft

from nano_offline.core.toast import toast

from nano_offline.components import SelectAllTextField, empty_state, new_form_sheet, render_form_sheet
from nano_offline.core.theme import Colors, Shadow
from nano_offline.core import currency


class PartyCenter:
    """Shared customer/supplier list, search, detail dialog, add/edit/delete.

    A single instance is reused for both customers and suppliers; the
    repository and title are passed to :meth:`show_center` per navigation.
    Extracted from ``main.py`` (previously the inline ``party_view`` closure).
    """

    def __init__(self, page: ft.Page, ctx, content: ft.Container, *, native_files=None, on_title_change=None):
        self.page = page
        self.ctx = ctx
        self.content = content
        self.native_files = native_files
        self.on_title_change = on_title_change

    def _set_header(self, title: str, subtitle: str = "") -> None:
        if self.on_title_change:
            self.on_title_change(title, subtitle)

    def money(self, value) -> str:
        return currency.format_amount(value, self.ctx.settings)

    def notify(self, text: str, kind: str | None = None, sound_kind: str | None = None) -> None:
        toast(self.page, text, kind=kind, sound_kind=sound_kind)

    def show_center(self, repo, title: str) -> None:
        page = self.page
        content = self.content
        notify = self.notify
        money = self.money
        is_customer = repo.table == "customers"
        singular = "العميل" if is_customer else "المورد"
        self._set_header(title, f"إدارة بيانات {title} والحسابات المرتبطة")
        search = SelectAllTextField(
            label=f"بحث في {title}",
            hint_text=f"الاسم أو الهاتف",
            prefix_icon=ft.Icons.SEARCH,
            expand=True,
        )
        rows = ft.Column(spacing=9)
        # Same paging as the items/invoices screens: build only a page of
        # cards at a time instead of every matching customer/supplier.
        render_limit = {"n": 60}
        summary_row = ft.ResponsiveRow(spacing=8, run_spacing=8)

        def small_metric(label: str, value: str, icon, accent: str):
            return ft.Container(
                ft.Row(
                    [
                        ft.Container(ft.Icon(icon, size=19, color=accent), width=38, height=38, alignment=ft.alignment.center, bgcolor=Colors.BACKGROUND, border_radius=12),
                        ft.Column([ft.Text(label, size=10, color=Colors.TEXT_SECONDARY), ft.Text(value, size=17, weight=ft.FontWeight.BOLD)], spacing=1, expand=True),
                    ]
                ),
                padding=11,
                bgcolor=Colors.WHITE,
                border=ft.border.all(1, Colors.BORDER),
                border_radius=16,
                shadow=Shadow.SM,
            )

        def open_editor(party: dict | None = None):
            name = SelectAllTextField(label="الاسم", value=(party or {}).get("name", ""))
            phone = SelectAllTextField(label="الهاتف", value=(party or {}).get("phone") or "", keyboard_type=ft.KeyboardType.PHONE)
            address = SelectAllTextField(label="العنوان", value=(party or {}).get("address") or "", multiline=True, min_lines=1, max_lines=3)
            sheet = new_form_sheet()

            def close(_=None):
                page.close(sheet)

            def save(_=None):
                try:
                    if party:
                        repo.update(int(party["id"]), name.value or "", phone.value, address.value)
                        message = f"تم تحديث {singular}"
                    else:
                        repo.create(name.value or "", phone.value, address.value)
                        message = f"تمت إضافة {singular}"
                    close()
                    notify(message)
                    refresh()
                except Exception as exc:
                    notify(str(exc), kind="error")

            render_form_sheet(
                page, sheet,
                title=f"{'تعديل' if party else 'إضافة'} {singular}",
                fields=[name, phone, address],
                on_close=close, on_save=save,
            )
            page.open(sheet)

        def confirm_delete(party: dict, parent_dialog=None, restore_on_cancel: bool = False):
            # restore_on_cancel=True is used by the swipe-to-delete row (see
            # `rows.controls.append` below): the row has already been swiped
            # out of view by Dismissible's own animation *before* this dialog
            # opens, so cancelling here must restore it. refresh() is the
            # correct way to do that — nothing was actually deleted, so
            # re-reading from `repo` naturally redraws the still-existing
            # party back into the list. Tap-triggered deletes (from
            # show_detail) pass restore_on_cancel=False since no row was
            # ever removed from view for those.
            confirm = ft.AlertDialog(modal=True)

            def close(_=None):
                page.close(confirm)
                if restore_on_cancel:
                    refresh()

            def remove(_=None):
                try:
                    repo.delete(int(party["id"]))
                    close()
                    if parent_dialog:
                        try:
                            page.close(parent_dialog)
                        except Exception:
                            pass
                    notify(f"تم حذف {singular}", kind="success", sound_kind="delete")
                    refresh()
                except Exception as exc:
                    close()
                    notify(str(exc), kind="error")

            confirm.title = ft.Text(f"حذف {singular}")
            confirm.content = ft.Text(f"هل تريد حذف «{party['name']}»؟ لن يسمح بالحذف إذا كانت هناك حركات مالية مرتبطة.")
            confirm.actions = [ft.TextButton("إلغاء", on_click=close), ft.FilledButton("حذف", icon=ft.Icons.DELETE_FOREVER, on_click=remove)]
            page.open(confirm)

        def show_detail(party: dict):
            try:
                data = repo.activity_summary(int(party["id"]))
            except Exception as exc:
                notify(str(exc), kind="error")
                return
            balance = float(data.get("balance") or 0)
            party_type = "customer" if title == "العملاء" else "supplier"
            try:
                open_rows = [
                    r for r in self.ctx.reports.outstanding_invoices(party_type)
                    if int(r.get("party_id") or 0) == int(party["id"])
                ]
            except Exception:
                open_rows = []
            rel = grade_party(balance=balance, outstanding_rows=open_rows)
            grade_color = getattr(Colors, rel["color_token"], Colors.PRIMARY)
            grade_bg = getattr(Colors, rel["bg_token"], Colors.PRIMARY_BG)
            recent = []
            for inv in data.get("recent_invoices") or []:
                remaining = float(inv.get("remaining_amount") or 0)
                recent.append(
                    ft.Container(
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(f"فاتورة #{inv['id']}", size=12, weight=ft.FontWeight.BOLD),
                                        ft.Text(str(inv.get("invoice_date") or "—"), size=10, color=Colors.TEXT_SECONDARY),
                                    ], spacing=1, expand=True,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(money(inv.get("total")), size=12, weight=ft.FontWeight.BOLD),
                                        ft.Text("مسددة" if remaining <= 1e-9 else f"متبقي {money(remaining)}", size=9, color=Colors.SUCCESS if remaining <= 1e-9 else Colors.ORANGE),
                                    ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END,
                                ),
                            ]
                        ),
                        padding=9, bgcolor=Colors.BACKGROUND, border_radius=12,
                    )
                )
            if not recent:
                recent = [ft.Text("لا توجد فواتير مرتبطة بعد", size=11, color=Colors.TEXT_SECONDARY)]

            # Bottom sheet instead of a centered AlertDialog -- matches the
            # same BottomSheet + drag-handle + rounded-top treatment already
            # used for the item detail view in items_view.py, so customer/
            # supplier detail reads consistently with the rest of the app.
            detail_sheet = ft.BottomSheet(content=ft.Container(), enable_drag=True, maintain_bottom_view_insets_padding=True)

            def close(_=None):
                page.close(detail_sheet)

            def edit(_=None):
                close()
                open_editor(data)

            party_type = "customer" if is_customer else "supplier"

            async def print_party_card(_=None):
                if self.native_files is None:
                    notify("الطباعة الأصلية غير مهيأة في هذا البناء")
                    return
                try:
                    html = self.ctx.documents.party_card_html(party_type, data)
                    await self.native_files.print_html(html, name=f"nano-party-{data['id']}")
                except Exception as exc:
                    notify(str(exc), kind="error")

            async def share_party_card_pdf(_=None):
                if self.native_files is None:
                    notify("تصدير PDF غير مهيأ في هذا البناء")
                    return
                try:
                    html = self.ctx.documents.party_card_html(party_type, data)
                    await self.native_files.share_pdf(html, filename=f"nano_party_{data['id']}.pdf")
                except Exception as exc:
                    notify(str(exc), kind="error")

            # Same explicit-height approach as the item detail sheet: an
            # outer Container height computed from the real screen height,
            # with a scrollable stats/history body and a fixed footer row
            # for حذف/تعديل/إغلاق so the actions stay reachable regardless
            # of how many recent invoices are listed above them.
            page_h = page.height or 780
            total_sheet_h = min(int(page_h * 0.55), 600)
            header_reserved, footer_reserved, gaps = 90, 60, 24
            body_area_height = max(180, total_sheet_h - header_reserved - footer_reserved - gaps)

            detail_sheet.content = ft.Container(
                ft.Column(
                    [
                        ft.Container(width=44, height=5, bgcolor=Colors.BORDER_STRONG, border_radius=10, alignment=ft.alignment.center),
                        ft.Row(
                            [
                                ft.Container(ft.Icon(ft.Icons.PERSON if is_customer else ft.Icons.LOCAL_SHIPPING_OUTLINED, color=Colors.PRIMARY), width=42, height=42, alignment=ft.alignment.center, bgcolor=Colors.PRIMARY_BG, border_radius=14),
                                ft.Column([
                                    ft.Text(data["name"], size=18, weight=ft.FontWeight.BOLD),
                                    ft.Row([
                                        ft.Text(data.get("phone") or "بدون هاتف", size=11, color=Colors.TEXT_SECONDARY),
                                        ft.Container(
                                            ft.Text(rel["label"], size=10, weight=ft.FontWeight.W_600, color=grade_color),
                                            padding=ft.padding.symmetric(horizontal=8, vertical=2),
                                            bgcolor=grade_bg,
                                            border_radius=10,
                                        ),
                                    ], spacing=8),
                                ], spacing=1, expand=True),
                                ft.IconButton(ft.Icons.PRINT_OUTLINED, tooltip="طباعة بطاقة الحساب", on_click=print_party_card),
                                ft.IconButton(ft.Icons.IOS_SHARE, tooltip="مشاركة PDF", on_click=share_party_card_pdf),
                            ]
                        ),
                        ft.Container(
                            ft.Column(
                                [
                                    ft.ResponsiveRow(
                                        [
                                            ft.Container(small_metric("الرصيد الحالي", money(balance), ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, Colors.PRIMARY), col={"xs": 6, "md": 3}),
                                            ft.Container(small_metric("عدد الفواتير", str(int(data.get("invoice_count") or 0)), ft.Icons.RECEIPT_LONG_OUTLINED, Colors.PURPLE), col={"xs": 6, "md": 3}),
                                            ft.Container(small_metric("إجمالي الفواتير", money(data.get("invoice_total")), ft.Icons.PAID_OUTLINED, Colors.SUCCESS), col={"xs": 6, "md": 3}),
                                            ft.Container(small_metric("انتظام السداد", rel["label"] + (f" · {rel['max_age_days']}ي" if rel["max_age_days"] else ""), ft.Icons.VERIFIED_USER_OUTLINED, grade_color), col={"xs": 6, "md": 3}),
                                        ], spacing=7, run_spacing=7,
                                    ),
                                    ft.Text(f"العنوان: {data.get('address') or '—'}", size=11, color=Colors.TEXT_MUTED),
                                    ft.Divider(height=10),
                                    ft.Text("آخر الفواتير", size=14, weight=ft.FontWeight.BOLD),
                                    ft.Column(recent, spacing=6),
                                ], spacing=9, scroll=ft.ScrollMode.AUTO,
                            ),
                            height=body_area_height, padding=ft.padding.only(top=8),
                        ),
                        ft.Container(
                            ft.Row(
                                [
                                    ft.TextButton("حذف", icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _: confirm_delete(data, detail_sheet), expand=True),
                                    ft.OutlinedButton("تعديل", icon=ft.Icons.EDIT_OUTLINED, on_click=edit, expand=True),
                                    ft.FilledButton("إغلاق", on_click=close, expand=True),
                                ],
                                spacing=10,
                            ),
                            padding=ft.padding.only(top=4),
                        ),
                    ],
                    spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
                height=total_sheet_h,
                padding=ft.padding.only(left=18, right=18, top=12, bottom=20),
                bgcolor=Colors.WHITE,
                border_radius=ft.border_radius.only(top_left=28, top_right=28),
                shadow=Shadow.LG,
            )
            page.open(detail_sheet)

        def _outstanding_by_party() -> dict[int, list[dict]]:
            party_type = "customer" if "customer" in str(getattr(repo, "table", "") or getattr(repo, "party_type", "") or title).lower() or title == "العملاء" else "supplier"
            if title == "العملاء":
                party_type = "customer"
            elif title == "الموردون":
                party_type = "supplier"
            try:
                rows = self.ctx.reports.outstanding_invoices(party_type)
            except Exception:
                return {}
            by: dict[int, list[dict]] = {}
            for r in rows:
                pid = r.get("party_id")
                if pid is None:
                    continue
                try:
                    pid = int(pid)
                except Exception:
                    continue
                by.setdefault(pid, []).append(r)
            return by

        def refresh(_=None):
            parties = repo.list(search.value or "")
            all_parties = repo.list()
            outstanding_map = _outstanding_by_party()
            total_balance = sum(float(x.get("balance") or 0) for x in all_parties)
            positive = sum(1 for x in all_parties if abs(float(x.get("balance") or 0)) > 1e-9)
            summary_row.controls = [
                ft.Container(small_metric(f"عدد {title}", str(len(all_parties)), ft.Icons.GROUP_OUTLINED, Colors.PRIMARY), col={"xs": 6, "md": 4}),
                ft.Container(small_metric("إجمالي الأرصدة", money(total_balance), ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, Colors.SUCCESS if total_balance >= 0 else Colors.DANGER), col={"xs": 6, "md": 4}),
                ft.Container(small_metric("حسابات بحركة", str(positive), ft.Icons.SYNC_ALT, Colors.PURPLE), col={"xs": 12, "md": 4}),
            ]
            rows.controls = []
            for party in parties[: render_limit["n"]]:
                balance = float(party.get("balance") or 0)
                initials = (party.get("name") or "؟").strip()[:1]
                row_card = ft.Container(
                    ft.Row(
                        [
                            ft.Container(ft.Text(initials, size=18, weight=ft.FontWeight.BOLD, color=Colors.PRIMARY), width=46, height=46, alignment=ft.alignment.center, bgcolor=Colors.PRIMARY_BG, border_radius=15),
                            ft.Column(
                                [
                                    ft.Text(party["name"], weight=ft.FontWeight.BOLD, size=14),
                                    ft.Text(party.get("phone") or party.get("address") or "بدون بيانات اتصال", size=10, color=Colors.TEXT_SECONDARY, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                ], expand=True, spacing=2,
                            ),
                            ft.Column(
                                [
                                    ft.Text(money(balance), weight=ft.FontWeight.BOLD, size=13, color=Colors.TEXT_PRIMARY),
                                    ft.Text(
                                        (
                                            lambda g: g["label"]
                                        )(
                                            grade_party(
                                                balance=balance,
                                                outstanding_rows=outstanding_map.get(int(party["id"]), []),
                                            )
                                        ),
                                        size=9,
                                        color=Colors.TEXT_SECONDARY,
                                    ),
                                ], spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END,
                            ),
                            ft.Icon(ft.Icons.CHEVRON_LEFT, size=18, color=Colors.TEXT_FAINT),
                        ], vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=12, bgcolor=Colors.WHITE, border=ft.border.all(1, Colors.BORDER), border_radius=16, shadow=Shadow.SM,
                    on_click=lambda _, p=dict(party): show_detail(p), ink=True,
                )
                # Swipe actions — deliberately narrow scope (see
                # SWIPE_ACTIONS_NOTES.md): parties are the one list in the
                # app with a real, already-guarded delete() (server refuses
                # if linked invoices exist). The swipe itself never deletes
                # anything — it only opens the *same* modal confirmation
                # used by the tap-to-delete path (`confirm_delete`), so a
                # misjudged or accidental swipe can never destroy data by
                # itself; the worst case is an unwanted confirm dialog the
                # user dismisses. Both drag directions are wired to the
                # identical action, so RTL-vs-LTR "which way does the row
                # go" ambiguity has no wrong answer to guess.
                rows.controls.append(
                    ft.Dismissible(
                        key=f"party-{party['id']}",
                        content=row_card,
                        dismiss_direction=ft.DismissDirection.HORIZONTAL,
                        background=ft.Container(
                            content=ft.Row([ft.Icon(ft.Icons.DELETE_OUTLINE, color=Colors.WHITE, size=22), ft.Text("حذف", color=Colors.WHITE, size=12, weight=ft.FontWeight.W_600)], spacing=6, alignment=ft.MainAxisAlignment.START),
                            bgcolor=Colors.DANGER_DARK, border_radius=16, padding=ft.padding.symmetric(horizontal=20), alignment=ft.alignment.center_left,
                        ),
                        secondary_background=ft.Container(
                            content=ft.Row([ft.Text("حذف", color=Colors.WHITE, size=12, weight=ft.FontWeight.W_600), ft.Icon(ft.Icons.DELETE_OUTLINE, color=Colors.WHITE, size=22)], spacing=6, alignment=ft.MainAxisAlignment.END),
                            bgcolor=Colors.DANGER_DARK, border_radius=16, padding=ft.padding.symmetric(horizontal=20), alignment=ft.alignment.center_right,
                        ),
                        on_dismiss=lambda _, p=dict(party): confirm_delete(p, restore_on_cancel=True),
                    )
                )
            if not rows.controls:
                if all_parties:
                    rows.controls.append(empty_state(
                        "لا توجد نتائج مطابقة للبحث",
                        icon=ft.Icons.PERSON_SEARCH,
                        hint="جرّب اسمًا أو رقم هاتف مختلف",
                    ))
                else:
                    rows.controls.append(empty_state(
                        f"لا يوجد {title} بعد",
                        icon=ft.Icons.PERSON_SEARCH,
                        hint=f"ابدأ بإضافة أول {singular}",
                        action_label=f"إضافة {singular}",
                        on_action=lambda _: open_editor(),
                    ))
            elif len(parties) > render_limit["n"]:
                remaining = len(parties) - render_limit["n"]

                def load_more(_=None):
                    render_limit["n"] += 60
                    refresh()

                rows.controls.append(
                    ft.OutlinedButton(
                        f"تحميل المزيد ({remaining})",
                        icon=ft.Icons.EXPAND_MORE_ROUNDED,
                        on_click=load_more,
                    )
                )
            page.update()

        def refresh_from_search(e=None):
            render_limit["n"] = 60
            refresh()

        search.on_change = refresh_from_search

        # Same sticky_top/scroll_body/bottom_bar treatment as the items and
        # stocktake screens: search stays reachable while scrolling a long
        # party list, and the primary "إضافة" action stays one tap away at
        # the bottom instead of scrolling off with the list.
        sticky_top = ft.Container(
            search,
            padding=ft.padding.only(left=18, right=18, top=14, bottom=10),
            bgcolor=Colors.WHITE,
            border=ft.border.only(bottom=ft.BorderSide(1, Colors.BORDER)),
        )
        scroll_body = ft.Column([summary_row, rows], spacing=12, scroll=ft.ScrollMode.AUTO, expand=True)
        bottom_bar = ft.Container(
            ft.FilledButton(f"إضافة {singular}", icon=ft.Icons.ADD, on_click=lambda _: open_editor(), expand=True),
            padding=ft.padding.only(left=18, right=18, top=10, bottom=10),
            bgcolor=Colors.WHITE,
            border=ft.border.only(top=ft.BorderSide(1, Colors.BORDER)),
            shadow=ft.BoxShadow(blur_radius=16, color=Colors.BORDER, offset=ft.Offset(0, -4)),
        )
        content.content = ft.Column(
            [
                sticky_top,
                ft.Container(scroll_body, padding=ft.padding.only(left=18, right=18, top=14, bottom=10), expand=True),
                bottom_bar,
            ],
            spacing=0,
            expand=True,
        )
        refresh()


__all__ = ["PartyCenter"]
