from __future__ import annotations

import time

import flet as ft

from nano_offline.core.toast import toast
from nano_offline.components import SelectAllTextField, SearchSelect, SmartAmountField, empty_state, money_text_from_str
from nano_offline.components.buttons import inline_icon_button
from nano_offline.core.theme import Colors
from nano_offline.core import barcode_settings

DEFAULT_UNIT_NAME = "قطعة"


class StocktakeCenter:
    """Continuous-scan stocktake: open the camera once, walk the shelves,
    and keep scanning without returning to any other screen between items.

    Standalone screen reached from the items list ("جرد بالمسح المستمر" in
    the "المزيد" sheet) rather than a permanent nav tab -- a stocktake is an
    occasional, focused task, not something that needs a slot in the main
    shell competing with daily screens.
    """

    def __init__(self, page: ft.Page, ctx, content: ft.Container, *, native_files=None, on_title_change=None, on_exit=None):
        self.page = page
        self.ctx = ctx
        self.content = content
        self.native_files = native_files
        self.on_title_change = on_title_change
        self.on_exit = on_exit
        self._session_id: int | None = None
        self._scanning = False
        self._last_code: str | None = None
        self._last_scan_at = 0.0

    def _set_header(self, title: str, subtitle: str = "") -> None:
        if self.on_title_change:
            self.on_title_change(title, subtitle)

    def notify(self, text: str, kind: str | None = None, sound_kind: str | None = None) -> None:
        toast(self.page, text, kind=kind, sound_kind=sound_kind)

    @staticmethod
    def _qty(value) -> str:
        return f"{float(value or 0):,.2f}"

    def money(self, value) -> str:
        from nano_offline.core import currency
        return currency.format_amount(value, self.ctx.settings)

    def _exit(self) -> None:
        if self.on_exit:
            self.on_exit()

    # ---- entry point ---------------------------------------------------- #

    def show_center(self) -> None:
        """Start a fresh session and render the scan screen -- unless a
        prior walk was left open (app closed mid-count, etc.), in which
        case offer to resume it before ever creating a new one."""
        self._set_header("جرد بالمسح المستمر", "")
        resumable = self.ctx.stocktake.find_resumable_session()
        if resumable:
            self._offer_resume(resumable)
            return
        self._start_fresh_session()

    def _start_fresh_session(self) -> None:
        self._session_id = self.ctx.stocktake.start_session()
        self._scanning = False
        self._last_code = None
        self._last_scan_at = 0.0
        self._render_scan_screen()

    def _resume_session(self, session_id: int) -> None:
        self._session_id = session_id
        self._scanning = False
        self._last_code = None
        self._last_scan_at = 0.0
        self._render_scan_screen()

    def _offer_resume(self, session: dict) -> None:
        page = self.page
        started = (session.get("started_at") or "").split(".")[0]
        line_count = int(session.get("line_count") or 0)
        dialog = ft.AlertDialog(modal=True, title=ft.Text("جلسة جرد مفتوحة"))

        def resume(_=None):
            page.close(dialog)
            self._resume_session(int(session["id"]))

        def discard_and_start_new(_=None):
            page.close(dialog)
            self.ctx.stocktake.discard_session(int(session["id"]))
            self.notify("تم تجاهل الجلسة السابقة وبدء جلسة جديدة")
            self._start_fresh_session()

        dialog.content = ft.Text(
            f"توجد جلسة جرد لم تُنهَ من قبل ({line_count} مادة ممسوحة"
            + (f"، بدأت {started}" if started else "")
            + ") — هل تريد إكمالها أم تجاهلها وبدء جلسة جديدة؟"
        )
        dialog.actions = [
            ft.TextButton("تجاهل وبدء جديدة", on_click=discard_and_start_new),
            ft.FilledButton("إكمال الجلسة السابقة", icon=ft.Icons.PLAY_ARROW_ROUNDED, on_click=resume),
        ]
        page.open(dialog)

    # ---- scan screen ------------------------------------------------------ #

    def _render_scan_screen(self) -> None:
        page = self.page
        ctx = self.ctx
        self._set_header("جرد بالمسح المستمر", "امسح المواد واحدة تلو الأخرى دون توقف")

        status_text = ft.Text("جاهز — اضغط ابدأ المسح", size=13, color=Colors.TEXT_SECONDARY)
        last_scan_card = ft.Container(visible=False)
        lines_column = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)
        total_lines_text = ft.Text("0 مادة ممسوحة", size=12, color=Colors.TEXT_SECONDARY)

        manual_field = SelectAllTextField(label="أو اكتب الباركود يدويًا", hint_text="ثم اضغط Enter", dense=True, expand=True)

        def refresh_sidebar() -> None:
            lines = ctx.stocktake.lines(self._session_id)
            total_lines_text.value = f"{len(lines)} مادة ممسوحة"
            if not lines:
                lines_column.controls = [
                    ft.Container(
                        ft.Text("لم يتم مسح أي مادة بعد", size=12, color=Colors.TEXT_FAINT),
                        padding=16, alignment=ft.alignment.center,
                    )
                ]
            else:
                lines_column.controls = [self._line_row(row) for row in lines]
            page.update()

        def show_last_scan(result: dict) -> None:
            status = result.get("status")
            if status == "added":
                item = result["item"]
                last_scan_card.content = ft.Row(
                    [
                        ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, color=Colors.SUCCESS, size=22),
                        ft.Column(
                            [
                                ft.Text(item.get("name") or "", weight=ft.FontWeight.BOLD, size=13),
                                ft.Text(f"العدّاد: {self._qty(result['counted_qty'])}", size=11, color=Colors.TEXT_SECONDARY),
                            ],
                            spacing=1, expand=True,
                        ),
                    ],
                    spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                last_scan_card.bgcolor = Colors.SUCCESS_BG
                last_scan_card.border = ft.border.all(1, Colors.SUCCESS)
                if barcode_settings.stocktake_sound_enabled(ctx.settings):
                    # Real haptic vibration here would still need a native
                    # platform channel (see the identical note in
                    # pos_view.py's _add_by_barcode) -- but the toast()
                    # call below now plays an actual chime through
                    # core/sound.py (audioplayers' AudioPool), not just a
                    # silent visual substitute: while last_scan_card only
                    # quietly updates in place, this toast both animates on
                    # screen *and* sounds, so this setting has a real
                    # audible effect. Uses the dedicated "scan" tone (short,
                    # built for firing many times a minute during a count)
                    # rather than the generic "success" chime, same
                    # reasoning as pos_view.py's barcode handler.
                    # (Whether/how loud it plays is then also gated by the
                    # admin's separate "الصوت" tab settings, same as every
                    # other toast in the app.)
                    self.notify("✔", kind="success", sound_kind="scan")
            elif status == "service":
                last_scan_card.content = ft.Text(
                    f"⚠ {result['item'].get('name','')} خدمة ولا تُحتسب في الجرد", size=12, color=Colors.WARNING_DARK
                )
                last_scan_card.bgcolor = Colors.WARNING_BG
                last_scan_card.border = ft.border.all(1, Colors.WARNING)
                if barcode_settings.stocktake_sound_enabled(ctx.settings):
                    self.notify("⚠ مادة خدمة", kind="warning")
            elif status == "checksum":
                last_scan_card.content = ft.Text("⚠ أعد المسح — رقم التحقق غير صحيح", size=12, color=Colors.WARNING_DARK)
                last_scan_card.bgcolor = Colors.WARNING_BG
                last_scan_card.border = ft.border.all(1, Colors.WARNING)
                if barcode_settings.stocktake_sound_enabled(ctx.settings):
                    self.notify("⚠ رقم التحقق غير صحيح", kind="warning")
            elif status == "similar":
                names = "، ".join(result.get("names", [])[:3])
                last_scan_card.content = ft.Text(f"⚠ لا توجد مطابقة تامة — أقرب المواد: {names}", size=12, color=Colors.WARNING_DARK)
                last_scan_card.bgcolor = Colors.WARNING_BG
                last_scan_card.border = ft.border.all(1, Colors.WARNING)
                if barcode_settings.stocktake_sound_enabled(ctx.settings):
                    self.notify("⚠ لا توجد مطابقة تامة", kind="warning")
            else:
                last_scan_card.content = ft.Row(
                    [
                        ft.Icon(ft.Icons.ERROR_ROUNDED, color=Colors.DANGER, size=22),
                        ft.Column(
                            [
                                ft.Text("لا توجد مادة بهذا الباركود", size=13, weight=ft.FontWeight.BOLD),
                                ft.Text(result.get("code", ""), size=11, color=Colors.TEXT_SECONDARY),
                            ],
                            spacing=1, expand=True,
                        ),
                        ft.FilledButton("إنشاء مادة", icon=ft.Icons.ADD, on_click=lambda _, c=result.get("code"): offer_create(c)),
                    ],
                    spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
                last_scan_card.bgcolor = Colors.DANGER_BG
                last_scan_card.border = ft.border.all(1, Colors.DANGER_BORDER)
                # Unlike the "added" branch above, this failure path used to
                # only update last_scan_card's inline visuals -- it never
                # called notify()/toast() at all, so it never reached
                # core/sound.py's play() either (see that module's
                # docstring: sound only piggybacks on toast() calls, there
                # is no separate direct hook). A cashier scanning an
                # unrecognized barcode during a fast continuous walk got no
                # audible cue at all that the scan failed, only a silent
                # card update easy to miss without looking at the screen.
                if barcode_settings.stocktake_sound_enabled(ctx.settings):
                    self.notify("لا توجد مادة بهذا الباركود", kind="error", sound_kind="barcode_error")
            last_scan_card.padding = 12
            last_scan_card.border_radius = 14
            last_scan_card.visible = True
            page.update()

        def ensure_default_unit_id(units_list: list[dict]) -> str | None:
            # Mirrors items_view's default-unit priming: most counted stock
            # is per-piece, so pre-selecting "قطعة" (creating it once if the
            # shop has no units defined yet) saves a search-and-tap on what
            # is meant to be a two-field, keep-walking-the-shelf form.
            existing = next((u for u in units_list if (u.get("name") or "").strip() == DEFAULT_UNIT_NAME), None)
            if existing:
                return str(existing["id"])
            try:
                return str(ctx.definitions.create_unit(DEFAULT_UNIT_NAME))
            except Exception:
                return None

        def offer_create(code: str | None) -> None:
            # Quick-add stays on this screen and hands straight back to the
            # scan loop -- the whole point of continuous mode is never
            # bouncing to the items screen mid-walk for an unrecognized
            # barcode.
            was_scanning = self._scanning
            if was_scanning:
                self._scanning = False

            units = ctx.definitions.list_units()
            name_field = SelectAllTextField(label="اسم المادة", autofocus=True, expand=True)
            price_field = SmartAmountField(label="سعر الشراء (اختياري)", expand=True)
            sell_field = SmartAmountField(label="سعر البيع (اختياري)", expand=True)
            unit_select = SearchSelect(
                label="الوحدة الأساسية",
                choices=[(str(u["id"]), u["name"]) for u in units],
                value=ensure_default_unit_id(units),
            )
            error_text = ft.Text("", size=11, color=Colors.DANGER)

            dialog = ft.AlertDialog(modal=True, title=ft.Text("مادة جديدة"))

            def resume_if_needed() -> None:
                if was_scanning:
                    page.run_task(scan_loop)

            def cancel(_=None):
                page.close(dialog)
                resume_if_needed()

            def save(_=None):
                name = (name_field.value or "").strip()
                if not name:
                    error_text.value = "اسم المادة مطلوب"
                    page.update()
                    return
                try:
                    purchase = float((price_field.value or "0").strip() or 0)
                    selling = float((sell_field.value or "0").strip() or 0)
                except ValueError:
                    error_text.value = "قيمة سعر غير صحيحة"
                    page.update()
                    return
                try:
                    ctx.items.create(
                        name=name,
                        barcode=code,
                        purchase_price=purchase,
                        selling_price=selling,
                        base_unit_id=int(unit_select.value) if unit_select.value else None,
                    )
                except ValueError as exc:
                    error_text.value = str(exc)
                    page.update()
                    return
                page.close(dialog)
                # The item now resolves by barcode -- feed the same code
                # straight back through the normal scan path so it lands in
                # this session as the first count, exactly as if the shelf
                # copy had scanned clean the first time. Clear the cooldown
                # guard first: handle_code() already stamped this code/time
                # on the original "not found" read, and without this reset
                # that stamp would make the follow-up look like a duplicate
                # re-read and get silently dropped.
                self._last_code = None
                self._last_scan_at = 0.0
                handle_code(code)
                resume_if_needed()

            dialog.content = ft.Column(
                [
                    ft.Text(f"الباركود: {code}", size=12, color=Colors.TEXT_SECONDARY),
                    name_field,
                    ft.Row([price_field, sell_field], spacing=8),
                    unit_select,
                    error_text,
                ],
                spacing=10, tight=True, width=360,
            )
            dialog.actions = [
                ft.TextButton("إلغاء", on_click=cancel),
                ft.FilledButton("إضافة ومتابعة المسح", icon=ft.Icons.ADD, on_click=save),
            ]
            page.open(dialog)

        def handle_code(code: str) -> None:
            code = (code or "").strip()
            if not code:
                return
            now = time.monotonic()
            cooldown = barcode_settings.stocktake_cooldown_ms(ctx.settings) / 1000.0
            if code == self._last_code and (now - self._last_scan_at) < cooldown:
                return  # same code re-read within the cooldown window -- ignore
            self._last_code = code
            self._last_scan_at = now
            try:
                result = ctx.stocktake.scan(self._session_id, code)
            except Exception as exc:
                self.notify(str(exc), kind="error")
                return
            show_last_scan(result)
            refresh_sidebar()

        def manual_submit(e):
            code = (manual_field.value or "").strip()
            manual_field.value = ""
            if code:
                handle_code(code)
            manual_field.focus()
            page.update()

        manual_field.on_submit = manual_submit

        async def scan_loop() -> None:
            if self.native_files is None:
                self.notify("مسح الباركود غير مهيأ في هذا البناء", kind="error")
                return
            self._scanning = True
            status_text.value = "المسح مستمر — وجّه الكاميرا نحو الباركود"
            page.update()
            while self._scanning:
                try:
                    code = await self.native_files.scan_barcode()
                except Exception as exc:
                    self.notify(str(exc), kind="error")
                    break
                if not self._scanning:
                    break
                if code:
                    handle_code(code)
                    # Loop immediately reopens the scanner -- no tap needed
                    # between one item and the next, which is the whole
                    # point of "continuous" mode vs. the item editor's
                    # one-shot scan.
                    continue
                # scan_barcode() returns None in exactly one situation: the
                # user backed out of the camera screen (AppBar/hardware
                # back button) without a read -- see native_files.py's
                # scan_barcode() docstring. There's no auto-timeout, so a
                # None here can only mean "the user is done" (finished the
                # stocktake, or just wants out) -- it is never "the camera
                # briefly failed to see a code, try again". Treating it as
                # anything other than an explicit stop was the actual bug:
                # the loop used to immediately call scan_barcode() again,
                # instantly reopening the very camera the user had just
                # backed out of -- indistinguishable from "can't exit the
                # camera at all" without force-closing the app.
                break
            self._scanning = False
            status_text.value = "المسح متوقف"
            page.update()

        def toggle_scan(_=None):
            if self._scanning:
                self._scanning = False
                status_text.value = "جارٍ الإيقاف..."
                page.update()
            else:
                page.run_task(scan_loop)

        def go_review(_=None):
            if self._scanning:
                self._scanning = False
            self._render_review_screen()

        def confirm_discard(_=None):
            dialog = ft.AlertDialog(modal=True, title=ft.Text("تجاهل الجرد؟"))

            def yes(_=None):
                page.close(dialog)
                self._scanning = False
                ctx.stocktake.discard_session(self._session_id)
                self.notify("تم تجاهل جلسة الجرد")
                self._exit()

            def no(_=None):
                page.close(dialog)

            dialog.content = ft.Text("لن يُحفظ أي تغيير على المخزون. هل أنت متأكد؟")
            dialog.actions = [ft.TextButton("إلغاء", on_click=no), ft.FilledButton("تجاهل", icon=ft.Icons.DELETE_OUTLINE, on_click=yes)]
            page.open(dialog)

        scan_button = ft.FilledButton(
            "ابدأ المسح المستمر", icon=ft.Icons.QR_CODE_SCANNER, on_click=toggle_scan, expand=True,
        )

        def sync_scan_button():
            scan_button.text = "إيقاف المسح" if self._scanning else "ابدأ المسح المستمر"
            scan_button.icon = ft.Icons.STOP_CIRCLE_OUTLINED if self._scanning else ft.Icons.QR_CODE_SCANNER

        top_bar = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.IconButton(icon=ft.Icons.CLOSE, tooltip="إغلاق", on_click=confirm_discard),
                            ft.Text("جرد بالمسح المستمر", size=16, weight=ft.FontWeight.BOLD, expand=True),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    status_text,
                ],
                spacing=4,
            ),
            padding=ft.padding.only(left=18, right=18, top=14, bottom=10),
            bgcolor=Colors.WHITE,
            border=ft.border.only(bottom=ft.BorderSide(1, Colors.BORDER)),
        )

        scroll_body = ft.Column(
            [
                last_scan_card,
                ft.Row([manual_field], spacing=8),
                ft.Row([ft.Text("المواد الممسوحة", size=13, weight=ft.FontWeight.BOLD), ft.Container(expand=True), total_lines_text]),
                lines_column,
            ],
            spacing=12, expand=True,
        )

        bottom_bar = ft.Container(
            ft.Row(
                [
                    scan_button,
                    ft.OutlinedButton("إنهاء ومراجعة", icon=ft.Icons.FACT_CHECK_OUTLINED, on_click=go_review),
                ],
                spacing=10,
            ),
            padding=ft.padding.only(left=18, right=18, top=10, bottom=10),
            bgcolor=Colors.WHITE,
            border=ft.border.only(top=ft.BorderSide(1, Colors.BORDER)),
            shadow=ft.BoxShadow(blur_radius=16, color=Colors.BORDER, offset=ft.Offset(0, -4)),
        )

        sync_scan_button()
        self.content.content = ft.Column(
            [top_bar, ft.Container(scroll_body, padding=ft.padding.symmetric(horizontal=18, vertical=12), expand=True), bottom_bar],
            spacing=0, expand=True,
        )
        refresh_sidebar()
        page.update()

    def _line_row(self, row: dict) -> ft.Control:
        counted = float(row["counted_qty"])
        system = float(row["system_qty_snapshot"])
        diff = counted - system
        if abs(diff) < 1e-9:
            accent = Colors.TEXT_SECONDARY
        elif diff > 0:
            accent = Colors.SUCCESS
        else:
            accent = Colors.DANGER
        unit = row.get("unit_abbreviation") or ""

        def edit_qty(_=None, item_id=int(row["item_id"]), name=row.get("item_name", "")):
            self._open_manual_edit(item_id, name, counted)

        return ft.Container(
            ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(row.get("item_name") or "", size=13, weight=ft.FontWeight.W_600),
                            ft.Text(f"مُسح {int(row['scan_count'])} مرة", size=10, color=Colors.TEXT_FAINT),
                        ],
                        spacing=1, expand=True,
                    ),
                    ft.Text(f"{self._qty(counted)} {unit}", size=13, weight=ft.FontWeight.BOLD, color=accent),
                    inline_icon_button(ft.Icons.EDIT_OUTLINED, edit_qty, tooltip="تعديل يدوي"),
                ],
                spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=8),
            bgcolor=Colors.WHITE, border=ft.border.all(1, Colors.BORDER), border_radius=12,
        )

    def _open_manual_edit(self, item_id: int, name: str, current_qty: float) -> None:
        page = self.page
        field = SelectAllTextField(label="الكمية المعدودة", value=self._qty(current_qty), keyboard_type=ft.KeyboardType.NUMBER)
        dialog = ft.AlertDialog(modal=True, title=ft.Text(name))

        def save(_=None):
            try:
                qty = float((field.value or "0").strip())
            except ValueError:
                self.notify("قيمة غير صحيحة", kind="error")
                return
            try:
                self.ctx.stocktake.set_counted_qty(self._session_id, item_id, qty)
            except Exception as exc:
                self.notify(str(exc), kind="error")
                return
            page.close(dialog)
            self._render_scan_screen()

        def cancel(_=None):
            page.close(dialog)

        dialog.content = field
        dialog.actions = [ft.TextButton("إلغاء", on_click=cancel), ft.FilledButton("حفظ", on_click=save)]
        page.open(dialog)

    # ---- review screen ------------------------------------------------- #

    def _render_review_screen(self) -> None:
        page = self.page
        ctx = self.ctx
        self._set_header("مراجعة الفروقات", "الأصناف التي فيها فرق بين المعدود والدفتري فقط")

        diffs = ctx.stocktake.diff_summary(self._session_id, only_diffs=True)
        rows_column = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)

        if not diffs:
            rows_column.controls = [
                empty_state(
                    "لا فروقات — المخزون مطابق تمامًا",
                    icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
                    hint="يمكنك اعتماد الجلسة بأمان أو العودة للمسح",
                )
            ]
        else:
            for row in diffs:
                diff = row["diff"]
                value_diff = row["value_diff"]
                positive = diff > 0
                accent = Colors.SUCCESS if positive else Colors.DANGER
                bg = Colors.SUCCESS_BG if positive else Colors.DANGER_BG
                unit = row.get("unit_abbreviation") or ""
                sign = "+" if positive else ""
                rows_column.controls.append(
                    ft.Container(
                        ft.Row(
                            [
                                ft.Column(
                                    [
                                        ft.Text(row.get("item_name") or "", size=13, weight=ft.FontWeight.W_600),
                                        ft.Text(
                                            f"دفتري {self._qty(row['system_qty_snapshot'])} ← معدود {self._qty(row['counted_qty'])}",
                                            size=11, color=Colors.TEXT_SECONDARY,
                                        ),
                                    ],
                                    spacing=1, expand=True,
                                ),
                                ft.Column(
                                    [
                                        ft.Text(f"{sign}{self._qty(diff)} {unit}", size=13, weight=ft.FontWeight.BOLD, color=accent),
                                        ft.Text(f"{sign}{self.money(value_diff)}", size=11, color=accent),
                                    ],
                                    spacing=1, horizontal_alignment=ft.CrossAxisAlignment.END,
                                ),
                            ],
                            spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=ft.padding.symmetric(horizontal=12, vertical=10),
                        bgcolor=bg, border=ft.border.all(1, accent), border_radius=12,
                    )
                )

        def back_to_scan(_=None):
            self._render_scan_screen()

        def do_discard(_=None):
            dialog = ft.AlertDialog(modal=True, title=ft.Text("تجاهل الجرد؟"))

            def yes(_=None):
                page.close(dialog)
                ctx.stocktake.discard_session(self._session_id)
                self.notify("تم تجاهل جلسة الجرد")
                self._exit()

            def no(_=None):
                page.close(dialog)

            dialog.content = ft.Text("لن يُحفظ أي تغيير على المخزون. هل أنت متأكد؟")
            dialog.actions = [ft.TextButton("إلغاء", on_click=no), ft.FilledButton("تجاهل", icon=ft.Icons.DELETE_OUTLINE, on_click=yes)]
            page.open(dialog)

        def do_commit(_=None):
            dialog = ft.AlertDialog(modal=True, title=ft.Text("اعتماد الجرد"))

            def yes(_=None):
                page.close(dialog)
                try:
                    count = ctx.stocktake.commit(self._session_id)
                except Exception as exc:
                    self.notify(str(exc), kind="error")
                    return
                self.notify(f"تم اعتماد الجرد — {count} تسوية مخزون" if count else "تم اعتماد الجرد بلا فروقات")
                self._exit()

            def no(_=None):
                page.close(dialog)

            dialog.content = ft.Text(
                f"سيتم تسجيل {len(diffs)} تسوية مخزون بناءً على الفروقات المعروضة. لا يمكن التراجع عن هذه الخطوة إلا بجرد جديد."
            )
            dialog.actions = [ft.TextButton("إلغاء", on_click=no), ft.FilledButton("اعتماد", icon=ft.Icons.CHECK_CIRCLE_OUTLINE, on_click=yes)]
            page.open(dialog)

        top_bar = ft.Container(
            ft.Row(
                [
                    ft.IconButton(icon=ft.Icons.ARROW_FORWARD, tooltip="عودة للمسح", on_click=back_to_scan),
                    ft.Text("مراجعة الفروقات", size=16, weight=ft.FontWeight.BOLD, expand=True),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.only(left=18, right=18, top=14, bottom=10),
            bgcolor=Colors.WHITE,
            border=ft.border.only(bottom=ft.BorderSide(1, Colors.BORDER)),
        )

        bottom_bar = ft.Container(
            ft.Row(
                [
                    ft.OutlinedButton("تجاهل", icon=ft.Icons.DELETE_OUTLINE, on_click=do_discard),
                    ft.FilledButton("اعتماد الجرد", icon=ft.Icons.CHECK_CIRCLE_OUTLINE, on_click=do_commit, expand=True),
                ],
                spacing=10,
            ),
            padding=ft.padding.only(left=18, right=18, top=10, bottom=10),
            bgcolor=Colors.WHITE,
            border=ft.border.only(top=ft.BorderSide(1, Colors.BORDER)),
            shadow=ft.BoxShadow(blur_radius=16, color=Colors.BORDER, offset=ft.Offset(0, -4)),
        )

        self.content.content = ft.Column(
            [top_bar, ft.Container(rows_column, padding=ft.padding.symmetric(horizontal=18, vertical=12), expand=True), bottom_bar],
            spacing=0, expand=True,
        )
        page.update()


__all__ = ["StocktakeCenter"]
