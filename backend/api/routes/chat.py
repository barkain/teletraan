"""WebSocket endpoint for real-time LLM chat communication."""

import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, WebSocketException, status

from config import get_settings
from llm.market_agent import MarketAnalysisAgent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


class ConnectionManager:
    """Manage WebSocket connections for chat clients."""

    def __init__(self) -> None:
        """Initialize connection manager."""
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        """Accept and register a new WebSocket connection.

        Args:
            websocket: The WebSocket connection to accept.
            client_id: Unique identifier for the client.
        """
        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info(f"Client {client_id} connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, client_id: str) -> None:
        """Remove a client connection.

        Args:
            client_id: The client ID to disconnect.
        """
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            logger.info(f"Client {client_id} disconnected. Total connections: {len(self.active_connections)}")

    async def send_message(self, client_id: str, message: dict) -> bool:
        """Send a JSON message to a specific client.

        Args:
            client_id: The target client ID.
            message: The message dict to send.

        Returns:
            True if message was sent, False if client not found.
        """
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_json(message)
                return True
            except Exception as e:
                logger.error(f"Error sending message to {client_id}: {e}")
                return False
        return False


# Global connection manager instance
manager = ConnectionManager()


def _check_ws_api_key(api_key: Optional[str]) -> None:
    """Verify the API key for a WebSocket connection.

    WebSocket upgrade requests cannot carry custom headers in browsers, so the
    API key is accepted as an ``?api_key=`` query parameter instead.
    """
    settings = get_settings()
    configured_key = settings.TELETRAAN_API_KEY
    if not configured_key:
        return  # Open access — no key configured
    if api_key != configured_key:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)


@router.websocket("/chat")
async def chat_websocket(
    websocket: WebSocket,
    api_key: Optional[str] = Query(None, alias="api_key"),
) -> None:
    """WebSocket endpoint for streaming LLM chat responses.

    Each connection gets its own isolated agent instance with independent
    conversation history — sessions never bleed into one another.

    Authentication: pass ``?api_key=<key>`` in the WebSocket URL when
    ``TELETRAAN_API_KEY`` is configured.

    Message Protocol:
    - Client sends: {"id": "msg-id", "message": "user question"}
    - Server sends (ack): {"type": "ack", "message_id": "msg-id"}
    - Server sends (text): {"type": "text", "content": "response chunk"}
    - Server sends (tool_call): {"type": "tool_call", "tool_name": "...", "tool_args": {...}}
    - Server sends (tool_result): {"type": "tool_result", "tool_name": "...", "tool_result": {...}}
    - Server sends (done): {"type": "done"}
    - Server sends (error): {"type": "error", "error": "error message"}
    """
    _check_ws_api_key(api_key)

    client_id = str(uuid.uuid4())
    await manager.connect(websocket, client_id)

    # Each connection gets its own agent — no shared conversation state
    agent = MarketAnalysisAgent()

    try:
        while True:
            # Receive message from client
            raw_data = await websocket.receive_text()
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                await manager.send_message(client_id, {
                    "type": "error",
                    "error": "Invalid JSON message"
                })
                continue

            message = data.get("message", "")
            message_id = data.get("id", str(uuid.uuid4()))

            if not message.strip():
                await manager.send_message(client_id, {
                    "type": "error",
                    "error": "Empty message"
                })
                continue

            # Send acknowledgment
            await manager.send_message(client_id, {
                "type": "ack",
                "message_id": message_id
            })

            # Stream response from LLM
            try:
                async for chunk in agent.chat(message, stream=True):
                    chunk_type = chunk.get("type", "text")

                    if chunk_type == "text":
                        await manager.send_message(client_id, {
                            "type": "text",
                            "content": chunk.get("content", ""),
                            "message_id": message_id
                        })
                    elif chunk_type == "tool_use":
                        await manager.send_message(client_id, {
                            "type": "tool_call",
                            "tool_name": chunk.get("tool"),
                            "tool_args": chunk.get("args"),
                            "message_id": message_id
                        })
                    elif chunk_type == "tool_result":
                        await manager.send_message(client_id, {
                            "type": "tool_result",
                            "tool_name": chunk.get("tool"),
                            "tool_result": chunk.get("result"),
                            "message_id": message_id
                        })
                    elif chunk_type == "done":
                        await manager.send_message(client_id, {
                            "type": "done",
                            "message_id": message_id
                        })
                    elif chunk_type == "error":
                        await manager.send_message(client_id, {
                            "type": "error",
                            "error": chunk.get("message", "Unknown error"),
                            "message_id": message_id
                        })

            except Exception as e:
                logger.error(f"Error processing chat for client {client_id}: {e}")
                await manager.send_message(client_id, {
                    "type": "error",
                    "error": str(e),
                    "message_id": message_id
                })

    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"Unexpected error for client {client_id}: {e}")
        manager.disconnect(client_id)


@router.post("/chat/clear")
async def clear_chat() -> dict:
    """Clear chat history endpoint (no-op — history is now per-session).

    Returns:
        Status message.
    """
    return {"status": "ok", "message": "Chat history is per-session; no global state to clear"}
