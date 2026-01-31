"""LLM agent for market analysis using Claude Agent SDK with tool calling.

This module provides a conversational AI agent that can answer questions about
stocks, sectors, and market conditions using real-time data and technical analysis.

Uses claude-agent-sdk which leverages the user's existing Claude Code subscription
(no separate API key needed).
"""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    AssistantMessage,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    tool,
    create_sdk_mcp_server,
)

logger = logging.getLogger(__name__)


# Define tools using @tool decorator for SDK MCP server
@tool(
    "get_stock_data",
    "Get current price and company information for a stock symbol. "
    "Returns price, change, volume, and basic company info like sector and market cap.",
    {"symbol": str}
)
async def get_stock_data_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Get stock data tool handler."""
    from llm.tools.handlers import get_stock_data_handler
    result = await get_stock_data_handler(args["symbol"])
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    "get_price_history",
    "Get historical price data (OHLCV) for a stock. "
    "Useful for analyzing trends and calculating indicators.",
    {"symbol": str, "period": str}
)
async def get_price_history_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Get price history tool handler."""
    from llm.tools.handlers import get_price_history_handler
    result = await get_price_history_handler(
        args["symbol"],
        args.get("period", "3mo")
    )
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    "analyze_technical",
    "Run comprehensive technical analysis on a stock including RSI, MACD, "
    "Bollinger Bands, moving averages, and pattern detection. Returns signals "
    "with confidence levels.",
    {"symbol": str}
)
async def analyze_technical_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Technical analysis tool handler."""
    from llm.tools.handlers import analyze_technical_handler
    result = await analyze_technical_handler(args["symbol"])
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    "get_sector_performance",
    "Get performance data for all market sectors (Technology, Healthcare, "
    "Financials, etc.) including daily returns and relative strength. "
    "Useful for sector rotation analysis.",
    {}
)
async def get_sector_performance_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Sector performance tool handler."""
    from llm.tools.handlers import get_sector_performance_handler
    result = await get_sector_performance_handler()
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    "analyze_sector_rotation",
    "Analyze sector rotation patterns and identify market cycle phase. "
    "Returns leading/lagging sectors, risk-on/risk-off signals, and insights.",
    {}
)
async def analyze_sector_rotation_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Sector rotation analysis tool handler."""
    from llm.tools.handlers import analyze_sector_rotation_handler
    result = await analyze_sector_rotation_handler()
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    "detect_patterns",
    "Detect chart patterns for a stock (double top/bottom, head and shoulders, "
    "breakouts, golden/death cross, etc.). Returns patterns with confidence scores "
    "and price targets.",
    {"symbol": str}
)
async def detect_patterns_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Pattern detection tool handler."""
    from llm.tools.handlers import detect_patterns_handler
    result = await detect_patterns_handler(args["symbol"])
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    "detect_anomalies",
    "Detect unusual market activity for a stock including volume spikes, "
    "price gaps, volatility surges, and unusual price moves.",
    {"symbol": str}
)
async def detect_anomalies_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Anomaly detection tool handler."""
    from llm.tools.handlers import detect_anomalies_handler
    result = await detect_anomalies_handler(args["symbol"])
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    "get_economic_indicators",
    "Get key economic indicators from FRED including GDP, unemployment, "
    "CPI inflation, Fed Funds rate, yield curve, VIX, and consumer sentiment.",
    {}
)
async def get_economic_indicators_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Economic indicators tool handler."""
    from llm.tools.handlers import get_economic_indicators_handler
    result = await get_economic_indicators_handler()
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    "get_yield_curve",
    "Get current treasury yields for yield curve analysis. "
    "Returns rates for various maturities from 1 month to 30 years.",
    {}
)
async def get_yield_curve_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Yield curve tool handler."""
    from llm.tools.handlers import get_yield_curve_handler
    result = await get_yield_curve_handler()
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


@tool(
    "compare_stocks",
    "Compare multiple stocks on key metrics like price change, volume, "
    "technical signals, and sector positioning.",
    {"symbols": list}
)
async def compare_stocks_tool(args: dict[str, Any]) -> dict[str, Any]:
    """Stock comparison tool handler."""
    from llm.tools.handlers import compare_stocks_handler
    result = await compare_stocks_handler(args["symbols"])
    return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}


# Create the SDK MCP server with all tools
_market_tools_server = create_sdk_mcp_server(
    name="market-analyzer",
    version="1.0.0",
    tools=[
        get_stock_data_tool,
        get_price_history_tool,
        analyze_technical_tool,
        get_sector_performance_tool,
        analyze_sector_rotation_tool,
        detect_patterns_tool,
        detect_anomalies_tool,
        get_economic_indicators_tool,
        get_yield_curve_tool,
        compare_stocks_tool,
    ]
)


class MarketAnalysisAgent:
    """LLM agent for market analysis Q&A with tool calling.

    This agent uses Claude via the Claude Agent SDK which leverages the user's
    existing Claude Code subscription. It has access to various data sources
    including Yahoo Finance, FRED economic indicators, and technical analysis tools.

    Example:
        ```python
        agent = MarketAnalysisAgent()
        async for event in agent.chat("What's happening with AAPL?"):
            if event["type"] == "text":
                print(event["content"], end="")
            elif event["type"] == "tool_use":
                print(f"Using tool: {event['tool']}")
        ```
    """

    SYSTEM_PROMPT = """You are a market analysis assistant with access to real-time stock data,
technical indicators, and market insights. Use the available tools to answer questions
about stocks, sectors, and market conditions. Always cite specific data when available.

Guidelines:
- Be concise but thorough in your analysis
- Use technical indicators and patterns to support your analysis
- Mention key levels (support/resistance) when relevant
- Consider both bullish and bearish factors
- When analyzing sectors, consider rotation patterns and economic context
- Always explain what the data means in practical terms
- If data is unavailable or an error occurs, explain the limitation

