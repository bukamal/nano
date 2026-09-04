"""Centralized design tokens for the Nano UI — light *and* dark aware.

Every color used across the app's views should come from here instead of
being repeated as a raw hex literal. This keeps the visual language
consistent and means a rebrand/theme change is a one-file edit instead of a
grep-and-replace across every view.

Usage (unchanged from before dark mode existed — this is the whole point):
    from nano_offline.core.theme import Colors

    ft.Text("...", color=Colors.TEXT_PRIMARY)

Dark mode wiring
-----------------
``Colors`` and ``Shadow`` are no longer plain classes with fixed class
attributes. ``Colors.PRIMARY`` (etc.) is resolved *at access time* against
whichever mode is currently active (see ``set_mode``/``get_mode`` below),
via a metaclass ``__getattr__`` (only invoked once *normal* attribute
lookup fails — which is why the classes below have empty bodies instead of
the literal hex values). This means every one of the hundreds of existing
``Colors.X`` / ``Shadow.X`` call sites across the app needed **zero
changes** to become dark-mode-aware — they already read the attribute
fresh every time a view is (re)built, they just now get the dark hex when
dark mode is active instead of always getting the light one.

The one thing this trick does *not* do for free is repaint controls that
were already built and added to the page before the mode changed — a
``ft.Text(color=Colors.TEXT_PRIMARY)`` bakes in a concrete color string the
moment it's constructed, same as any other Python attribute access. Nano's
views are cheap to rebuild from scratch (every ``*_view.py`` builds fresh
controls on every ``show_center()`` call, nothing is cached/reused), so a
mode switch is applied by re-running whichever full-screen rebuild the app
already uses elsewhere for the same "everything must repaint" need after a
backup restore (``main.py``'s ``open_shell()`` / ``reset_page()`` pair) —
see ``main.py``'s ``apply_theme_settings(rebuild=True)`` for the call site
that ties this together with ``core.theme_settings``.
"""

from __future__ import annotations

import flet as ft

# --- Mode state ----------------------------------------------------------#
# The *resolved* physical mode actually in effect right now — always
# "light" or "dark", never "system"/"auto". Resolving "follow the system"
# or "dark between 7pm and 6am" into one of these two is
# ``core.theme_settings.resolve_effective_mode``'s job; this module only
# ever deals in the end result, so it stays a trivial on/off switch.
_state: dict[str, str] = {"mode": "light"}


def get_mode() -> str:
    """The currently active resolved mode: ``"light"`` or ``"dark"``."""
    return _state["mode"]


def is_dark() -> bool:
    return _state["mode"] == "dark"


def set_mode(mode: str) -> None:
    """Set the active mode. Anything other than the literal ``"dark"`` is light.

    Deliberately permissive instead of raising on an unexpected value —
    this is called from startup/settings-resolution code where a stray
    typo'd or legacy-stored value should degrade to the safe default
    (light) rather than crash the whole app.
    """
    _state["mode"] = "dark" if mode == "dark" else "light"


class _LightTokens:
    """Reference copy of every light-mode value. Never used directly at
    runtime for attribute access (see ``Colors`` below) — exists purely so
    the actual values are readable/greppable/diffable in one place, and so
    ``_LIGHT`` can be built from it instead of duplicated by hand.
    """

    # Brand / primary — deep teal instead of the generic Material blue that
    # nearly every SaaS/accounting app defaults to. Reads as "financial" and
    # trustworthy without colliding with the success-green or purple accents
    # already used elsewhere in the palette.
    PRIMARY = "#0F766E"
    PRIMARY_DARK = "#115E59"
    PRIMARY_BG = "#F0FDFA"
    PRIMARY_BORDER = "#99F6E4"

    # Neutral surfaces
    WHITE = "#FFFFFF"
    BACKGROUND = "#F8FAFC"
    BACKGROUND_ALT = "#F1F5F9"

    # Borders
    BORDER = "#E2E8F0"
    BORDER_ALT = "#E5E7EB"
    BORDER_STRONG = "#CBD5E1"

    # Text
    TEXT_PRIMARY = "#0F172A"
    TEXT_SECONDARY = "#64748B"
    TEXT_MUTED = "#475569"
    TEXT_MUTED_DARK = "#334155"
    TEXT_FAINT = "#94A3B8"

    # Success / green
    SUCCESS = "#16A34A"
    SUCCESS_DARK = "#15803D"
    SUCCESS_ALT = "#059669"
    SUCCESS_DARKER = "#166534"
    SUCCESS_BG = "#ECFDF5"

    # Danger / red
    DANGER = "#EF4444"
    DANGER_DARK = "#DC2626"
    DANGER_DARKER = "#B91C1C"
    DANGER_BG = "#FEF2F2"
    DANGER_BORDER = "#FECACA"

    # Warning / amber
    WARNING = "#F59E0B"
    WARNING_DARK = "#D97706"
    WARNING_DARKER = "#B45309"
    WARNING_BG = "#FFFBEB"
    WARNING_BG_ALT = "#FFF7ED"

    # Orange (distinct accent, e.g. purchases/alerts)
    ORANGE = "#EA580C"
    ORANGE_DARK = "#9A3412"

    # Purple (distinct accent, e.g. services/reports)
    PURPLE = "#7C3AED"
    PURPLE_LIGHT = "#8B5CF6"
    PURPLE_BG = "#F5F3FF"


