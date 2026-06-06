"""WebSocket endpoint for real-time LLM chat communication."""

import json
import logging
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from api.deps import get_current_user_ws
from llm.market_agent import MarketAnalysisAgent
from models.user import User

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


@router.websocket("/chat")
async def chat_websocket(
    websocket: WebSocket,
    user: User = Depends(get_current_user_ws),
) -> None:
    """WebSocket endpoint for streaming LLM chat responses.

    Requires a valid access token passed as a ``token`` query parameter
    (browsers cannot set an Authorization header on WebSocket upgrades).

    Each connection gets its own isolated agent instance with independent
    conversation history — sessions never bleed into one another.

    Message Protocol:
    - Client sends: {"id": "msg-id", "message": "user question"}
    - Client sends (clear): {"type": "clear"} — resets this session's history
    - Server sends (ack): {"type": "ack", "message_id": "msg-id"}
    - Server sends (history_cleared): {"type": "history_cleared"}
    - Server sends (text): {"type": "text", "content": "response chunk"}
    - Server sends (tool_call): {"type": "tool_call", "tool_name": "...", "tool_args": {...}}
    - Server sends (tool_result): {"type": "tool_result", "tool_name": "...", "tool_result": {...}}
    - Server sends (done): {"type": "done"}
    - Server sends (error): {"type": "error", "error": "error message"}
    """
    client_id = str(uuid.uuid4())

    await manager.connect(websocket, client_id)

    # Each connection gets its own agent — conversation history is isolated
    # per session and never bleeds across users/tabs.
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

            # Control message: clear this session's conversation history
            if data.get("type") == "clear":
                agent.clear_history()
                await manager.send_message(client_id, {
                    "type": "history_cleared"
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
