from __future__ import annotations

import asyncio
import math
import time

import flet as ft

from nano_offline.core.toast import toast

from nano_offline.components import SearchSelect, SelectAllTextField, empty_state
from nano_offline.components.buttons import hero_button, stepper_icon_button
from nano_offline.services.invoice_service import InvoiceLineInput
from nano_offline.core.theme import Colors, IconSize, LazyPalette, Radius, Shadow
from nano_offline.core import currency
from nano_offline.core import barcode_settings
from nano_offline.core import pos_settings
from nano_offline.core import sound as sound_engine

# A small fixed palette so category chips get a stable, distinguishable
# color per category without needing a "color" column on the categories
# table. Cycled by index, not hashed, so the same category keeps the same
# color across a session (and across screens) as long as list order is
# stable — which it is, since list_categories() orders by name.
CHIP_PALETTE = LazyPalette("PRIMARY", "PURPLE_LIGHT", "ORANGE", "WARNING_DARK", "SUCCESS_ALT")


class POSCenter:
    """Fast, touch-first counter-sale screen.

    Separate from InvoiceCenter's full editor (customer/date/reference/notes)
    on purpose: POS optimizes for "scan or tap, then pay" with everything
    else defaulted. It still creates a normal ``sale`` invoice through
    ``InvoiceService`` so it stays fully compatible with reporting,
    inventory and party balances — there is no separate POS data model.
    """

    def __init__(
        self,
        page: ft.Page,
        ctx,
        content: ft.Container,
        native_files=None,
        on_title_change=None,
        on_saved=None,
        on_create_item=None,
        on_fullscreen_enter=None,
        on_fullscreen_exit=None,
    ):
        self.page = page
        self.ctx = ctx
        self.content = content
        self.native_files = native_files
        self.on_title_change = on_title_change
        self.on_saved = on_saved
        self.on_create_item = on_create_item
        # POS is the one screen that goes edge-to-edge (see show_center()):
        # these hide the app's own top header + sidebar/tab bar chrome for
        # the duration of the sale and restore it on exit -- optional so
        # POSCenter still works standalone (e.g. in tests) without a shell.
        self.on_fullscreen_enter = on_fullscreen_enter
        self.on_fullscreen_exit = on_fullscreen_exit

        # Cart lines keyed by item_id -> {"item": row, "qty": float}.
        # A dict (not a list) means "scan again" is a single lookup+bump,
        # never a duplicate row.
        self.cart: dict[int, dict] = {}
        self.cart_order: list[int] = []  # insertion order, for undo + display
        self.held: list[dict] = []  # [{"label": str, "cart": dict, "order": list, "customer_id": int|None}]
        self.customer_id: int | None = None
        self.received_digits: str = ""
        self.auto_print: bool = False
        # Session-only "last added" recall -- most-recent-first, deduped,
        # capped short on purpose (a quick-recall strip, not a history log).
        self.recent_item_ids: list[int] = []

    def money(self, value: float) -> str:
        return currency.format_amount(value, self.ctx.settings)

    @staticmethod
    def _qty(value) -> str:
        """Plain (non-currency) number formatting -- quantities."""
        return f"{float(value or 0):,.2f}"

    def notify(self, text: str, kind: str | None = None, sound_kind: str | None = None) -> None:
        toast(self.page, text, kind=kind, sound_kind=sound_kind)

    # ------------------------------------------------------------------ #
    # Entry point
    # ------------------------------------------------------------------ #

    def show_center(self) -> None:
        if self.on_title_change:
            self.on_title_change("نقطة البيع", "بيع سريع بالكاونتر — مسح أو لمس ثم دفع")
        if self.on_fullscreen_enter:
            self.on_fullscreen_enter()
        try:
            self._build()
        except Exception as exc:
            self._show_center_error(exc)

    def _exit_pos(self, _=None) -> None:
        """Leave fullscreen POS. Falls back to a no-op if the shell didn't
        wire an exit target (on_fullscreen_exit already restores chrome;
        on_saved, if provided, is what actually navigates elsewhere)."""
        if self.on_fullscreen_exit:
            self.on_fullscreen_exit()

    def _show_center_error(self, exc: Exception) -> None:
        if self.on_title_change:
            self.on_title_change("نقطة البيع", "تعذر تحميل شاشة نقطة البيع")
        message = str(exc).strip() or exc.__class__.__name__
        self.content.content = ft.Column(
            [
                ft.Icon(ft.Icons.ERROR_OUTLINE, size=42, color=Colors.DANGER_DARKER),
                ft.Text("تعذر تحميل شاشة نقطة البيع", size=18, weight=ft.FontWeight.BOLD),
                ft.Text(message, size=11, color=Colors.DANGER_DARKER, selectable=True),
                ft.FilledButton("إعادة المحاولة", icon=ft.Icons.REFRESH, on_click=lambda _: self.show_center()),
            ],
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self.page.update()

    # ------------------------------------------------------------------ #
    # Build
    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        items = self.ctx.items.pos_catalog()
        self.item_map = {int(i["id"]): i for i in items}
        categories = self.ctx.definitions.list_categories()
        customers = self.ctx.customers.list()

        state = {"query": "", "category_id": None}

        # ---- today's running total ---------------------------------------
        # A quick "how's today going" glance from inside the sale screen
        # itself -- no need to leave POS and open the full dashboard mid-shift.
        # Lives in the compact fullscreen header now (see pos_header below),
        # not stacked as its own row above the catalog.
        today_summary_text = ft.Text("", size=11, color=Colors.TEXT_SECONDARY)

        def refresh_today_summary():
            try:
                s = self.ctx.dashboard.today_summary()
            except Exception:
                today_summary_text.value = ""
                return
            today_summary_text.value = f"مبيعات اليوم: {s['count']} فاتورة · {self.money(s['total'])}"

        refresh_today_summary()

        # ---- recent items (session recall) ---------------------------------
        recent_row = ft.Row(spacing=6, scroll=ft.ScrollMode.AUTO, wrap=False, visible=False)

        def render_recent():
            controls = []
            for item_id in self.recent_item_ids:
                item = self.item_map.get(item_id)
                if item is None:
                    continue
                controls.append(
                    ft.Container(
                        ft.Row(
                            [ft.Icon(ft.Icons.HISTORY, size=13, color=Colors.PRIMARY_DARK),
                             ft.Text(str(item["name"]), size=11, weight=ft.FontWeight.W_600, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)],
                            spacing=4, tight=True,
                        ),
                        padding=ft.padding.symmetric(horizontal=10, vertical=6),
                        bgcolor=Colors.WHITE,
                        border=ft.border.all(1, Colors.BORDER),
                        border_radius=16,
                        on_click=lambda _, i=item_id: self._add_item(i),
                        ink=True,
                    )
                )
            recent_row.controls = controls
            recent_row.visible = bool(controls)

        render_recent()

        # ---- search / barcode bar -------------------------------------
        search_field = SelectAllTextField(
            label="بحث عن مادة",
            hint_text="اكتب اسم المادة...",
            prefix_icon=ft.Icons.SEARCH,
            dense=True,
            expand=True,
        )
        barcode_field = SelectAllTextField(
            label="مسح الباركود",
            hint_text="وجّه القارئ هنا واضغط Enter تلقائيًا",
            prefix_icon=ft.Icons.QR_CODE_2,
            dense=True,
            expand=True,
        )

        async def _focus_barcode_after_mount() -> None:
            # NOT autofocus=True above: requesting focus that early races
            # Flutter's text-input channel attaching, so the field reports
            # hasFocus=True without ever actually opening the on-screen
            # keyboard -- and because it already "has focus" as far as
            # Flutter is concerned, a real tap on it afterwards doesn't
            # trigger a focus change either, so the keyboard stays closed
            # until the user taps a different field first. A short yield
            # after the view has finished mounting lets the channel attach,
            # so the same focus() call actually raises the keyboard, and
            # still gives the hardware/USB "wedge" scanner a focused field
            # to type into without the user needing to tap first.
            await asyncio.sleep(0.2)
            barcode_field.focus()
            self.page.update()

        self.page.run_task(_focus_barcode_after_mount)

        def scan_button_handler(_):
            self.page.run_task(self._scan_with_camera)

        # ---- category chips ---------------------------------------------
        chips_row = ft.Row(spacing=8, scroll=ft.ScrollMode.AUTO, wrap=False)

        def set_category(cat_id: int | None):
            state["category_id"] = cat_id
            render_chips()
            render_grid()
            self.page.update()

        def render_chips():
            controls = []
            all_active = state["category_id"] is None
            controls.append(self._chip("الكل", all_active, Colors.TEXT_MUTED_DARK, lambda _: set_category(None)))
            for idx, cat in enumerate(categories):
                active = state["category_id"] == int(cat["id"])
                color = CHIP_PALETTE[idx % len(CHIP_PALETTE)]
                controls.append(self._chip(cat["name"], active, color, lambda _, c=int(cat["id"]): set_category(c)))
            chips_row.controls = controls

        # ---- item grid ------------------------------------------------
        # ResponsiveRow (not GridView) so tiles reflow by column count and
        # size naturally within a scrolling page — no bounded-height parent
        # required, unlike GridView(expand=True).
        grid = ft.ResponsiveRow(spacing=10, run_spacing=10)

        def render_grid():
            q = state["query"].strip().casefold()
            cat_id = state["category_id"]
            matched = []
            for item in items:
                if cat_id is not None and item.get("category_id") != cat_id:
                    continue
                if q and q not in str(item["name"]).casefold():
                    continue
                matched.append(item)

            tiles = []
            # Only worth separating "best sellers" out as their own labelled
            # section when the catalog isn't already filtered down (a search
            # or category pick is itself a stronger signal than the global
            # sales ranking) -- `items` already comes back best-sellers-first
            # from pos_catalog(), so this just makes that ordering visible.
            unfiltered = cat_id is None and not q
            if unfiltered:
                best = [it for it in matched if float(it.get("sold_qty") or 0) > 0]
                rest = [it for it in matched if float(it.get("sold_qty") or 0) <= 0]
                if best:
                    tiles.append(self._section_label("⭐ الأكثر مبيعًا"))
                    tiles.extend(self._item_tile(it) for it in best)
                    if rest:
                        tiles.append(self._section_label("كل المواد"))
                    tiles.extend(self._item_tile(it) for it in rest)
                else:
                    tiles.extend(self._item_tile(it) for it in matched)
            else:
                tiles.extend(self._item_tile(it) for it in matched)

            grid.controls = tiles
            grid.visible = bool(tiles)
            empty_box.visible = not tiles

        empty_box = empty_state(
            "لا توجد نتائج",
            icon=ft.Icons.SEARCH_OFF,
            hint="جرّب اسمًا مختلفًا أو امسح باركود المادة مباشرة",
        )
        empty_box.visible = False

        def search_changed(e):
            state["query"] = search_field.value or ""
            render_grid()
            self.page.update()

        search_field.on_change = search_changed

        def barcode_submit(e):
            code = (barcode_field.value or "").strip()
            barcode_field.value = ""
            if code:
                self._add_by_barcode(code)
            # barcode_field no longer collapses the cart on focus (see
            # collapse_cart_for_search() above), so this is just a safety
            # net -- forces the cart visible after every scan regardless of
            # what else may have hidden it.
            cart_wrap.visible = True
            barcode_field.focus()
            self.page.update()

        barcode_field.on_submit = barcode_submit

        # ---- cart panel -------------------------------------------------
        # Bounded height + its own scroll: the cart panel is pinned fixed
        # (with the bottom pay bar) instead of scrolling away with the
        # catalog, so a long cart needs to scroll internally rather than
        # growing without limit.
        # CART_FULL_HEIGHT is the normal height; CART_HALF_HEIGHT is used
        # while the name-search field is focused (see
        # collapse_cart_for_search below) so the cart shrinks instead of
        # disappearing entirely once the on-screen keyboard opens.
        CART_FULL_HEIGHT = 220
        CART_HALF_HEIGHT = CART_FULL_HEIGHT // 2
        cart_column = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, height=CART_FULL_HEIGHT)
        total_text = ft.Text("0.00", size=22, weight=ft.FontWeight.BOLD, color=Colors.PRIMARY_DARK)
        # A separate instance for the payment sheet -- total_text above is
        # permanently mounted in the sticky bottom pay bar, and a Flet
        # control can't be mounted in two places (bar + sheet) at once.
        sheet_total_text = ft.Text("0.00", size=22, weight=ft.FontWeight.BOLD, color=Colors.PRIMARY_DARK)
        count_text = ft.Text("0 بند", size=12, color=Colors.TEXT_SECONDARY)
        held_row = ft.Row(spacing=6, scroll=ft.ScrollMode.AUTO, wrap=False, visible=False)

        customer_dd = SearchSelect(
            label="عميل (اختياري)",
            hint_text="نقدي بدون عميل",
            choices=[(str(c["id"]), c["name"]) for c in customers],
        )

        received_display = ft.Text("0.00", size=22, weight=ft.FontWeight.BOLD)
        change_text = ft.Text("الباقي: 0.00", size=13, color=Colors.SUCCESS_DARK)
        auto_print_switch = ft.Switch(label="طباعة تلقائية بعد الدفع", value=pos_settings.auto_print_default(self.ctx.settings), scale=0.85)

        checkout_btn = hero_button("دفع", icon=ft.Icons.PAYMENTS_OUTLINED)

        def total_amount() -> float:
            return sum(float(row["item"]["selling_price"]) * float(row["qty"]) for row in self.cart.values())

        def received_amount() -> float:
            # The cashier types the cash handed over in the currently displayed
            # currency (SYP or USD) on the numpad; convert it to the stored USD
            # unit so it can be compared against total_amount() (also USD).
            try:
                typed_syp = float(self.received_digits) if self.received_digits else None
            except ValueError:
                typed_syp = None
            if typed_syp is None:
                return total_amount()
            return currency.to_stored(typed_syp, currency.get_effective_rate(self.ctx.settings))

        def remove_by_swipe(item_id: int):
            self.cart.pop(item_id, None)
            if item_id in self.cart_order:
                self.cart_order.remove(item_id)
            refresh_cart()
            self.page.update()

        def _apply_change_text():
            total = total_amount()
            change = received_amount() - total
            if change >= 0:
                change_text.value = f"الباقي للعميل: {self.money(change)}" if change > 0 else "المبلغ مضبوط بالتمام"
                change_text.color = Colors.SUCCESS_DARK
            elif self.customer_id:
                # A shortfall is a valid credit sale once a customer is
                # selected -- InvoiceService already records total-paid as
                # a receivable on that customer (see _require_party_for_credit
                # in invoice_service.py). This is not an error state.
                change_text.value = f"دفعة جزئية — سيُسجَّل {self.money(-change)} على حساب العميل"
                change_text.color = Colors.WARNING_DARK
            else:
                # No customer means InvoiceService forces paid=total
                # regardless of what was typed here (anonymous sales can't
                # carry a receivable) -- so an unselected customer with a
                # cash shortfall needs a stronger warning: the checkout
                # will still go through as "fully paid" even though the
                # cashier hasn't actually collected the full amount yet.
                change_text.value = f"⚠️ ناقص {self.money(-change)} — لا يوجد عميل لتسجيل الباقي، اختر عميلًا أو أكمل المبلغ"
                change_text.color = Colors.DANGER_DARK

        def refresh_cart():
            # Whatever hid cart_wrap (search/barcode field focus -- see
            # collapse_cart_for_search below) should never outlive an
            # actual cart change: refresh_cart() runs after every add,
            # remove, undo, hold and resume, regardless of *how* that
            # change happened (grid tap, camera scan, hardware barcode
            # wedge...). Forcing visibility back on here -- instead of only
            # on the search/barcode field's on_blur -- means the cart can
            # no longer get stuck hidden just because the field that
            # triggered the add never actually lost focus (a hardware
            # scanner keeps the barcode field focused between scans; a
            # catalog tap while the search field is still focused doesn't
            # blur it either). self._cart_wrap is only set once cart_wrap
            # exists below -- the very first refresh_cart() call during
            # initial layout happens before that, so this is a no-op then.
            cw = getattr(self, "_cart_wrap", None)
            if cw is not None:
                cw.visible = True
            total = total_amount()
            rows = []
            for item_id in self.cart_order:
                row = self.cart.get(item_id)
                if row is None:
                    continue
                card = self._cart_row(row, on_change=lambda: (refresh_cart(), self.page.update()))
                # Swipe-to-remove is safe here (unlike the parties/items
                # lists — see SWIPE_ACTIONS_NOTES.md): a cart line is a
                # pre-checkout, unsaved in-memory row that already has an
                # instant, no-confirmation "X" remove button right on the
                # row. The swipe just triggers that exact same removal, so
                # it introduces no new destructive action.
                rows.append(
                    ft.Dismissible(
                        key=f"cart-{item_id}",
                        content=card,
                        dismiss_direction=ft.DismissDirection.HORIZONTAL,
                        background=ft.Container(
                            content=ft.Row([ft.Icon(ft.Icons.DELETE_OUTLINE, color=Colors.WHITE, size=18), ft.Text("حذف", color=Colors.WHITE, size=11, weight=ft.FontWeight.W_600)], spacing=6, alignment=ft.MainAxisAlignment.START),
                            bgcolor=Colors.DANGER_DARK, border_radius=10, padding=ft.padding.symmetric(horizontal=14), alignment=ft.alignment.center_left,
                        ),
                        secondary_background=ft.Container(
                            content=ft.Row([ft.Text("حذف", color=Colors.WHITE, size=11, weight=ft.FontWeight.W_600), ft.Icon(ft.Icons.DELETE_OUTLINE, color=Colors.WHITE, size=18)], spacing=6, alignment=ft.MainAxisAlignment.END),
                            bgcolor=Colors.DANGER_DARK, border_radius=10, padding=ft.padding.symmetric(horizontal=14), alignment=ft.alignment.center_right,
                        ),
                        on_dismiss=lambda _, iid=item_id: remove_by_swipe(iid),
                    )
                )
            cart_column.controls = rows if rows else [empty_state("السلة فارغة", icon=ft.Icons.SHOPPING_CART_OUTLINED, hint="امسح باركود أو اضغط على مادة للإضافة")]
            total_text.value = self.money(total)
            sheet_total_text.value = self.money(total)
            count_text.value = f"{len(self.cart_order)} بند" if self.cart_order else "0 بند"
            self.received_digits = ""
            received_display.value = self.money(total)
            _apply_change_text()
            checkout_btn.disabled = not self.cart_order
            render_quick_cash()
            held_row.visible = bool(self.held)
            if self.held:
                held_row.controls = [
                    ft.Container(
                        ft.Row(
                            [ft.Icon(ft.Icons.PAUSE_CIRCLE_OUTLINE, size=15, color=Colors.WARNING_DARK), ft.Text(h["label"], size=11, weight=ft.FontWeight.W_600)],
                            spacing=4, tight=True,
                        ),
                        padding=ft.padding.symmetric(horizontal=10, vertical=6),
                        bgcolor=Colors.WARNING_BG,
                        border=ft.border.all(1, Colors.WARNING),
                        border_radius=20,
                        on_click=lambda _, idx=idx: resume_held(idx),
                    )
                    for idx, h in enumerate(self.held)
                ]

        # ---- numpad for amount received ---------------------------------
        def _sync_received_display():
            received_display.value = self.money(received_amount()) if self.received_digits else self.money(total_amount())
            _apply_change_text()

        def numpad_press(key: str):
            if key == "C":
                self.received_digits = ""
            elif key == "⌫":
                self.received_digits = self.received_digits[:-1]
            elif key == ".":
                if "." not in self.received_digits:
                    self.received_digits = (self.received_digits or "0") + "."
            else:
                if len(self.received_digits.replace(".", "")) >= 9:
                    return
                self.received_digits += key
            _sync_received_display()
            self.page.update()

        # ---- quick cash buttons ------------------------------------------
        # Common round amounts a cashier can tap instead of typing on the
        # numpad for every sale -- the exact total plus the next 2-3 round
        # figures above it, sized to whichever currency is displayed (SYP
        # notes vs USD notes have very different natural denominations).
        quick_cash_row = ft.Row(spacing=6, scroll=ft.ScrollMode.AUTO, wrap=False)

        def set_received(amount_displayed: float | None):
            self.received_digits = "" if amount_displayed is None else currency.format_plain(amount_displayed)
            _sync_received_display()
            self.page.update()

        def _quick_cash_button(label: str, amount_displayed: float | None):
            return ft.Container(
                ft.Text(label, size=12, weight=ft.FontWeight.W_600, color=Colors.PRIMARY_DARK),
                padding=ft.padding.symmetric(horizontal=12, vertical=8),
                bgcolor=Colors.BACKGROUND_ALT,
                border=ft.border.all(1, Colors.BORDER),
                border_radius=20,
                ink=True,
                on_click=lambda _, a=amount_displayed: set_received(a),
            )

        def render_quick_cash():
            total_displayed = currency.to_display(total_amount(), currency.get_effective_rate(self.ctx.settings))
            is_usd = currency.get_display_currency(self.ctx.settings) == currency.DISPLAY_CURRENCY_USD
            steps = [1, 5, 10, 20, 50, 100] if is_usd else [1000, 5000, 10000, 25000, 50000, 100000]
            max_buttons = pos_settings.quick_cash_count(self.ctx.settings)
            buttons = [_quick_cash_button("المبلغ بالتمام", None)]
            if total_displayed > 0:
                seen: set[float] = set()
                for step in steps:
                    val = math.ceil(total_displayed / step) * step
                    if val <= total_displayed or val in seen:
                        continue
                    seen.add(val)
                    buttons.append(_quick_cash_button(currency.format_display_value(val, self.ctx.settings, with_symbol=False), val))
                    if len(seen) == max_buttons:
                        break
            quick_cash_row.controls = buttons

        def numpad_key(label: str):
            return ft.Container(
                ft.Text(label, size=18, weight=ft.FontWeight.BOLD),
                width=52, height=42, alignment=ft.alignment.center,
                bgcolor=Colors.BACKGROUND_ALT, border_radius=10, ink=True,
                on_click=lambda _, k=label: numpad_press(k),
            )

        numpad = ft.Column(
            [
                ft.Row([numpad_key("1"), numpad_key("2"), numpad_key("3")], spacing=6),
                ft.Row([numpad_key("4"), numpad_key("5"), numpad_key("6")], spacing=6),
                ft.Row([numpad_key("7"), numpad_key("8"), numpad_key("9")], spacing=6),
                ft.Row([numpad_key("C"), numpad_key("0"), numpad_key("⌫")], spacing=6),
            ],
            spacing=6,
        )

        # ---- actions: undo / hold / new -----------------------------------
        def undo_last(_=None):
            if not self.cart_order:
                return
            last_id = self.cart_order[-1]
            row = self.cart.get(last_id)
            if row is None:
                self.cart_order.pop()
                refresh_cart()
                self.page.update()
                return
            if row["qty"] > 1:
                row["qty"] -= 1
            else:
                self.cart.pop(last_id, None)
                self.cart_order.pop()
            refresh_cart()
            self.page.update()

        def clear_cart(keep_customer: bool = False):
            self.cart = {}
            self.cart_order = []
            if not keep_customer:
                customer_dd.value = None
                self.customer_id = None

        def hold_cart(_=None):
            if not self.cart_order:
                self.notify("السلة فارغة")
                return
            label = f"تعليق #{len(self.held) + 1} · {time.strftime('%H:%M')}"
            self.held.append({"label": label, "cart": self.cart, "order": self.cart_order, "customer_id": self.customer_id})
            clear_cart()
            refresh_cart()
            self.notify("تم تعليق الفاتورة — يمكنك بدء بيع جديد")
            self.page.update()

        def resume_held(idx: int):
            if self.cart_order:
                self.notify("أنهِ أو علّق السلة الحالية أولًا")
                return
            held_ticket = self.held.pop(idx)
            self.cart = held_ticket["cart"]
            self.cart_order = held_ticket["order"]
            self.customer_id = held_ticket["customer_id"]
            customer_dd.value = str(self.customer_id) if self.customer_id else None
            refresh_cart()
            self.page.update()

        # ---- checkout -----------------------------------------------------
        def do_checkout(_=None) -> bool:
            if not self.cart_order:
                self.notify("السلة فارغة")
                return False
            try:
                lines = [
                    InvoiceLineInput(
                        description=str(row["item"]["name"]),
                        item_id=int(row["item"]["id"]),
                        quantity=float(row["qty"]),
                        unit_price=float(row["item"]["selling_price"]),
                    )
                    for row in (self.cart[i] for i in self.cart_order)
                ]
                total = total_amount()
                received = received_amount()
                paid = min(received, total) if self.customer_id else total
                invoice_id = self.ctx.invoices.create_invoice(
                    invoice_type="sale",
                    lines=lines,
                    customer_id=self.customer_id,
                    paid_amount=paid,
                )
                self.notify(f"تم البيع بنجاح — فاتورة #{invoice_id}" + (f" · الباقي {self.money(max(0, received - total))}" if received > total else ""))
                if auto_print_switch.value and self.native_files is not None:
                    self.page.run_task(self._print_receipt, invoice_id)
                clear_cart()
                refresh_cart()
                refresh_today_summary()
                if self.on_saved:
                    self.on_saved()
                self.page.update()
                return True
            except Exception as exc:
                self.notify(str(exc), kind="error")
                return False

        # ---- payment sheet --------------------------------------------
        # Everything needed to actually take money (customer, numpad, quick
        # cash, auto-print) used to sit permanently inside the cart column,
        # pushing "دفع" itself to the bottom of a long scroll once the cart
        # had more than a couple of lines. It now opens on demand from the
        # sticky total bar instead, so it only takes over the screen the
        # moment the cashier is actually paying.
        # is_scroll_controlled + maintain_bottom_view_insets_padding: same
        # fix as new_form_sheet() (components/form_sheet.py) -- without
        # is_scroll_controlled, Flutter shrink-wraps a modal BottomSheet to
        # a ~9/16-screen ceiling, and this sheet's content (customer field +
        # totals + change text + quick-cash row + numpad + print switch +
        # confirm button) is tall enough to blow past that on most phones.
        # The confirm button was landing below that ceiling with no scroll
        # to reach it -- effectively invisible/unusable in quick sale.
        payment_sheet = ft.BottomSheet(
            content=ft.Container(),
            is_scroll_controlled=True,
            enable_drag=True,
            maintain_bottom_view_insets_padding=True,
        )

        def confirm_payment(_=None):
            if do_checkout():
                self.page.close(payment_sheet)

        def open_payment_sheet(_=None):
            if not self.cart_order:
                self.notify("السلة فارغة")
                return
            payment_sheet.content = ft.Container(
                ft.Column(
                    [
                        ft.Container(width=44, height=5, bgcolor=Colors.BORDER_STRONG, border_radius=10, alignment=ft.alignment.center),
                        ft.Text("إتمام الدفع", size=18, weight=ft.FontWeight.BOLD),
                        customer_dd,
                        ft.Row(
                            [
                                ft.Column([ft.Text("الإجمالي", size=11, color=Colors.TEXT_SECONDARY), sheet_total_text], spacing=2),
                                ft.Column([ft.Text("المستلم", size=11, color=Colors.TEXT_SECONDARY), received_display], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.END, expand=True),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        change_text,
                        quick_cash_row,
                        numpad,
                        auto_print_switch,
                        hero_button("بيع", icon=ft.Icons.POINT_OF_SALE_OUTLINED, on_click=confirm_payment),
                    ],
                    spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True,
                    scroll=ft.ScrollMode.AUTO,
                ),
                padding=ft.padding.only(left=18, right=18, top=12, bottom=24),
                bgcolor=Colors.WHITE,
                border_radius=ft.border_radius.only(top_left=24, top_right=24),
            )
            self.page.open(payment_sheet)

        checkout_btn.on_click = open_payment_sheet

        def customer_changed(_=None):
            self.customer_id = int(customer_dd.value) if customer_dd.value else None
            # A shortfall's meaning (blocking warning vs. valid credit sale)
            # depends on whether a customer is selected, so re-evaluate the
            # change/credit message the moment that changes.
            _apply_change_text()
            self.page.update()

        customer_dd.on_change = customer_changed

        # ---- assemble layout ------------------------------------------
        render_chips()
        render_grid()
        refresh_cart()

        catalog_pane = ft.Column(
            [
                ft.Row([search_field], spacing=10),
                ft.Row([barcode_field, ft.IconButton(icon=ft.Icons.CAMERA_ALT_OUTLINED, tooltip="مسح بالكاميرا", on_click=scan_button_handler, icon_color=Colors.PRIMARY)], spacing=10),
                recent_row,
                chips_row,
                grid,
                empty_box,
            ],
            spacing=10,
        )

        # Cart pane keeps only what a cashier needs while still browsing --
        # customer, received-amount numpad, quick cash and auto-print all
        # moved into the payment sheet (see open_payment_sheet above), so
        # this column stays short even with several lines in the cart.
        cart_pane = ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("السلة", size=16, weight=ft.FontWeight.BOLD, expand=True),
                            count_text,
                            ft.IconButton(icon=ft.Icons.PAUSE_CIRCLE_OUTLINED, tooltip="تعليق الفاتورة", on_click=hold_cart, icon_size=IconSize.HEADER),
                            ft.IconButton(icon=ft.Icons.UNDO, tooltip="تراجع عن آخر إضافة", on_click=undo_last, icon_size=IconSize.HEADER),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    held_row,
                    cart_column,
                ],
                spacing=10,
            ),
            padding=14,
            bgcolor=Colors.WHITE,
            border=ft.border.all(1, Colors.BORDER),
            border_radius=Radius.LG,
            shadow=Shadow.MD,
        )

        # Compact fullscreen header: replaces the app's own top bar (hidden
        # via on_fullscreen_enter) with an exit button + title + the "how's
        # today going" glance, all in one dense row instead of three stacked
        # ones -- reclaims vertical space specifically for the mobile
        # fullscreen layout.
        pos_header = ft.Container(
            ft.Row(
                [
                    ft.IconButton(icon=ft.Icons.ARROW_FORWARD_IOS if self.page.rtl else ft.Icons.ARROW_BACK_IOS_NEW, icon_size=IconSize.HEADER, tooltip="إنهاء البيع السريع", on_click=self._exit_pos),
                    ft.Column(
                        [ft.Text("نقطة البيع", size=15, weight=ft.FontWeight.BOLD), today_summary_text],
                        spacing=0, expand=True,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=6,
            ),
            padding=ft.padding.only(left=14, right=14, top=10, bottom=10),
            bgcolor=Colors.WHITE,
            border=ft.border.only(bottom=ft.BorderSide(1, Colors.BORDER)),
        )

        # Sticky pay bar: pinned outside the scrolling body below (not one
        # more item at the end of a long column) so "الإجمالي + دفع" stays
        # reachable in one tap no matter how many lines are in the cart or
        # how far the catalog grid has been scrolled.
        bottom_pay_bar = ft.Container(
            ft.Row(
                [
                    ft.Column([ft.Text("الإجمالي", size=11, color=Colors.TEXT_SECONDARY), total_text], spacing=1),
                    checkout_btn,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.only(left=18, right=18, top=10, bottom=10),
            bgcolor=Colors.WHITE,
            border=ft.border.only(top=ft.BorderSide(1, Colors.BORDER)),
            shadow=ft.BoxShadow(blur_radius=16, color=Colors.BORDER, offset=ft.Offset(0, -4)),
        )
        checkout_btn.width = 160

        # Wrapped so it can be hidden as a unit (see collapse_cart_for_search
        # below) without touching cart_pane's own children/state.
        cart_wrap = ft.Container(cart_pane, padding=ft.padding.only(left=18, right=18, bottom=8))
        # Exposed on self so refresh_cart() (defined above, called after
        # every cart mutation) can force it back visible regardless of
        # focus/blur -- see the comment at the top of refresh_cart().
        self._cart_wrap = cart_wrap

        # Shrink the cart to half height while the name-search field is
        # focused: on phones, the on-screen keyboard that focus opens
        # shrinks the visible viewport enough that the fixed cart_pane
        # pinned below the scrolling catalog can end up overlapping the
        # search field/results instead of sitting cleanly beneath them.
        # Halving cart_column's height for the moment search is actually
        # being typed reclaims that space without hiding the cart outright
        # (its total is still visible in bottom_pay_bar the whole time, and
        # the shortened list still scrolls), and it returns to full height
        # the instant the field loses focus.
        #
        # Deliberately NOT wired to barcode_field: a hardware/USB "wedge"
        # scanner keeps that field focused for the whole session (see the
        # comment in barcode_submit() below), so shrinking on its focus
        # used to leave the cart stuck small with no blur event to restore
        # it.
        def collapse_cart_for_search(_=None):
            cart_column.height = CART_HALF_HEIGHT
            self.page.update()

        def restore_cart_after_search(_=None):
            cart_column.height = CART_FULL_HEIGHT
            self.page.update()

        search_field.on_focus = collapse_cart_for_search
        search_field.on_blur = restore_cart_after_search

        # Only the catalog scrolls now. The cart pane used to sit inside
        # this same scrolling body (side-by-side on desktop via
        # ResponsiveRow, stacked below the catalog on mobile), which meant
        # scrolling through the catalog grid could scroll the cart out of
        # view too. The cart is pulled out below and pinned fixed together
        # with the sticky pay bar instead, so it (and the total/checkout
        # button) stay reachable no matter how far the catalog is scrolled.
        scroll_body = ft.Column(
            [catalog_pane],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        self.content.content = ft.Column(
            [
                pos_header,
                ft.Container(scroll_body, padding=ft.padding.only(left=18, right=18, top=14, bottom=10), expand=True),
                cart_wrap,
                bottom_pay_bar,
            ],
            spacing=0,
            expand=True,
        )
        self.page.update()

        # expose closures needed by helper methods below
        self._render_grid = render_grid
        self._refresh_cart = refresh_cart
        self._search_field = search_field
        self._barcode_field = barcode_field
        self._render_recent = render_recent
        self._refresh_today_summary = refresh_today_summary

    # ------------------------------------------------------------------ #
    # Small UI helpers
    # ------------------------------------------------------------------ #

    def _chip(self, label: str, active: bool, color: str, on_click):
        return ft.Container(
            ft.Text(label, size=12, weight=ft.FontWeight.W_600, color=Colors.WHITE if active else color),
            padding=ft.padding.symmetric(horizontal=14, vertical=8),
            bgcolor=color if active else Colors.WHITE,
            border=ft.border.all(1, color if active else Colors.BORDER),
            border_radius=20,
            on_click=on_click,
            ink=True,
        )

    def _section_label(self, text: str) -> ft.Container:
        """Full-width label dropped inline into the tile ResponsiveRow to
        mark a section (e.g. best sellers) without needing a second grid."""
        return ft.Container(
            ft.Text(text, size=12, weight=ft.FontWeight.BOLD, color=Colors.TEXT_SECONDARY),
            col={"xs": 12},
            padding=ft.padding.only(top=4, bottom=2),
        )

    def _item_tile(self, item: dict) -> ft.Container:
        item_id = int(item["id"])
        is_service = item["item_type"] == "خدمة"
        qty_badge = None
        out_of_stock = False
        if not is_service:
            available = float(item.get("quantity") or 0)
            out_of_stock = available <= 0
            badge_color = Colors.DANGER_DARK if out_of_stock else Colors.TEXT_FAINT
            qty_badge = ft.Text(f"م: {self._qty(item['quantity'])}", size=10, color=badge_color, weight=ft.FontWeight.BOLD if out_of_stock else None)
        idx = 0
        # stable-ish color by category id for a touch of visual grouping
        if item.get("category_id"):
            idx = int(item["category_id"])
        color = CHIP_PALETTE[idx % len(CHIP_PALETTE)]
        return ft.Container(
            ft.Column(
                [
                    ft.Container(
                        ft.Icon(ft.Icons.INVENTORY_2_OUTLINED if not is_service else ft.Icons.DESIGN_SERVICES_OUTLINED, color=color, size=26),
                        width=44, height=44, alignment=ft.alignment.center, bgcolor=Colors.BACKGROUND_ALT, border_radius=12,
                    ),
                    ft.Text(item["name"], size=12, weight=ft.FontWeight.W_600, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, text_align=ft.TextAlign.CENTER),
                    ft.Text(self.money(item["selling_price"]), size=13, weight=ft.FontWeight.BOLD, color=Colors.PRIMARY_DARK),
                    qty_badge or ft.Container(height=1),
                ],
                spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=10,
            bgcolor=Colors.WHITE,
            # Out-of-stock is a nudge, not a block -- the sale is still
            # allowed (e.g. a known backorder), just flagged visually via
            # the border so the cashier notices before scanning more.
            border=ft.border.all(1.5 if out_of_stock else 1, Colors.DANGER if out_of_stock else Colors.BORDER),
            border_radius=Radius.MD,
            ink=True,
            col={"xs": 6, "sm": 4, "md": 4, "lg": 3, "xl": 2},
            on_click=lambda _, i=item_id: self._add_item(i),
        )

    def _cart_row(self, row: dict, on_change) -> ft.Container:
        item = row["item"]
        item_id = int(item["id"])
        is_service = item["item_type"] == "خدمة"

        def change_qty(delta: float):
            new_qty = row["qty"] + delta
            if new_qty <= 0:
                self.cart.pop(item_id, None)
                if item_id in self.cart_order:
                    self.cart_order.remove(item_id)
            else:
                row["qty"] = new_qty
            on_change()

        def remove(_=None):
            self.cart.pop(item_id, None)
            if item_id in self.cart_order:
                self.cart_order.remove(item_id)
            on_change()

        line_total = float(item["selling_price"]) * float(row["qty"])
        # Informational only (see item tile note above) -- InvoiceService
        # itself has no stock guard, so this never blocks checkout; it just
        # lets the cashier catch it before printing the receipt.
        exceeds_stock = (not is_service) and float(row["qty"]) > float(item.get("quantity") or 0)
        warning_line = None
        if exceeds_stock:
            warning_line = ft.Text(
                f"⚠️ المتوفر فعليًا: {self._qty(item.get('quantity'))} فقط",
                size=10, color=Colors.DANGER_DARK, weight=ft.FontWeight.W_600,
            )
        return ft.Container(
            ft.Column(
                [
                    ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(item["name"], size=12, weight=ft.FontWeight.W_600, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Text(f"{self.money(item['selling_price'])} × {self._qty(row['qty'])} = {self.money(line_total)}", size=11, color=Colors.TEXT_SECONDARY),
                                ],
                                spacing=1, expand=True,
                            ),
                            stepper_icon_button(ft.Icons.REMOVE_CIRCLE_OUTLINE, lambda _: change_qty(-1)),
                            ft.Text(self._qty(row["qty"]), size=12, weight=ft.FontWeight.BOLD),
                            stepper_icon_button(ft.Icons.ADD_CIRCLE_OUTLINE, lambda _: change_qty(1)),
                            stepper_icon_button(ft.Icons.CLOSE, remove, danger=True),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=2,
                    ),
                    *([warning_line] if warning_line else []),
                ],
                spacing=2,
            ),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            bgcolor=Colors.BACKGROUND_ALT,
            border=ft.border.all(1, Colors.DANGER) if exceeds_stock else None,
            border_radius=10,
        )

    # ------------------------------------------------------------------ #
    # Cart mutation
    # ------------------------------------------------------------------ #

    def _add_item(self, item_id: int, qty_delta: float = 1.0) -> None:
        item = self.item_map.get(item_id)
        if item is None:
            return
        row = self.cart.get(item_id)
        if row is None:
            self.cart[item_id] = {"item": item, "qty": qty_delta}
            self.cart_order.append(item_id)
        else:
            row["qty"] += qty_delta
        self._remember_recent(item_id)
        self._refresh_cart()
        self.page.update()

    def _remember_recent(self, item_id: int) -> None:
        """Push ``item_id`` to the front of the session recall strip."""
        if item_id in self.recent_item_ids:
            self.recent_item_ids.remove(item_id)
        self.recent_item_ids.insert(0, item_id)
        del self.recent_item_ids[8:]  # short strip, not a history log
        render = getattr(self, "_render_recent", None)
        if render is not None:
            render()

    def _add_by_barcode(self, code: str) -> None:
        found = self.ctx.items.find_by_barcode(code)
        if not found:
            self._offer_create_item(code)
            return
        item_id = int(found["id"])
        self.item_map[item_id] = found
        # A code registered against a specific selling unit (e.g. a
        # carton barcode) should add that unit's full quantity in one
        # scan, not just 1 base unit -- see item_barcodes.unit_id /
        # ItemRepository.find_by_barcode.
        qty_delta = 1.0
        matched_unit_id = found.get("matched_unit_id")
        if matched_unit_id:
            unit_row = next(
                (u for u in self.ctx.items.units(item_id) if int(u["id"]) == int(matched_unit_id)), None
            )
            if unit_row:
                qty_delta = float(unit_row.get("conversion_factor") or 1)
        # Real haptic feedback on scan would still need a native platform
        # channel added to the flet_native_files extension (Dart/Kotlin/
        # Swift) -- out of reach here with no Flutter toolchain or device to
        # verify against. The audible side of this is no longer a gap
        # though: this toast() call plays a real chime through
        # core/sound.py (audioplayers' AudioPool, no native code needed --
        # see its module docstring for why that's a different case than
        # vibration). It's pinned to the dedicated "scan" tone (sound_kind=
        # "scan") rather than the generic "success" chime a checkmark
        # message would otherwise infer -- a cashier scanning dozens of
        # items a minute gets a short, distinct, non-fatiguing tone tied
        # specifically to "item recognized", separate from success sounds
        # elsewhere in the app. The admin-configurable "الباركود" setting
        # below still picks how much on-screen detail this toast shows --
        # independent of the "الصوت" tab's own settings for whether/how
        # loud each tone kind plays.
        if barcode_settings.scan_feedback_mode(self.ctx.settings) == "brief":
            self.notify("✔", sound_kind="scan")
        else:
            qty_note = f" × {self._qty(qty_delta)}" if qty_delta != 1 else ""
            self.notify(f"✔ أُضيف: {found['name']}{qty_note}", sound_kind="scan")
        self._add_item(item_id, qty_delta)

    def _offer_create_item(self, code: str) -> None:
        # A scan that matched nothing gets its own dedicated tone
        # (sound_kind="barcode_error") rather than the generic 'error'
        # chime -- distinct and short enough that a cashier scanning fast
        # immediately reads it as "no match" instead of "something broke",
        # whether or not this ends in the "create item?" dialog below.
        if self.on_create_item is None:
            self.notify("لا توجد مادة بهذا الباركود", kind="error", sound_kind="barcode_error")
            return
        sound_engine.play(self.page, "barcode_error")
        dialog = ft.AlertDialog(modal=True, title=ft.Text("لا توجد مادة بهذا الباركود"))

        def create(_=None) -> None:
            self.page.close(dialog)
            self.on_create_item(code)

        def cancel(_=None) -> None:
            self.page.close(dialog)

        dialog.content = ft.Text(f"الباركود الممسوح: {code}\nهل تريد إنشاء مادة جديدة بهذا الباركود؟")
        dialog.actions = [ft.TextButton("إلغاء", on_click=cancel), ft.FilledButton("إنشاء مادة جديدة", on_click=create)]
        self.page.open(dialog)

    async def _scan_with_camera(self) -> None:
        if self.native_files is None:
            self.notify("مسح الباركود غير مهيأ في هذا البناء")
            return
        try:
            code = await self.native_files.scan_barcode()
        except Exception as exc:
            self.notify(str(exc), kind="error")
            return
        if code:
            self._add_by_barcode(code)

    async def _print_receipt(self, invoice_id: int) -> None:
        try:
            html = self.ctx.documents.invoice_html(invoice_id)
            await self.native_files.print_html(html, name=f"nano-invoice-{invoice_id}")
        except Exception as exc:
            self.notify(str(exc), kind="error")


__all__ = ["POSCenter"]
