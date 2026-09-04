"""A modern, app-aware toast notification -- replacement for ``ft.SnackBar``.

Flet's built-in ``SnackBar`` is rendered at the true bottom edge of the
viewport, with no awareness of the app's own bottom tab bar (``mobile_bar``
in ``main.py``, a plain 78px ``Container`` that lives in the page's normal
control tree, not in a slot Flet's Scaffold knows about). The result was a
default gray bar covering the tabs on every phone screen.

:func:`toast` fixes that by floating its own pill in ``page.overlay`` and
placing it *above* whichever bottom chrome is currently visible -- above the
mobile tab bar on phones, or just off the page edge on desktop where that
bar is hidden (see ``adapt_navigation`` in ``main.py``). A single reusable
overlay slot lives on the page object itself, so calling this twice in
quick succession slides the old toast out instead of stacking duplicates.

Usage (drop-in replacement for every existing ``notify``/``_notify`` helper):

    from nano_offline.core.toast import toast
    toast(self.page, "تم الحفظ")                      # kind auto-detected
    toast(self.page, "تعذّر الاتصال", kind="error")     # explicit override
"""

from __future__ import annotations

import asyncio
from typing import Literal

import flet as ft

from nano_offline.core import sound
from nano_offline.core.theme import Colors, Shadow

ToastKind = Literal["success", "error", "warning", "info"]

# (icon, accent color, tint background for the icon chip)
_STYLE: dict[ToastKind, tuple[str, str, str]] = {
    "success": (ft.Icons.CHECK_CIRCLE_ROUNDED, Colors.SUCCESS, Colors.SUCCESS_BG),
    "error": (ft.Icons.ERROR_ROUNDED, Colors.DANGER, Colors.DANGER_BG),
    "warning": (ft.Icons.WARNING_ROUNDED, Colors.WARNING, Colors.WARNING_BG),
    "info": (ft.Icons.INFO_ROUNDED, Colors.PRIMARY, Colors.PRIMARY_BG),
}

_HIDDEN_BOTTOM = -120.0
_MOBILE_BAR_HEIGHT = 78
_EDGE_MARGIN = 18
_ANIM = ft.Animation(260, ft.AnimationCurve.EASE_OUT)

# Calibrated against the app's actual message strings (see every existing
# notify()/_notify() call site) rather than a generic guess -- success
# messages in this codebase consistently start with "تم"/"تمت"/"✔", hard
# failures name themselves ("خطأ", "تعذر", "فشل", "غير موجود"...), and
# blocking validation prompts read as "يجب"/"اختر"/"لا تملك"/etc.
_SUCCESS_MARKERS = ("تم ", "تمت ", "✔", "بنجاح")
_ERROR_MARKERS = ("خطأ", "تعذر", "فشل", "غير مهيأ", "غير موجود", "غير مطابق", "لا توجد", "لا يمكن")
_WARNING_MARKERS = ("يجب", "اختر", "لا تملك", "أولاً", "أولًا", "الرجاء", "فارغ")


def _infer_kind(text: str) -> ToastKind:
    t = text.strip()
    if t.startswith(_SUCCESS_MARKERS) or any(m in t for m in _SUCCESS_MARKERS):
        return "success"
    if any(m in t for m in _ERROR_MARKERS):
        return "error"
    if any(m in t for m in _WARNING_MARKERS):
        return "warning"
    return "info"


def _visible_bottom(page: ft.Page) -> float:
    """Sit above the mobile tab bar on phones; hug the page edge on desktop
    (the tab bar is hidden there in favor of the sidebar -- see
    ``adapt_navigation`` in ``main.py``)."""
    is_desktop = bool(page.width and page.width >= 900)
    return _EDGE_MARGIN if is_desktop else _MOBILE_BAR_HEIGHT + _EDGE_MARGIN


def toast(page: ft.Page, text: str, kind: ToastKind | None = None, duration: int = 2600, sound_kind: str | None = None) -> None:
    """Show a floating toast that never covers the app's own navigation.

    ``kind`` controls the accent color/icon (success/error/warning/info);
    when omitted it's inferred from the message text. ``sound_kind`` lets a
    call site play a more specific tone (e.g. "scan", "save" -- see
    core/sound.py) than the four visual kinds cover, without needing a
    matching new pill color/icon for it; the toast still *looks* like
    whichever of the four visual kinds fits (usually "success"). Slides up
    with a fade-in, then slides back down and removes itself after
    ``duration``ms.
    """
    resolved_kind: ToastKind = kind or _infer_kind(text)
    icon_name, accent, tint = _STYLE[resolved_kind]

    # Every toast in the app already carries a resolved success/error/
    # warning/info kind -- piggyback the sound-cue system on it here so
    # every existing call site gets a matching tone for free. See
    # core/sound.py's module docstring for why this single choke point
    # was chosen over touching every notify() call site individually.
    sound.play(page, sound_kind or resolved_kind)

    pill = ft.Container(
        content=ft.Row(
            [
                ft.Container(
                    ft.Icon(icon_name, color=accent, size=18),
                    width=30,
                    height=30,
                    border_radius=15,
                    bgcolor=tint,
                    alignment=ft.alignment.center,
                ),
                ft.Text(text, size=12.5, weight=ft.FontWeight.W_600, color=Colors.TEXT_PRIMARY, max_lines=3),
            ],
            spacing=10,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=Colors.WHITE,
        border=ft.border.all(1, Colors.BORDER),
        border_radius=999,
        padding=ft.padding.only(left=14, right=16, top=8, bottom=8),
        shadow=Shadow.LG,
    )

    wrapper = ft.Container(
        content=ft.Row([pill], alignment=ft.MainAxisAlignment.CENTER),
        left=0,
        right=0,
        bottom=_HIDDEN_BOTTOM,
        opacity=0,
        animate_position=_ANIM,
        animate_opacity=_ANIM,
    )

    # Reuse one overlay slot per page: a fresh call while a toast is still
    # showing removes the previous one immediately instead of letting two
    # pills stack on top of each other.
    previous = getattr(page, "_nano_toast", None)
    if previous is not None and previous in page.overlay:
        page.overlay.remove(previous)
    page._nano_toast = wrapper
    page.overlay.append(wrapper)
    page.update()

    wrapper.bottom = _visible_bottom(page)
    wrapper.opacity = 1
    page.update()

    async def _auto_dismiss() -> None:
        await asyncio.sleep(duration / 1000)
        if getattr(page, "_nano_toast", None) is not wrapper:
            return  # a newer toast already replaced this one
        wrapper.bottom = _HIDDEN_BOTTOM
        wrapper.opacity = 0
        page.update()
        await asyncio.sleep(_ANIM.duration / 1000)
        if wrapper in page.overlay:
            page.overlay.remove(wrapper)
            page.update()
        if getattr(page, "_nano_toast", None) is wrapper:
            page._nano_toast = None

    page.run_task(_auto_dismiss)


__all__ = ["toast", "ToastKind"]
