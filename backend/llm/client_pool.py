"""Shared pool of persistent ClaudeSDKClient instances.

Eliminates subprocess-per-call overhead by reusing long-lived clients.
Each client maintains a persistent Claude CLI subprocess that handles
multiple sequential queries via stdin/stdout JSON protocol.
"""

import os

# Skip version check subprocess before importing SDK
os.environ.setdefault("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")

# Clear Claude Code session markers so claude-agent-sdk doesn't refuse to
# start with "cannot be launched inside another Claude Code session".
# This is defense-in-depth: the Tauri sidecar already strips these vars,
# but if they leak through (e.g. running the backend manually from a
# Claude Code terminal), we still want the SDK to work.
os.environ.pop("CLAUDECODE", None)
os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# Pool configuration
POOL_SIZE = 5  # Max concurrent LLM sessions (main.py raises FD limit to 4096; 5 clients use ~50-75 FDs)


@dataclass
class LLMQueryResult:
    """Result of an LLM query with usage metadata."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    model: str = ""

# ---------------------------------------------------------------------------
# LLM provider environment setup
# ---------------------------------------------------------------------------
# The claude-agent-sdk reads auth from env vars.  We propagate the values
# from our Settings so that env vars are in place before any SDK client
# is created.

_llm_env_configured = False


def _build_llm_env() -> dict[str, str]:
    """Build the environment variable dict for the chosen LLM provider.

    Returns a dict suitable for ``ClaudeAgentOptions.env`` so that auth
    vars are passed **explicitly** to the spawned CLI subprocess rather
    than relying solely on ``os.environ`` inheritance (which can be lost
    across threads or if another module mutates the global env).
    """
    from config import get_settings
    settings = get_settings()
    provider = settings.get_llm_provider()

    env: dict[str, str] = {}

    if provider == "proxy":
        token = settings.ANTHROPIC_AUTH_TOKEN or settings.ANTHROPIC_API_KEY
        if token:
            env["ANTHROPIC_API_KEY"] = token
            env["ANTHROPIC_AUTH_TOKEN"] = token
        elif settings.ANTHROPIC_API_KEY is not None:
            env["ANTHROPIC_API_KEY"] = settings.ANTHROPIC_API_KEY
        if settings.ANTHROPIC_BASE_URL:
            env["ANTHROPIC_BASE_URL"] = settings.ANTHROPIC_BASE_URL
        if settings.API_TIMEOUT_MS:
            env["API_TIMEOUT_MS"] = str(settings.API_TIMEOUT_MS)

    elif provider == "anthropic_api":
        if settings.ANTHROPIC_API_KEY:
            env["ANTHROPIC_API_KEY"] = settings.ANTHROPIC_API_KEY
        if settings.ANTHROPIC_BASE_URL:
            env["ANTHROPIC_BASE_URL"] = settings.ANTHROPIC_BASE_URL
        if settings.API_TIMEOUT_MS:
            env["API_TIMEOUT_MS"] = str(settings.API_TIMEOUT_MS)

    elif provider == "bedrock":
        env["CLAUDE_CODE_USE_BEDROCK"] = "1"
        if settings.AWS_REGION:
            env["AWS_REGION"] = settings.AWS_REGION

    elif provider == "vertex":
        env["CLAUDE_CODE_USE_VERTEX"] = "1"
        if settings.VERTEX_PROJECT:
            env["CLOUD_ML_PROJECT_ID"] = settings.VERTEX_PROJECT
        if settings.VERTEX_REGION:
            env["CLOUD_ML_REGION"] = settings.VERTEX_REGION

    elif provider == "azure":
        env["CLAUDE_CODE_USE_FOUNDRY"] = "1"

    return env


def _configure_llm_env() -> None:
    """Set environment variables for the chosen LLM provider.

    Called once (lazily) before the first SDK client is created.
    Mirrors ``_build_llm_env()`` into ``os.environ`` for backwards
    compatibility with any code that reads env vars directly.
    """
    global _llm_env_configured
    if _llm_env_configured:
        return

    from config import get_settings
    settings = get_settings()
    provider = settings.get_llm_provider()

    env = _build_llm_env()
    os.environ.update(env)

    # Logging
    if provider == "proxy":
        logger.info(
            "LLM provider: %s -- endpoint: %s",
            settings.get_llm_display_name(),
            settings.ANTHROPIC_BASE_URL,
        )
    elif provider == "anthropic_api":
        logger.info(
            "LLM provider: Anthropic API (direct) -- model: %s, endpoint: %s",
            settings.ANTHROPIC_MODEL,
            settings.ANTHROPIC_BASE_URL or "https://api.anthropic.com",
        )
    elif provider == "bedrock":
        logger.info(
            "LLM provider: Amazon Bedrock -- region: %s",
            settings.AWS_REGION or "(default)",
        )
    elif provider == "vertex":
        logger.info(
            "LLM provider: Google Vertex AI -- project: %s, region: %s",
            settings.VERTEX_PROJECT or "(default)",
            settings.VERTEX_REGION or "(default)",
        )
    elif provider == "azure":
        logger.info("LLM provider: Azure AI Foundry")
    else:
        logger.warning(
            "LLM provider: Claude Code subscription auth. "
            "This relies on a local Claude Code login and is NOT recommended "
            "for distributed/production deployments (see Anthropic TOS). "
            "Set ANTHROPIC_API_KEY or a cloud provider flag for production use."
        )

    _llm_env_configured = True


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
        # Ensure LLM provider env vars are set in os.environ (backwards compat)
        _configure_llm_env()
        # Pass auth env vars explicitly via options.env so the spawned CLI
        # subprocess receives them regardless of os.environ state.
        options = ClaudeAgentOptions(env=_build_llm_env())
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
) -> LLMQueryResult:
    """Execute an LLM query using a pooled client.

    Prepends system_prompt to user_prompt since pool clients have no
    fixed system prompt. This is the standard replacement for the
    per-module _query_llm() methods.

    Returns:
        LLMQueryResult with response text and usage metadata.
    """
    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock  # type: ignore[import-untyped]

    pool = get_client_pool()

    # Combine system + user prompt (pool clients have no system_prompt)
    combined_prompt = f"""<system_instructions>
{system_prompt}
</system_instructions>

{user_prompt}"""

    response_text = ""
    input_tokens = 0
    output_tokens = 0
    cost_usd = 0.0
    sdk_duration_ms = 0.0
    model = ""

    start = time.monotonic()
    async with pool.checkout() as client:
        await client.query(combined_prompt)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        response_text += block.text
            elif isinstance(msg, ResultMessage):
                cost_usd = msg.total_cost_usd or 0.0
                sdk_duration_ms = float(msg.duration_ms or 0)
                usage = msg.usage or {}
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)

    elapsed_ms = (time.monotonic() - start) * 1000

    logger.info(
        f"[POOL] {agent_name} complete: {len(response_text)} chars, "
        f"{input_tokens}+{output_tokens} tokens, ${cost_usd:.4f}, "
        f"{elapsed_ms:.0f}ms"
    )
    return LLMQueryResult(
        text=response_text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        duration_ms=sdk_duration_ms if sdk_duration_ms > 0 else elapsed_ms,
        model=model,
    )
