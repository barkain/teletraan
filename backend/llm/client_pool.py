"""Shared pool of persistent ClaudeSDKClient instances.

Eliminates subprocess-per-call overhead by reusing long-lived clients.
Each client maintains a persistent Claude CLI subprocess that handles
multiple sequential queries via stdin/stdout JSON protocol.
"""

import os

# Skip version check subprocess before importing SDK
os.environ.setdefault("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# Pool configuration
POOL_SIZE = 5  # Max concurrent LLM sessions (main.py raises FD limit to 4096; 5 clients use ~50-75 FDs)


class ClientPool:
    """Async pool of reusable ClaudeSDKClient instances.

    Clients are created lazily on first checkout. When returned, they stay
    connected for reuse. If a client errors during use, it is discarded
    and a fresh one is created.

    Usage:
        pool = get_client_pool()
        async with pool.checkout() as client:
            await client.query("prompt")
            async for msg in client.receive_response():
                ...
    """

    def __init__(self, size: int = POOL_SIZE) -> None:
        self._size = size
        self._available: asyncio.Queue[ClaudeSDKClient | None] = asyncio.Queue(
            maxsize=size
        )
        self._initialized = False
        self._total_created = 0
        self._total_queries = 0

    async def initialize(self) -> None:
        """Fill the pool with None placeholders (lazy client creation)."""
        if self._initialized:
            return
        for _ in range(self._size):
            await self._available.put(None)  # Placeholder -- real client created on checkout
        self._initialized = True
        logger.info(f"Client pool initialized with {self._size} slots")

    async def _create_client(self) -> ClaudeSDKClient:
        """Create and connect a new ClaudeSDKClient with no system prompt."""
        options = ClaudeAgentOptions()  # No system_prompt -- callers prepend to user prompt
        client = ClaudeSDKClient(options=options)
        await client.connect()
        self._total_created += 1
        logger.debug(f"Created new pool client (total created: {self._total_created})")
        return client

    async def _destroy_client(self, client: ClaudeSDKClient) -> None:
        """Safely disconnect and destroy a client."""
        try:
            await client.disconnect()
        except Exception as e:
            logger.warning(f"Error disconnecting pool client: {e}")

    @asynccontextmanager
    async def checkout(self) -> AsyncGenerator[ClaudeSDKClient, None]:
        """Check out a client from the pool.

        Creates a new client if the slot was empty (lazy init).
        On successful use, returns client to pool.
        On error, discards client and puts a fresh slot back.
        """
        await self.initialize()

        # Block until a slot is available (this IS the concurrency control)
        client_or_none = await self._available.get()

        client: ClaudeSDKClient | None = None
        try:
            if client_or_none is None:
                client = await self._create_client()
            else:
                client = client_or_none

            self._total_queries += 1
            yield client

            # Success -- return client to pool for reuse
            await self._available.put(client)

        except Exception:
            # Error -- discard this client and put a None placeholder back
            if client is not None:
                await self._destroy_client(client)
            await self._available.put(None)  # Fresh slot for next checkout
            raise

    async def shutdown(self) -> None:
        """Drain the pool and disconnect all clients."""
        while not self._available.empty():
            try:
                client = self._available.get_nowait()
                if client is not None:
                    await self._destroy_client(client)
            except asyncio.QueueEmpty:
                break
        self._initialized = False
        logger.info(
            f"Client pool shut down (created: {self._total_created}, "
            f"queries served: {self._total_queries})"
        )

    @property
    def stats(self) -> dict:
        return {
            "pool_size": self._size,
            "available": self._available.qsize(),
            "total_created": self._total_created,
            "total_queries": self._total_queries,
        }


# Module-level singleton
_pool: ClientPool | None = None


def get_client_pool() -> ClientPool:
    """Get the shared client pool singleton."""
    global _pool
    if _pool is None:
        _pool = ClientPool(size=POOL_SIZE)
    return _pool


async def pool_query_llm(
    system_prompt: str,
    user_prompt: str,
    agent_name: str = "unknown",
) -> str:
    """Execute an LLM query using a pooled client.

    Prepends system_prompt to user_prompt since pool clients have no
    fixed system prompt. This is the standard replacement for the
    per-module _query_llm() methods.
    """
    from claude_agent_sdk import AssistantMessage, TextBlock  # type: ignore[import-untyped]

    pool = get_client_pool()

    # Combine system + user prompt (pool clients have no system_prompt)
    combined_prompt = f"""<system_instructions>
{system_prompt}
</system_instructions>

{user_prompt}"""

    response_text = ""
    async with pool.checkout() as client:
        await client.query(combined_prompt)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        response_text += block.text

    logger.info(f"[POOL] {agent_name} complete: {len(response_text)} chars")
    return response_text