When discussing price movements:
- Use percentages for context
- Compare to relevant benchmarks when appropriate
- Consider volume as confirmation of moves

When discussing technical indicators:
- Explain what each indicator is showing
- Note any divergences or confluences
- Be clear about signal strength and confidence levels"""

    def __init__(self) -> None:
        """Initialize the market analysis agent."""
        # No API key needed - uses Claude Code subscription
        self.conversation_history: list[dict[str, Any]] = []
        self.max_tool_iterations = 10  # Prevent infinite tool loops

        # Build allowed tools list for the SDK
        self._allowed_tools = [
            "mcp__market-analyzer__get_stock_data",
            "mcp__market-analyzer__get_price_history",
            "mcp__market-analyzer__analyze_technical",
            "mcp__market-analyzer__get_sector_performance",
            "mcp__market-analyzer__analyze_sector_rotation",
            "mcp__market-analyzer__detect_patterns",
            "mcp__market-analyzer__detect_anomalies",
            "mcp__market-analyzer__get_economic_indicators",
            "mcp__market-analyzer__get_yield_curve",
            "mcp__market-analyzer__compare_stocks",
        ]

    def _get_options(self) -> ClaudeAgentOptions:
        """Create Claude Agent options with MCP tools configured."""
        return ClaudeAgentOptions(
            system_prompt=self.SYSTEM_PROMPT,
            mcp_servers={"market-analyzer": _market_tools_server},
            allowed_tools=self._allowed_tools,
            max_turns=self.max_tool_iterations,
        )

    async def chat(
        self,
        message: str,
        stream: bool = True
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Process a chat message with streaming response.

        This method sends the user's message to Claude via the Claude Agent SDK,
        handles any tool calls, and streams the response back. It supports
        multiple rounds of tool use in a single response.

        Args:
            message: User's message/question.
            stream: Whether to stream the response (always True for now).

        Yields:
            Event dicts with the following types:
            - {"type": "text", "content": "..."} - Text content
            - {"type": "tool_use", "tool": "...", "args": {...}} - Tool being called
            - {"type": "tool_result", "tool": "...", "result": {...}} - Tool result
            - {"type": "error", "message": "..."} - Error occurred
            - {"type": "done"} - Response complete
        """
        # Add user message to history
        self.conversation_history.append({
            "role": "user",
            "content": message
        })

        try:
            options = self._get_options()

            # Build the prompt with conversation context if we have history
            if len(self.conversation_history) > 1:
                # Include conversation history in the prompt
                context_parts = []
                for msg in self.conversation_history[:-1]:  # All except current
                    role = msg["role"]
                    content = msg["content"]
                    if isinstance(content, str):
                        context_parts.append(f"{role.upper()}: {content}")
                    elif isinstance(content, list):
                        # Handle complex content (tool results etc)
                        text_parts = []
                        for item in content:
                            if isinstance(item, dict):
                                if item.get("type") == "text":
                                    text_parts.append(item.get("text", ""))
                        if text_parts:
                            context_parts.append(f"{role.upper()}: {''.join(text_parts)}")

                full_prompt = "\n\n".join(context_parts) + f"\n\nUSER: {message}"
            else:
                full_prompt = message

            # Use ClaudeSDKClient for bidirectional streaming with tool support
            async with ClaudeSDKClient(options=options) as client:
                await client.query(full_prompt)

                assistant_text = ""

                async for msg in client.receive_response():
                    if isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            if isinstance(block, TextBlock):
                                assistant_text += block.text
                                yield {"type": "text", "content": block.text}

                            elif isinstance(block, ToolUseBlock):
                                # Extract tool name (remove MCP prefix)
                                tool_name = block.name
                                if tool_name.startswith("mcp__market-analyzer__"):
                                    tool_name = tool_name[len("mcp__market-analyzer__"):]

                                yield {
                                    "type": "tool_use",
                                    "tool": tool_name,
                                    "args": block.input
                                }

                            elif isinstance(block, ToolResultBlock):
                                # Parse tool result
                                tool_name = getattr(block, 'tool_use_id', 'unknown')
                                try:
                                    result = json.loads(block.content) if isinstance(block.content, str) else block.content
                                except json.JSONDecodeError:
                                    result = block.content

                                yield {
                                    "type": "tool_result",
                                    "tool": tool_name,
                                    "result": result
                                }

                # Add assistant response to history
                if assistant_text:
                    self.conversation_history.append({
                        "role": "assistant",
                        "content": assistant_text
                    })

            yield {"type": "done"}

        except Exception as e:
            logger.error(f"Error in chat: {e}")
            yield {"type": "error", "message": str(e)}

    async def chat_simple(self, message: str) -> str:
        """Simple non-streaming chat that returns the full response.

        Args:
            message: User's message/question.

        Returns:
            Complete response text.
        """
        full_response = ""
        async for event in self.chat(message, stream=True):
            if event["type"] == "text":
                full_response += event["content"]
            elif event["type"] == "error":
                return f"Error: {event['message']}"
        return full_response

    def clear_history(self) -> None:
        """Clear conversation history to start fresh."""
        self.conversation_history = []

    def get_history(self) -> list[dict[str, Any]]:
        """Get current conversation history.

        Returns:
            List of conversation messages.
        """
        return self.conversation_history.copy()


# Module-level singleton instance
_agent_instance: MarketAnalysisAgent | None = None


def get_market_agent() -> MarketAnalysisAgent:
    """Get or create the singleton market agent instance.

    Returns:
        The market analysis agent instance.
    """
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = MarketAnalysisAgent()
    return _agent_instance


# Convenience alias
market_agent = get_market_agent