_LIGHT: dict[str, str] = {k: v for k, v in vars(_LightTokens).items() if k.isupper()}

# Dark-mode counterpart of the table above — same token names, tuned so
# text/icon-on-surface contrast stays readable rather than a naive hue
# inversion: surfaces get *darker*, text/accents get *lighter and slightly
# desaturated* so nothing glows or vibrates on an OLED screen at night, and
# semantic colors (success/danger/warning) keep their identity while
# backing off enough to stay legible on a dark surface.
_DARK: dict[str, str] = {
    "PRIMARY": "#2DD4BF",
    "PRIMARY_DARK": "#5EEAD4",
    "PRIMARY_BG": "#0F2E2B",
    "PRIMARY_BORDER": "#134E4A",
    "WHITE": "#1E293B",  # "card surface" — kept token role, not literal color
    "BACKGROUND": "#0F172A",
    "BACKGROUND_ALT": "#1E293B",
    "BORDER": "#334155",
    "BORDER_ALT": "#334155",
    "BORDER_STRONG": "#475569",
    "TEXT_PRIMARY": "#F1F5F9",
    "TEXT_SECONDARY": "#94A3B8",
    "TEXT_MUTED": "#CBD5E1",
    "TEXT_MUTED_DARK": "#E2E8F0",
    "TEXT_FAINT": "#64748B",
    "SUCCESS": "#4ADE80",
    "SUCCESS_DARK": "#22C55E",
    "SUCCESS_ALT": "#34D399",
    "SUCCESS_DARKER": "#86EFAC",
    "SUCCESS_BG": "#0F2E1A",
    "DANGER": "#F87171",
    "DANGER_DARK": "#EF4444",
    "DANGER_DARKER": "#FCA5A5",
    "DANGER_BG": "#3A1214",
    "DANGER_BORDER": "#7F1D1D",
    "WARNING": "#FBBF24",
    "WARNING_DARK": "#F59E0B",
    "WARNING_DARKER": "#FDE68A",
    "WARNING_BG": "#3A2A0A",
    "WARNING_BG_ALT": "#3A230A",
    "ORANGE": "#FB923C",
    "ORANGE_DARK": "#FDBA74",
    "PURPLE": "#A78BFA",
    "PURPLE_LIGHT": "#C4B5FD",
    "PURPLE_BG": "#241A3A",
}

assert set(_DARK) == set(_LIGHT), "dark/light token tables drifted out of sync"


class _ColorsMeta(type):
    def __getattr__(cls, name: str):
        table = _DARK if _state["mode"] == "dark" else _LIGHT
        try:
            return table[name]
        except KeyError:
            raise AttributeError(name) from None


class Colors(metaclass=_ColorsMeta):
    """Mode-aware color tokens — see the module docstring. Deliberately has
    no class body: every ``Colors.X`` access falls through to
    ``_ColorsMeta.__getattr__`` above, which is what makes it live-switch
    between light and dark.
    """


class Spacing:
    """Common spacing scale (px) used for padding/margins/gaps."""

    XS = 4
    SM = 8
    MD = 12
    LG = 16
    XL = 20
    XXL = 24


class Radius:
    """Common corner-radius scale (px)."""

    SM = 10
    MD = 14
    LG = 16
    XL = 20


class IconSize:
    """Icon-only button sizes (px), keyed by the *role* the icon plays —
    not by screen. Before this existed, near-identical actions were sized
    ad hoc per call site (a "close this sheet" X was 19px in one view and
    20px in another; a quantity +/- stepper was 16px in the invoice editor
    but 18px in the POS cart) purely because whoever wrote that call site
    picked a number that looked fine in isolation. Pick the token that
    matches the *role*, not whatever pixel value looks closest to what was
    there before, so the same kind of action reads identically everywhere
    it appears.
    """

    INLINE = 18  # row-level actions: edit, quantity steppers, small remove
    HEADER = 20  # dialog/sheet/panel header actions: close, settings, mark-all
    HERO = 34    # a single prominent, page-level add/create action


# Elevation scale (soft, low-opacity shadows) for surface depth, resolved
# against the active mode the same way ``Colors`` is (see module docstring)
# — a dark-mode shadow needs a darker/less visible tint than the light-mode
# one or it reads as a pale halo instead of depth, so this can't just reuse
# a fixed color the way the original single-mode version did.
#
# Usage (unchanged):
#     ft.Container(..., shadow=Shadow.SM)   # list rows, chips
#     ft.Container(..., shadow=Shadow.MD)   # standard content cards
#     ft.Container(..., shadow=Shadow.LG)   # dialogs, KPI/metric cards
_SHADOW_RECIPES: dict[str, tuple[int, int, tuple[int, int], str]] = {
    "SM": (10, 0, (0, 2), "BORDER"),
    "MD": (18, 0, (0, 5), "BORDER"),
    "LG": (26, 0, (0, 9), "BORDER_STRONG"),
}


