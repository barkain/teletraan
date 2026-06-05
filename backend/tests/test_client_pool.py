"""Tests for the ClaudeSDKClient pool concurrency control.

Focus: the pool must return its slot exactly once on every checkout exit
path -- normal completion, Exception, and (critically) asyncio.CancelledError,
which is a BaseException in py3.13 and previously leaked a slot permanently.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from llm.client_pool import POOL_SIZE, ClientPool


class _FakeClient:
    """Minimal stand-in for ClaudeSDKClient (connect/disconnect only)."""

    def __init__(self) -> None:
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False


@pytest.fixture()
def patched_client_factory():
    """Patch the SDK client so checkout never spawns a real subprocess."""
    with patch(
        "llm.client_pool.ClaudeSDKClient",
        side_effect=lambda *a, **k: _FakeClient(),
    ), patch("llm.client_pool._configure_llm_env"), patch(
        "llm.client_pool._build_llm_env", return_value={}
    ):
        yield


async def test_checkout_returns_slot_on_normal_exit(patched_client_factory):
    """A clean checkout returns the slot, leaving the pool full."""
    pool = ClientPool(size=2)
    await pool.initialize()

    async with pool.checkout() as client:
        assert client is not None
        # One slot is held during the body.
        assert pool.stats["available"] == 1

    # Slot returned exactly once -- pool back to full.
    assert pool.stats["available"] == 2


async def test_checkout_returns_slot_on_exception(patched_client_factory):
    """An exception inside the body still returns the slot (no leak)."""
    pool = ClientPool(size=2)
    await pool.initialize()

    with pytest.raises(RuntimeError):
        async with pool.checkout():
            assert pool.stats["available"] == 1
            raise RuntimeError("boom")

    assert pool.stats["available"] == 2


async def test_checkout_returns_slot_on_cancellation(patched_client_factory):
    """Regression: cancelling the holding task mid-checkout must NOT leak a slot.

    Pre-fix, asyncio.CancelledError (a BaseException in py3.13) bypassed the
    ``except Exception`` reclaim path, leaking the slot permanently. The
    try/finally now guarantees the slot is returned exactly once.
    """
    size = 2
    pool = ClientPool(size=size)
    await pool.initialize()

    entered = asyncio.Event()

    async def _hold() -> None:
        async with pool.checkout():
            # Signal we hold a slot, then block forever until cancelled.
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(_hold())

    # Wait until the task is inside the checkout holding a slot.
    await asyncio.wait_for(entered.wait(), timeout=5)
    assert pool.stats["available"] == size - 1

    # Cancel the holding task mid-checkout (the leak repro).
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # The slot must be reclaimed: pool back to full, not stuck at size-1.
    assert pool.stats["available"] == size


async def test_concurrency_never_exceeds_pool_size(patched_client_factory):
    """Even with cancellations, concurrent holders never exceed POOL_SIZE.

    Repeatedly checking out and cancelling must not orphan slots; the pool's
    available count must always recover to full so the cap is respected.
    """
    size = 3
    pool = ClientPool(size=size)
    await pool.initialize()

    for _ in range(10):
        entered = asyncio.Event()

        async def _hold() -> None:
            async with pool.checkout():
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(_hold())
        await asyncio.wait_for(entered.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    # After 10 cancelled checkouts the pool must be fully replenished,
    # proving no slot was leaked (which would shrink effective capacity).
    assert pool.stats["available"] == size


def test_pool_size_and_timeout_constants():
    """Capacity constants from the PR #37 work are preserved."""
    from llm.client_pool import CHECKOUT_TIMEOUT

    assert POOL_SIZE == 12
    assert CHECKOUT_TIMEOUT == 180


def test_reset_client_pool_removed():
    """The reset_client_pool() hack must be gone now that the leak is fixed."""
    import llm.client_pool as cp

    assert not hasattr(cp, "reset_client_pool")
