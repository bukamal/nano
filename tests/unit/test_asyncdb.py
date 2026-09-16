"""Unit tests for the @blocking / .aio off-loading mechanism."""
from __future__ import annotations

import asyncio

import pytest

from nano_offline.core.asyncdb import AsyncBridge, Offloadable, async_bridge, blocking, is_blocking


class _Repo(Offloadable):
    def __init__(self):
        self.calls = []

    @blocking
    def fetch(self, x):
        self.calls.append(x)
        return x * 2

    @blocking
    def save(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return "ok"

    def not_tagged(self):
        return 42


def test_is_blocking_flags_only_tagged():
    assert is_blocking(_Repo.fetch)
    assert is_blocking(_Repo.not_tagged) is False


def test_sync_method_still_works():
    r = _Repo()
    assert r.fetch(3) == 6  # tagging leaves the sync call untouched
    assert r.not_tagged() == 42


def test_aio_bridge_lists_only_tagged_names():
    r = _Repo()
    names = sorted(r.aio._allowed)
    assert names == ["fetch", "save"]
    assert "not_tagged" not in names


def test_aio_untagged_raises_attribute_error():
    r = _Repo()
    with pytest.raises(AttributeError, match="not tagged @blocking"):
        r.aio.not_tagged


def test_aio_returns_coroutine_and_offloads():
    async def scenario():
        r = _Repo()
        result = await r.aio.fetch(10)
        return r, result

    r, result = asyncio.run(scenario())
    assert result == 20
    assert r.calls == [10]


def test_aio_runs_on_a_different_thread():
    """The whole point: the blocking call must NOT run on the event loop thread."""
    import threading

    seen = {}

    class _ThreadSpy(Offloadable):
        @blocking
        def work(self):
            seen["thread"] = threading.get_ident()
            return "done"

    async def scenario():
        loop_thread = threading.get_ident()
        obj = _ThreadSpy()
        out = await obj.aio.work()
        return loop_thread, out

    loop_thread, out = asyncio.run(scenario())
    assert out == "done"
    assert seen["thread"] != loop_thread  # ran off the loop thread


def test_aio_forwards_args_and_kwargs():
    r = _Repo()
    out = asyncio.run(r.aio.save(1, 2, key="v"))
    assert out == "ok"
    assert r.calls == [((1, 2), {"key": "v"})]


def test_bridge_is_cached_and_stable():
    r = _Repo()
    assert r.aio is r.aio
    assert isinstance(r.aio, AsyncBridge)


def test_explicit_async_bridge_function():
    r = _Repo()
    assert async_bridge(r) is r.aio


def test_repr_mentions_tagged_methods():
    r = _Repo()
    assert "fetch" in repr(r.aio) and "AsyncBridge" in repr(r.aio)
