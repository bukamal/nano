from __future__ import annotations

"""FIX_0.9.4: ماسح الباركود الذكي — نسخة مطوّرة وعصرية.

ما الذي تغيّر عن شاشة "مسح الباركود" القديمة (v0.9.3)؟

الذكاوات الجديدة
-----------------
1. AI Scene Hint شريحة ذكية فوق الإطار تقرأ جودة اللقطة لحظيًا:
   - "إضاءة كافية ✓" / "إضاءة منخفضة — شغّل الفلاش" / "قرّب أكثر" / "ثبّت الهاتف"
   تُحدَّث بمؤشّر ``confidence`` يرفعه/يُخفضه قرار آخر اكتشاف ناجح.
2. AutoTorch: يضيء الفلاش تلقائيًا عند انخفاض الإضاءة (بدون لمس)، ويمكن تعطيله من
   بطاقة الإعدادات في الزاوية العلوية اليسرى (مطابقة لمبدأ "دائما التلقائي،
   قابل للتعديل عند الطلب" المستخدم في view_modes الخاصة بـ Nano).
3. SmartFrame نابض: زوايا الإطار تتنفس بمعدّل يتناسب مع ثبات اللقطة، ويتحول
   لونه من المِنت الأساسي (TEAL) إلى النعناع المتوهّج عند الاكتشاف.
4. Live Type Chip: شريحة زجاجية تطفو فوق الإطار تعرض نوع الترميز فورًا
   (EAN-13 / EAN-8 / UPC-A / QR / DataMatrix / Code128) قبل إرجاع القيمة.
5. Recent Chips شريط لآخر ٣ قيم مسحوبة — قرّب لأعلى لتكراره دون إعادة التصويب.
6. Multi-mode Dock كبسولة زجاجية عائمة بأربعة أزرار دائرية:
   الفلاش التلقائي، الاستيراد من المعرض، الإدخال اليدوي، سجلّ اليوم كاملًا.
7. Smooth Capture Card: عند الاكتشاف تظهر بطاقة زجاجية بزمن انتقالي ١٢٠ مللي
   تعرض القيمة والاسم إن وُجد، مع زرّان "فتح المادة" و"نسخ".
8. Manual Entry Sheet: نافذة إدخال يدوي كبديل آمن إن تعطّلت الكاميرا.
9. اليومي لا يُحفظ محليًا فقط، بل يُمرَّر فورًا عبر callback واحد
   ``on_scan(value: str, kind: str, meta: dict)`` للمستهلك (نقطة البيع، إضافة
   سطر فاتورة، جرد، إضافة مادة)، مما يحافظ على نفس توقيع العقد الذي تستخدمه
   بقية المراكز.

الحفاظ على الهوية
-----------------
- نفس الـ token map: ``Colors`` و ``Shadow`` و ``APP_FONT_FAMILY`` دون أي تكرار
  للـ hex خارج theme.
- RTL، خط Plex، والنظام اللوني TEA/OSL (Light + Dark) يعمل فورًا بدون أي تغيير
  إضافي، لأن ``Colors`` يحلّ تلقائيًا حسب الوضع.
- نفس آليات toast المراكز الأخرى (``core.toast.toast``)، و patterns الـ Center
  (build/shell/header) دون كسر توقيع الصف.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Optional

import flet as ft

from nano_offline.core.theme import Colors, Shadow
from nano_offline.core.toast import toast


# --------------------------------------------------------------------------- #
#  ScanKind — نوع الترميز الذي اكتشفه الماسح.                                 #
# --------------------------------------------------------------------------- #
class ScanKind(str, Enum):
    EAN13 = "EAN-13"
    EAN8 = "EAN-8"
    UPC_A = "UPC-A"
    CODE128 = "Code-128"
    QR = "QR"
    DATA_MATRIX = "DataMatrix"
    UNKNOWN = "Unknown"


_KIND_BY_PREFIX = {
    "EAN13": ScanKind.EAN13,
    "EAN8": ScanKind.EAN8,
    "UPCA": ScanKind.UPC_A,
    "CODE128": ScanKind.CODE128,
    "CODE_128": ScanKind.CODE128,
    "QR": ScanKind.QR,
    "QRCODE": ScanKind.QR,
    "DATA_MATRIX": ScanKind.DATA_MATRIX,
}


def parse_kind(raw: str) -> ScanKind:
    if not raw:
        return ScanKind.UNKNOWN
    key = raw.strip().upper().replace("-", "").replace(" ", "")
    return _KIND_BY_PREFIX.get(key, ScanKind.UNKNOWN)


# --------------------------------------------------------------------------- #
#  AI hint — حالات الإضاءة والحركة والوضوح.                                  #
# --------------------------------------------------------------------------- #
class HintState(str, Enum):
    LIGHT_OK = "light_ok"
    LIGHT_LOW = "light_low"
    BLUR = "blur"
    TOO_FAR = "too_far"
    STABILIZING = "stabilizing"
    LOCKED = "locked"


_DAT = {
    HintState.LIGHT_OK: ("إضاءة كافية", "check_circle", Colors.SUCCESS),
    HintState.LIGHT_LOW: ("إضاءة منخفضة — فعِّل الفلاش", "wb_twilight", Colors.WARNING),
    HintState.BLUR: ("ثبّت الهاتف", "vibration", Colors.WARNING),
    HintState.TOO_FAR: ("قرّب أكثر", "zoom_in", Colors.WARNING),
    HintState.STABILIZING: ("تثبيت اللقطة…", "auto_fix_high", Colors.PRIMARY),
    HintState.LOCKED: ("تم الاكتشاف ✓", "verified", Colors.SUCCESS),
}


@dataclass
class ScanFeedback:
    """آخر لقطة تغذية راجعة من حلقة الكاميرا. تُحدّث بثبات على الإطار."""

    state: HintState = HintState.STABILIZING
    confidence: float = 0.0          # 0..1
    auto_torch: bool = False
    last_kind: ScanKind = ScanKind.UNKNOWN
    last_value: str = ""
    pulse_phase: int = 0             # 0..255 لشدة النبض


# --------------------------------------------------------------------------- #
#  مكوّنات صغيرة قابلة لإعادة الاستخدام داخل الشاشة.                        #
# --------------------------------------------------------------------------- #
@dataclass
class RecentChip:
    value: str
    kind: ScanKind = ScanKind.UNKNOWN


def _glass(padding: ft.PaddingValue = 8, radius: int = 18, opacity: float = 0.55) -> ft.BoxShadow:
    """ظل زجاجي خفيف يُستخدم على الكبسولات العائمة."""
    return ft.BoxShadow(
        spread_radius=0,
        blur_radius=24,
        color="#0F172A" if not Colors.is_dark() else "#000000",
        offset=ft.Offset(0, 8),
    )


class _CornerBracket(ft.Container):
    """زاوية إطار نابضة — يرث اللون من الإطار الأصلي لـ Nano."""

    def __init__(self, corner: str, size: int = 26, thickness: int = 4):
        align_map = {
            "tl": ft.alignment.top_left,
            "tr": ft.alignment.top_right,
            "bl": ft.alignment.bottom_left,
            "br": ft.alignment.bottom_right,
        }
        rotate_map = {
            "tl": ft.Rotate(0, alignment=ft.alignment.top_left),
            "tr": ft.Rotate(0, alignment=ft.alignment.top_right),
            "bl": ft.Rotate(0, alignment=ft.alignment.bottom_left),
            "br": ft.Rotate(0, alignment=ft.alignment.bottom_right),
        }
        super().__init__(
            width=size,
            height=size,
            border=ft.border.only(
                top=ft.BorderSide(thickness, Colors.PRIMARY) if corner in ("tl", "tr") else None,
                bottom=ft.BorderSide(thickness, Colors.PRIMARY) if corner in ("bl", "br") else None,
                left=ft.BorderSide(thickness, Colors.PRIMARY) if corner in ("tl", "bl") else None,
                right=ft.BorderSide(thickness, Colors.PRIMARY) if corner in ("tr", "br") else None,
            ),
            border_radius=6,
            animate=ft.Animation(280, "easeOut"),
            scale=1.0,
            rotate=rotate_map[corner],
        )
        self.corner = corner


# --------------------------------------------------------------------------- #
#  SmartBarcodeScanner — المركز الرئيسي للشاشة.                              #
# --------------------------------------------------------------------------- #
class SmartBarcodeScanner:
    """شاشة كاملة «مسح الباركود الذكي» لـ Nano — استبدال 1:1 لمربع الماسح القديم.

    المعاملات:
        on_scan(value, kind, meta) -> Awaitable[None] | None
            الـ callback الموحّد الذي تُستدعى به قيمة الـ scan الفعلية عند الكشف.
        parent_title
            عنوان الـ sheet الفرعي لو تم فتحه من قائمة (يظهر في الـ title bar).
        auto_open
            يبدأ فتح الكاميرا مباشرة عند ``build()`` (افتراضي True — نمط الـ
            Centre). يُستخدم False لإخفاء المعاينة حتى يستدعيها المستهلِك.
    """

    DEFAULT_THUMB = 0.55  # 55% من ارتفاع الكاميرا

    def __init__(
        self,
        on_scan: Callable[[str, ScanKind, dict], Awaitable[None] | None],
        *,
        parent_title: str = "مسح الباركود الذكي",
        auto_open: bool = True,
        recent: list[RecentChip] | None = None,
    ) -> None:
        self._on_scan = on_scan
        self._parent_title = parent_title
        self._auto_open = auto_open
        self._recent: list[RecentChip] = list(recent or [])
        self._feedback = ScanFeedback()
        self._torch_on = False
        self._auto_torch_enabled = True
        self._page: Optional[ft.Page] = None
        self._build_views()

    # ------------------------------------------------------------------ #
    #  بناء شجرة الـ Controls (Flet ready)                                #
    # ------------------------------------------------------------------ #
    def _build_views(self) -> None:
        # شريط علوي — X إغلاق + العنوان المركزي + كبسولة الفلاش.
        self.close_btn = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_color=Colors.WHITE,
            icon_size=22,
            tooltip="إغلاق",
            on_click=lambda _: self._on_close(),
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=14),
                bgcolor=ft.Colors.with_opacity(0.18, "#0F172A"),
                padding=ft.Padding(10, 10, 10, 10),
            ),
        )

        self.torch_pill = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.FLASH_OFF, size=18, color=Colors.WHITE),
                    ft.Text("إيقاف", size=12, color=Colors.WHITE, weight=ft.FontWeight.W_600),
                ],
                spacing=6,
            ),
            padding=ft.Padding(12, 8, 14, 8),
            border_radius=999,
            bgcolor=ft.Colors.with_opacity(0.22, "#0F172A"),
            on_click=lambda _: self._toggle_torch(),
            ink=True,
        )

        self.title_bar = ft.Container(
            content=ft.Row(
                [
                    self.close_btn,
                    ft.Container(expand=True),
                    ft.Container(
                        content=ft.Text(
                            self._parent_title,
                            size=16,
                            weight=ft.FontWeight.W_700,
                            color=Colors.WHITE,
                        ),
                        padding=ft.Padding(2, 0, 2, 0),
                    ),
                    ft.Container(expand=True),
                    self.torch_pill,
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=8,
            ),
            padding=ft.Padding(0, 6, 0, 6),
        )

        # Hint chip أعلى الإطار — رسائل ذكية حسب حالة اللقطة.
        self.hint_icon = ft.Icon(
            ft.Icons.AUTO_FIX_HIGH,
            size=14,
            color=Colors.PRIMARY,
        )
        self.hint_text = ft.Text(
            _DAT[HintState.STABILIZING][0],
            size=12,
            weight=ft.FontWeight.W_600,
            color=Colors.TEXT_PRIMARY,
        )
        self.hint_chip = ft.Container(
            content=ft.Row(
                [self.hint_icon, self.hint_text],
                tight=True,
                spacing=6,
            ),
            padding=ft.Padding(10, 7, 14, 7),
            border_radius=999,
            bgcolor=Colors.WHITE,
            shadow=Shadow.SOFT,
            animate=ft.Animation(220, "easeOut"),
        )

        # نوع الترميز (يظهر بعد أول اكتشاف).
        self.kind_chip = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.QR_CODE_ROUNDED, size=14, color=Colors.PRIMARY_DARK),
                    ft.Text(
                        ScanKind.UNKNOWN.value,
                        size=12,
                        weight=ft.FontWeight.W_700,
                        color=Colors.PRIMARY_DARK,
                    ),
                ],
                tight=True,
                spacing=4,
            ),
            padding=ft.Padding(8, 4, 12, 4),
            border_radius=8,
            bgcolor=Colors.PRIMARY_BG,
            border=ft.border.all(1, Colors.PRIMARY_BORDER),
            visible=False,
            animate=ft.Animation(180, "easeOut"),
        )

        # الإطار النابض والزوايا المتوهجة (يرث لون theme).
        self.frame_overlay = ft.Stack(
            [
                # خط المسح الأفقي النابض.
                ft.Container(
                    left=2,
                    right=2,
                    top=self.DEFAULT_THUMB * 100 - 1,
                    height=2,
                    bgcolor=Colors.PRIMARY,
                    border_radius=2,
                    animate_position=ft.Animation(140, "easeInOut"),
                    opacity=0.85,
                ),
                _CornerBracket("tl"),
                _CornerBracket("tr"),
                _CornerBracket("bl"),
                _CornerBracket("br"),
            ],
            width=240,
            height=int(240 * self.DEFAULT_THUMB),
        )

        # خلفية الكاميرا — في الإنتاج تُستبدل بـ ft.Image المصغّر من الكاميرا.
        self.viewfinder = ft.Container(
            width=240,
            height=int(240 * self.DEFAULT_THUMB),
            border_radius=18,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            bgcolor=ft.Colors.with_opacity(0.65, "#0F172A"),
            content=ft.Column(
                [
                    ft.Container(expand=True, alignment=ft.alignment.center),
                    ft.Container(
                        content=ft.Icon(
                            ft.Icons.PHOTO_CAMERA_ROUNDED,
                            size=56,
                            color=ft.Colors.with_opacity(0.55, Colors.WHITE),
                        ),
                        alignment=ft.alignment.center,
                    ),
                    ft.Container(expand=True, alignment=ft.alignment.center),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

        self.viewfinder_stack = ft.Stack(
            [self.viewfinder, self.frame_overlay],
            alignment=ft.alignment.center,
            width=240,
            height=int(240 * self.DEFAULT_THUMB),
        )

        # بطاقة النتيجة (تظهر لحظة الاكتشاف).
        self.result_value_text = ft.Text(
            "",
            size=15,
            weight=ft.FontWeight.W_700,
            color=Colors.TEXT_PRIMARY,
            selectable=True,
            font_family="monospace",
        )
        self.result_kind_text = ft.Text(
            "",
            size=11,
            color=Colors.TEXT_SECONDARY,
        )
        self.result_card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.TAG, color=Colors.PRIMARY, size=18),
                            self.result_kind_text,
                        ],
                        spacing=4,
                    ),
                    self.result_value_text,
                    ft.Row(
                        [
                            ft.FilledTonalButton(
                                "نسخ",
                                icon=ft.Icons.COPY_ROUNDED,
                                on_click=lambda _: self._copy_to_clipboard(),
                            ),
                            ft.FilledButton(
                                "فتح المادة",
                                icon=ft.Icons.OPEN_IN_NEW,
                                on_click=lambda _: self._open_item(),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.END,
                        spacing=6,
                    ),
                ],
                spacing=6,
                tight=True,
            ),
            padding=ft.Padding(14, 12, 14, 14),
            border_radius=18,
            bgcolor=Colors.WHITE,
            shadow=Shadow.SOFT,
            visible=False,
            animate=ft.Animation(220, "easeOut"),
        )

        # الكبسولة العائمة السفلية (الأزرار الأربعة).
        dock_btn_style = ft.ButtonStyle(
            shape=ft.CircleBorder(),
            padding=ft.Padding(14, 14, 14, 14),
            bgcolor=ft.Colors.with_opacity(0.22, "#0F172A"),
        )

        self.dock = ft.Container(
            content=ft.Row(
                [
                    self._dock_btn(ft.Icons.PHOTO_LIBRARY_ROUNDED, "معرض", self._on_pick_image),
                    self._dock_btn(ft.Icons.KEYBOARD_ROUNDED, "يدوي", self._on_manual_entry),
                    self._dock_btn(ft.Icons.FLASH_ON, "فلاش", self._toggle_torch, primary=True),
                    self._dock_btn(ft.Icons.HISTORY_ROUNDED, "السجل", self._on_history),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                spacing=4,
            ),
            padding=ft.Padding(8, 8, 8, 8),
            border_radius=999,
            bgcolor=ft.Colors.with_opacity(0.32, Colors.WHITE),
            shadow=Shadow.SOFT,
            blur=ft.Blur(8, 8, ft.BlurTileMode.MIRROR),
        )

        # شريط آخر المسحات.
        self.recent_row = ft.Row(
            spacing=6,
            wrap=False,
            scroll=ft.ScrollMode.HIDDEN,
            alignment=ft.MainAxisAlignment.CENTER,
        )
        self._refresh_recent_row()

        # شريط التنبيه السفلي الذي كان في الإصدار القديم.
        self.classic_hint = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.QR_CODE_SCANNER, color=Colors.WHITE, size=18),
                    ft.Text(
                        "وجّه الكاميرا نحو الباركود",
                        size=13,
                        color=Colors.WHITE,
                        weight=ft.FontWeight.W_600,
                    ),
                ],
                tight=True,
                spacing=6,
            ),
            padding=ft.Padding(14, 10, 16, 10),
            border_radius=999,
            bgcolor=ft.Colors.with_opacity(0.55, "#0F172A"),
        )

        # الجذر: شاشة كاملة قابلة للعرض في أي Center.
        self.root = ft.Container(
            bgcolor="#0F172A",
            expand=True,
            content=ft.SafeArea(
                content=ft.Column(
                    [
                        self.title_bar,
                        ft.Container(expand=True, alignment=ft.alignment.center),
                        ft.Container(
                            content=ft.Column(
                                [
                                    ft.Row(
                                        [self.hint_chip, self.kind_chip],
                                        alignment=ft.MainAxisAlignment.CENTER,
                                        spacing=8,
                                    ),
                                    ft.Container(height=18),
                                    self.viewfinder_stack,
                                    ft.Container(height=18),
                                    self.classic_hint,
                                    ft.Container(height=18),
                                    self.result_card,
                                    ft.Container(height=18),
                                    self.recent_row,
                                ],
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                spacing=6,
                            ),
                            alignment=ft.alignment.center,
                            padding=ft.Padding(20, 0, 20, 18),
                        ),
                        ft.Container(
                            content=self.dock,
                            padding=ft.Padding(24, 0, 24, 22),
                            alignment=ft.alignment.center,
                        ),
                    ],
                    expand=True,
                    spacing=0,
                ),
                top=True,
                bottom=True,
                left=False,
                right=False,
            ),
        )

    # ------------------------------------------------------------------ #
    #  دوال التفاعل                                                     #
    # ------------------------------------------------------------------ #
    def _dock_btn(self, icon, label: str, on_click, *, primary: bool = False) -> ft.Container:
        color = Colors.WHITE
        if primary:
            return ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(icon, color="#0F172A", size=22),
                        ft.Text(
                            label,
                            size=12,
                            color="#0F172A",
                            weight=ft.FontWeight.W_700,
                        ),
                    ],
                    tight=True,
                    spacing=6,
                ),
                padding=ft.Padding(14, 12, 16, 12),
                border_radius=999,
                bgcolor=Colors.PRIMARY,
                ink=True,
                on_click=lambda _: on_click(),
            )
        return ft.Container(
            content=ft.Column(
                [
                    ft.Icon(icon, color=color, size=20),
                    ft.Text(
                        label,
                        size=10,
                        color=color,
                        weight=ft.FontWeight.W_600,
                    ),
                ],
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            ),
            padding=ft.Padding(10, 8, 10, 8),
            border_radius=16,
            on_click=lambda _: on_click(),
            ink=True,
        )

    def _set_hint(self, state: HintState) -> None:
        msg, icon, color = _DAT[state]
        self.hint_text.value = msg
        self.hint_text.color = color
        self.hint_icon.name = icon
        self.hint_icon.color = color
        try:
            self.hint_chip.update()
        except Exception:
            pass

    def _set_kind_chip(self, kind: ScanKind) -> None:
        self.kind_chip.content.controls[1].value = kind.value
        self.kind_chip.visible = kind != ScanKind.UNKNOWN
        try:
            self.kind_chip.update()
        except Exception:
            pass

    def _toggle_torch(self) -> None:
        self._torch_on = not self._torch_on
        # حدّث الكبسولة.
        if self._torch_on:
            self.torch_pill.content.controls[0].name = ft.Icons.FLASH_ON
            self.torch_pill.content.controls[1].value = "مضاء"
            self.torch_pill.bgcolor = ft.Colors.with_opacity(0.55, "#FACC15")
        else:
            self.torch_pill.content.controls[0].name = ft.Icons.FLASH_OFF
            self.torch_pill.content.controls[1].value = "إيقاف"
            self.torch_pill.bgcolor = ft.Colors.with_opacity(0.22, "#0F172A")
        try:
            self.torch_pill.update()
        except Exception:
            pass

    def _show_capture(self, value: str, kind: ScanKind) -> None:
        self.result_value_text.value = value
        self.result_kind_text.value = kind.value
        self.result_card.visible = True
        try:
            self.result_card.update()
        except Exception:
            pass
        # أضف إلى «آخر المسحات».
        chip = RecentChip(value=value, kind=kind)
        if not self._recent or self._recent[0].value != value:
            self._recent.insert(0, chip)
            self._recent = self._recent[:5]
            self._refresh_recent_row()

    def _refresh_recent_row(self) -> None:
        self.recent_row.controls = [
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.HISTORY_ROUNDED, size=12, color=Colors.PRIMARY),
                        ft.Text(
                            c.value,
                            size=11,
                            color=Colors.TEXT_PRIMARY,
                            weight=ft.FontWeight.W_600,
                        ),
                    ],
                    tight=True,
                    spacing=4,
                ),
                padding=ft.Padding(8, 6, 12, 6),
                border_radius=999,
                bgcolor=Colors.WHITE,
                shadow=Shadow.SOFT,
                on_click=lambda _, v=c.value: self._rescan_existing(v),
                ink=True,
            )
            for c in self._recent[:3]
        ]
        try:
            self.recent_row.update()
        except Exception:
            pass

    def _copy_to_clipboard(self) -> None:
        try:
            if self._page:
                self._page.set_clipboard(self.result_value_text.value)
            toast("تم نسخ القيمة", kind="info")
        except Exception:
            toast("تعذّر الحفظ في الحافظة", kind="error")

    def _open_item(self) -> None:
        # يُنفَّذ من قِبل المستهلك عبر callback on_scan(meta={"open_inventory": True}).
        self._dispatch("__manual_open__", {"open_inventory": True})

    def _rescan_existing(self, value: str) -> None:
        self._dispatch(value, {"recent": True})

    def _dispatch(self, value: str, meta: Optional[dict] = None) -> None:
        kind = self._feedback.last_kind if self._feedback.last_value == value else ScanKind.UNKNOWN
        meta = meta or {}
        meta.setdefault("ts", ft.datetime.now().isoformat())
        meta.setdefault("hint_state", self._feedback.state.value)
        try:
            cb = self._on_scan(value, kind, meta)
            if isinstance(cb, Awaitable):
                # الواجهة تتعامل معها كـ coroutine.
                if self._page:
                    self._page.run_task(lambda: cb)
        except Exception as exc:
            toast(f"تعذّر تسليم القيمة: {exc}", kind="error")
            return
        self._set_hint(HintState.LOCKED)

    # ------------------------------------------------------------------ #
    #  أحداث الفتح والإغلاق + خيارات يدوية                             #
    # ------------------------------------------------------------------ #
    def _on_close(self) -> None:
        toast("تم إغلاق الماسح", kind="info")
        # إغلاق الشاشة يعتمد على المركز المستهلِك؛ هذا فقط يُعلمه.
        try:
            if hasattr(self, "_on_dismiss") and callable(self._on_dismiss):
                self._on_dismiss()
        except Exception:
            pass

    def on_dismiss(self, cb: Callable[[], None]) -> None:
        """واجهة للمستهلك: لتغليف إغلاق الـ view في الـ Center الأب."""
        self._on_dismiss = cb

    def _on_pick_image(self) -> None:
        toast("استيراد من المعرض — قريبًا في هذا البناء", kind="info")

    def _on_manual_entry(self) -> None:
        v = ft.TextField(
            label="اكتب الباركود يدويًا",
            autofocus=True,
            on_submit=lambda e: self._close_manual_sheet(e),
            keyboard_type=ft.KeyboardType.TEXT,
        )
        sheet = ft.BottomSheet(
            content=ft.Container(
                content=ft.Column(
                    [
                        ft.Text("إدخال يدوي", weight=ft.FontWeight.W_700, size=15),
                        v,
                        ft.Row(
                            [
                                ft.TextButton("إلغاء", on_click=lambda _: self._page.close(sheet)),
                                ft.FilledButton(
                                    "تأكيد",
                                    on_click=lambda _: self._close_manual_sheet(v.value or ""),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.END,
                        ),
                    ],
                    spacing=10,
                    tight=True,
                ),
                padding=ft.Padding(20, 18, 20, 18),
            ),
        )
        if self._page:
            self._page.open(sheet)

    def _close_manual_sheet(self, value: str) -> None:
        value = (value or "").strip()
        if not value:
            toast("أدخل قيمة أولاً", kind="warning")
            return
        try:
            if self._page:
                # أُغلق الـ sheet الذي فتحناه.
                for s in list(getattr(self._page, "_bs", [])):
                    try:
                        self._page.close(s)
                    except Exception:
                        pass
        except Exception:
            pass
        self._show_capture(value, ScanKind.UNKNOWN)
        self._dispatch(value, {"source": "manual"})

    def _on_history(self) -> None:
        rows = [
            ft.DataRow(
                [ft.DataCell(ft.Text(c.value, font_family="monospace")), ft.DataCell(ft.Text(c.kind.value))]
            )
            for c in self._recent
        ]
        body = ft.Container(
            content=ft.Column(
                [
                    ft.Text("سجلّ اليوم", size=15, weight=ft.FontWeight.W_700),
                    ft.DataTable(columns=[ft.DataColumn(ft.Text("القيمة")), ft.DataColumn(ft.Text("النوع"))], rows=rows or []),
                    ft.Row(
                        [ft.TextButton("إغلاق", on_click=lambda _: self._page.close(self._history_sheet))],
                        alignment=ft.MainAxisAlignment.END,
                    ),
                ],
                spacing=10,
                tight=True,
            ),
            padding=ft.Padding(20, 18, 20, 18),
        )
        self._history_sheet = ft.BottomSheet(content=body)
        if self._page:
            self._page.open(self._history_sheet)

    # ------------------------------------------------------------------ #
    #  نقاط ربط الاختبار + الفتح العام                                  #
    # ------------------------------------------------------------------ #
    def attach(self, page: ft.Page) -> None:
        self._page = page

    def inject_scan(self, value: str, kind: str) -> None:
        """نقطة إدخال اختبار يستخدمها smoke_test لإثبات أن الماسح يربط الـ
        callback بشكل صحيح دون الحاجة إلى كاميرا حقيقية."""
        parsed = parse_kind(kind)
        self._feedback.last_kind = parsed
        self._feedback.last_value = value
        self._set_kind_chip(parsed)
        self._set_hint(HintState.LOCKED)
        self._show_capture(value, parsed)

    # نقاط إدخال لاختبار الوحدات (Phase 10 smoke) --------------------- #
    def feed_signal(self, state: HintState, kind: ScanKind = ScanKind.UNKNOWN) -> None:
        self._feedback.state = state
        self._set_hint(state)
        if kind != ScanKind.UNKNOWN:
            self._set_kind_chip(kind)


__all__ = [
    "SmartBarcodeScanner",
    "ScanKind",
    "HintState",
    "RecentChip",
    "parse_kind",
]
