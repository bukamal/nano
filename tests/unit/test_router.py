"""Unit tests for the pure-Python Router (core/router.py)."""
from __future__ import annotations

import pytest

from nano_offline.core.router import Route, RouteDenied, Router


@pytest.fixture()
def renders():
    return []


@pytest.fixture()
def full_router(renders):
    r = Router(home="dashboard", render=lambda key, kwargs: (renders.append((key, dict(kwargs))), None)[1])
    for key in ("dashboard", "items", "invoices", "finance", "security"):
        r.register(key, label=key, render=lambda **kw: None)
    r.register("sale", permission="invoices", render=lambda **kw: None)
    r.register("pos", permission="invoices", render=lambda **kw: None, on_leave=lambda k, kw: renders.append(("leave", k, kw)))
    return r


def test_register_and_get(full_router):
    assert full_router.get("sale").permission == "invoices"
    assert full_router.get("missing") is None


def test_go_renders_and_tracks_current(full_router, renders):
    assert full_router.go("items") is True
    assert full_router.current == "items"
    assert renders[-1][0] == "items"


def test_unknown_route_denied(full_router, renders):
    assert full_router.go("nope") is False
    assert full_router.current is None
    assert renders == []


def test_permission_denied_calls_on_denied(full_router):
    seen = []
    full_router.can_render = lambda route: route.permission == "admin"
    full_router.on_denied = lambda exc, key, kw: seen.append((type(exc).__name__, key))
    assert full_router.go("sale") is False
    assert seen == [("RouteDenied", "sale")]


def test_back_stack_semantics(full_router):
    full_router.go("items")           # current items, stack []
    full_router.go("sale")            # stack [items]
    full_router.go("invoices", reset=True)  # tab tap -> stack cleared
    assert full_router.path == ["invoices"]
    assert full_router.can_go_back() is False
    assert full_router.back() is False  # at root: caller exits


def test_push_and_pop(full_router):
    full_router.go("invoices")
    full_router.go("sale")
    assert full_router.path == ["invoices", "sale"]
    assert full_router.back() is True
    assert full_router.current == "invoices"
    assert full_router.path == ["invoices"]


def test_replace_current_avoids_duplicate_push(full_router):
    full_router.get("sale").replace_current = True
    full_router.go("invoices")
    full_router.go("sale")
    full_router.go("sale")
    assert full_router.path == ["invoices", "sale"]  # only one sale entry


def test_replace_flag_swaps_without_pushing(full_router):
    full_router.go("items")
    full_router.go("sale")
    assert full_router.path == ["items", "sale"]
    full_router.go("finance", replace=True)
    assert full_router.path == ["items", "finance"]


def test_kwargs_survive_back(full_router, renders):
    full_router.go("items", prefill_barcode="123")
    full_router.go("sale")
    assert full_router.back() is True
    assert renders[-1] == ("items", {"prefill_barcode": "123"})


def test_reset_to(full_router):
    full_router.go("items")
    full_router.go("sale")
    full_router.reset_to("dashboard")
    assert full_router.path == ["dashboard"]
    assert full_router.at_home()


def test_render_failure_undoes_push(renders):
    def shell_render(key, kwargs):
        renders.append((key, kwargs))
        if key == "finance":
            raise RuntimeError("view crashed")

    r = Router(home="dashboard", render=shell_render)
    for key in ("dashboard", "items", "finance"):
        r.register(key, render=lambda **kw: None)
    r.go("items")
    assert r.go("finance") is False
    # The failed push was undone: the stack still describes what is on
    # screen, and the current entry was never committed.
    assert r.path == ["items"]
    assert r.current == "items"


def test_on_leave_fires_only_when_leaving(full_router, renders):
    full_router.go("pos")
    assert ("leave", "pos", {}) not in renders
    full_router.go("sale")
    assert ("leave", "pos", {}) in renders[-3:]
    # re-entering pos then tabbing out also fires once
    renders.clear()
    full_router.go("pos")
    full_router.go("dashboard", reset=True)
    assert sum(1 for r in renders if r[0] == "leave") == 1


def test_on_leave_error_does_not_block_navigation(full_router):
    def bad_leave(key, kwargs):
        raise RuntimeError("cleanup broke")

    full_router.get("pos").on_leave = bad_leave
    full_router.go("pos")
    assert full_router.go("dashboard") is True
    assert full_router.current == "dashboard"


def test_back_after_permission_lost_goes_home(full_router, renders):
    full_router.go("invoices")
    full_router.go("sale")
    full_router.can_render = lambda route: route.key not in ("invoices",)
    assert full_router.back() is True
    assert full_router.current == "dashboard"
    assert full_router.path == ["dashboard"]


def test_route_dataclass_defaults():
    route = Route(key="x")
    assert route.permission is None
    assert route.render is None
    assert route.replace_current is False


def test_denied_callback_receives_exception():
    seen = []

    def on_denied(exc, key, kwargs):
        seen.append((exc, key, kwargs))

    r = Router(home="dashboard", render=lambda k, kw: None, on_denied=on_denied)
    r.go("ghost", a=1)
    assert isinstance(seen[0][0], RouteDenied)
    assert seen[0][1] == "ghost"
    assert seen[0][2] == {"a": 1}


def test_no_render_callback_denies_everything():
    seen = []
    r = Router(home="dashboard", on_denied=lambda exc, key, kw: seen.append(key))
    r.register("items", render=lambda **kw: None)
    assert r.go("items") is False
    assert seen == ["items"]