class _ShadowMeta(type):
    def __getattr__(cls, name: str):
        try:
            blur, spread, (dx, dy), border_token = _SHADOW_RECIPES[name]
        except KeyError:
            raise AttributeError(name) from None
        return ft.BoxShadow(
            blur_radius=blur,
            spread_radius=spread,
            color=getattr(Colors, border_token),
            offset=ft.Offset(dx, dy),
        )


class Shadow(metaclass=_ShadowMeta):
    """Mode-aware elevation tokens — see ``Colors`` docstring for the pattern."""


class _SeverityStyles:
    """Lazily-resolved replacement for what used to be a plain dict.

    Shared with NotificationCenter's panel (views/notifications_view.py) and
    DashboardCenter's alerts card (views/dashboard_view.py) so a "warning"
    alert reads the same regardless of which screen renders it. Keyed by
    NotificationService.Alert.severity ("info" | "warning" | "urgent").

    A plain ``dict`` built at import time would freeze in whatever mode was
    active the moment this module first loaded (always light, since that's
    the startup default) and never notice a later switch to dark. This
    keeps the exact same ``.get(key, default)`` / ``[key]`` call-site API
    every existing view already uses, but resolves the actual Colors.* hex
    values fresh on every access.
    """

    _RECIPES = {
        "urgent": ("DANGER", "DANGER_BG", ft.Icons.PRIORITY_HIGH_ROUNDED),
        "warning": ("WARNING_DARK", "WARNING_BG", ft.Icons.WARNING_AMBER_ROUNDED),
        "info": ("PRIMARY", "PRIMARY_BG", ft.Icons.INFO_OUTLINE_ROUNDED),
    }

    def __getitem__(self, key: str):
        color_token, bg_token, icon = self._RECIPES[key]
        return (getattr(Colors, color_token), getattr(Colors, bg_token), icon)

    def get(self, key: str, default=None):
        try:
            return self[key]
        except KeyError:
            return default


class _StatusStyles:
    """Lazily-resolved replacement for what used to be a plain dict.

    Shared (icon, text_color, bg_color, border_color) triples for the small
    inline status pill used by the auth flow (activation + login).
    Centralized here so both screens recolor identically instead of each
    keeping its own copy that can drift out of sync. See ``_SeverityStyles``
    above for why this can't be a plain dict anymore.
    """

    _RECIPES = {
        "info": (ft.Icons.INFO_OUTLINE_ROUNDED, "TEXT_SECONDARY", "BACKGROUND_ALT", "BORDER"),
        "success": (ft.Icons.CHECK_CIRCLE_ROUNDED, "SUCCESS_DARKER", "SUCCESS_BG", "SUCCESS"),
        "error": (ft.Icons.ERROR_ROUNDED, "DANGER_DARKER", "DANGER_BG", "DANGER_BORDER"),
    }

    def __getitem__(self, key: str):
        icon, color_token, bg_token, border_token = self._RECIPES[key]
        return (icon, getattr(Colors, color_token), getattr(Colors, bg_token), getattr(Colors, border_token))

    def get(self, key: str, default=None):
        try:
            return self[key]
        except KeyError:
            return default


SEVERITY_STYLE = _SeverityStyles()
STATUS_STYLES = _StatusStyles()


class LazyPalette:
    """A ``list``-like sequence of ``Colors`` tokens resolved on access.

    For the handful of views that cycle through a fixed set of accent
    colors by index (e.g. ``PALETTE[category_id % len(PALETTE)]`` for
    category/tag chips) — a plain ``[Colors.PRIMARY, Colors.ORANGE, ...]``
    list would bake in the light-mode hex values the moment the module
    first imports and never see a later mode switch, same issue as
    ``SEVERITY_STYLE``/``STATUS_STYLES`` above. Supports ``len()``,
    ``[index]``, and iteration, so existing call sites need no changes
    beyond building the palette with this instead of a plain list.

    Usage:
        CATEGORY_PALETTE = LazyPalette("PRIMARY", "PURPLE_LIGHT", "ORANGE")
        ...
        accent = CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)]
    """

    def __init__(self, *tokens: str):
        self._tokens = tokens

    def __len__(self) -> int:
        return len(self._tokens)

    def __getitem__(self, index: int) -> str:
        return getattr(Colors, self._tokens[index])

    def __iter__(self):
        return (getattr(Colors, t) for t in self._tokens)


__all__ = [
    "Colors", "Spacing", "Radius", "IconSize", "Shadow", "SEVERITY_STYLE", "STATUS_STYLES", "LazyPalette",
    "get_mode", "set_mode", "is_dark",
]
