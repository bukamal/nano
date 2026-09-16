"""Unified off-loading of blocking DB work off the Flet event loop.

Flet runs the whole UI (every ``on_click`` handler, every ``show_center``)
on one asyncio event loop. ``sqlite3`` calls are synchronous, so a
repository query run straight from a handler *blocks the loop*: the app
visibly freezes (no toast, no animation, no input) until the query
finishes. On a phone with thousands of items that freeze is the #1 source
of "the app hung" reports.

Fixing it call-site by call-site would take weeks (and did, piecemeal --
only ~11 ``asyncio.to_thread`` spots exist across the whole app). This
module provides the uniform mechanism instead:

1. Repository methods that are safe to run on a worker thread are marked
   with :func:`blocking`. "Safe" means: the method opens and closes its own
   SQLite connection (``with self.db.connect()`` / ``self.db.transaction()``)
   and touches no Flet objects. Every repository method in this codebase
   already follows that rule -- ``Database.connect()`` builds a fresh
   connection per call, and the audit triggers read the actor through the
   shared ``Database`` object, which is plain attribute reads: thread-safe.

2. Each repository exposes a ``.aio`` bridge (see :func:`async_bridge`)
   whose only members are the tagged methods, each wrapped as a coroutine
   that runs it via :func:`asyncio.to_thread`. Async UI code awaits the
   bridge instead of calling the sync method::

       rows = await ctx.items.aio.list(search=q, limit=50)

   Un-tagged methods are deliberately *absent* from the bridge (raising
   ``AttributeError``), so a future refactor can't silently off-load
   something that must stay on the loop (e.g. a method that would grow to
   touch ``page``/controls -- the tags make that boundary explicit).

3. The decorator leaves the *sync* method untouched, so every existing
   call site keeps working during the migration; views switch to
   ``.aio`` incrementally.

Naming note: it is ``blocking`` (what the function *does*), not
``thread_safe`` (what you promise about it) -- the tag documents the cost
and reviewers can grep it: ``rg "@blocking" src`` lists every off-loadable
DB entry point.
"""

from __future__ import annotations

import asyncio
import functools
from typing import Any, Callable, TypeVar

__all__ = ["blocking", "is_blocking", "async_bridge", "AsyncBridge", "Offloadable"]

F = TypeVar("F", bound=Callable[..., Any])

_TAG = "_nano_blocking"


def blocking(func: F) -> F:
    """Mark a sync method as safe to off-load with ``asyncio.to_thread``.

    The method is returned *unchanged* (still fully synchronous); the tag
    only opts it into the ``.aio`` bridge. Do NOT tag anything that touches
    Flet controls or the page, and do NOT tag generators / context
    managers (``db.transaction()``) -- crossing thread boundaries with an
    unfinished sqlite transaction is exactly the bug this module should
    prevent.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        return func(*args, **kwargs)

    setattr(wrapper, _TAG, True)
    functools.update_wrapper(wrapper, func)
    wrapper.__annotations__.update(getattr(func, "__annotations__", {}))
    return wrapper  # type: ignore[return-value]


def is_blocking(obj: Any) -> bool:
    return bool(getattr(obj, _TAG, False))


class AsyncBridge:
    """Coroutine facade over the ``@blocking`` methods of one target object.

    Built lazily and cached on the target (``target._nano_aio``), so
    ``ctx.items.aio is ctx.items.aio`` and each wrapped coroutine is created
    once per method.
    """

    __slots__ = ("_target", "_allowed")

    def __init__(self, target: Any, names: tuple[str, ...]):
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_allowed", set(names))

    def __getattr__(self, name: str):
        target = object.__getattribute__(self, "_target")
        allowed = object.__getattribute__(self, "_allowed")
        if name not in allowed:
            raise AttributeError(
                f"{type(target).__name__}.{name} is not tagged @blocking; "
                "off-loading it would be unsafe (touches the event loop or "
                "must stay synchronous). Tag it deliberately or keep calling "
                "the sync method."
            )
        fn = getattr(target, name)

        async def run(*args: Any, **kwargs: Any):
            return await asyncio.to_thread(fn, *args, **kwargs)

        run.__name__ = name
        run.__qualname__ = f"{type(target).__name__}.{name}.aio"
        run.__doc__ = (fn.__doc__ or "").split("\n", 1)[0] + " (off-loaded via asyncio.to_thread)"
        return run

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        target = object.__getattribute__(self, "_target")
        allowed = sorted(object.__getattribute__(self, "_allowed"))
        return f"<AsyncBridge {type(target).__name__} {allowed}>"


def async_bridge(target: Any) -> AsyncBridge:
    """Return (creating on first use) the ``.aio`` bridge for ``target``."""
    existing = getattr(target, "_nano_aio", None)
    if existing is not None:
        return existing
    names = []
    for cls in type(target).__mro__:
        for key, value in vars(cls).items():
            if key.startswith("_") or key in names:
                continue
            if callable(value) and is_blocking(value):
                names.append(key)
    bridge = AsyncBridge(target, tuple(names))
    object.__setattr__(target, "_nano_aio", bridge)
    return bridge


class Offloadable:
    """Mixin giving a class an ``aio`` property -> :func:`async_bridge`.

    Repositories mix this in and decorate their public methods with
    ``@blocking``; UI code then awaits ``repo.aio.method(...)`` to run that
    call on a worker thread instead of the Flet event loop.
    """

    @property
    def aio(self) -> AsyncBridge:
        return async_bridge(self)
