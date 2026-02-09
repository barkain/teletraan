"""API routes for insight conversations with WebSocket support.

This module provides REST and WebSocket endpoints for conversational
exploration of DeepInsights, including streaming AI responses,
modification proposals, and research requests.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.deps import get_db
from analysis.insight_conversation_agent import (
    get_insight_conversation_agent,
    ModificationProposal,
    ResearchRequest,
)
from analysis.pattern_extractor import PatternExtractor
from database import async_session_factory
from models.deep_insight import DeepInsight
from models.insight_conversation import (
    InsightConversation,
    InsightConversationMessage,
    InsightModification,
    FollowUpResearch,
    ConversationStatus,
    MessageRole,
    ModificationStatus,
    ResearchStatus,
)
from schemas.insight_conversation import (
    ConversationCreate,
    ConversationUpdate,
    InsightConversationResponse,
    InsightConversationDetailResponse,
    InsightConversationListResponse,
    InsightConversationMessageResponse,
    InsightModificationResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# WEBSOCKET CONNECTION MANAGER
# =============================================================================


class InsightChatConnectionManager:
    """Manage WebSocket connections for insight conversations."""

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
        logger.info(
            f"Insight chat client {client_id} connected. "
            f"Total connections: {len(self.active_connections)}"
        )

    def disconnect(self, client_id: str) -> None:
        """Remove a client connection.

        Args:
            client_id: The client ID to disconnect.
        """
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            logger.info(
                f"Insight chat client {client_id} disconnected. "
                f"Total connections: {len(self.active_connections)}"
            )

    async def send_message(self, client_id: str, message: dict[str, Any]) -> bool:
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
manager = InsightChatConnectionManager()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


async def _get_insight_or_404(
    insight_id: int, db: AsyncSession
) -> DeepInsight:
    """Get insight by ID or raise 404."""
    result = await db.execute(
        select(DeepInsight).where(DeepInsight.id == insight_id)
    )
    insight = result.scalar_one_or_none()
    if not insight:
        raise HTTPException(status_code=404, detail="Insight not found")
    return insight


async def _get_conversation_or_404(
    conversation_id: int, db: AsyncSession
) -> InsightConversation:
    """Get conversation by ID or raise 404."""
    result = await db.execute(
        select(InsightConversation).where(InsightConversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _format_conversation_response(
    conversation: InsightConversation,
    message_count: int = 0,
    modification_count: int = 0,
) -> InsightConversationResponse:
    """Format conversation model to response schema."""
    return InsightConversationResponse(
        id=conversation.id,
        deep_insight_id=conversation.deep_insight_id,
        title=conversation.title,
        status=conversation.status.value,
        message_count=message_count,
        modification_count=modification_count,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        closed_at=conversation.closed_at,
        summary=conversation.summary,
    )


# =============================================================================
# PATTERN EXTRACTION BACKGROUND TASK
# =============================================================================


async def _extract_patterns_from_conversation(
    conversation_id: int,
    deep_insight_id: int,
) -> None:
    """Background task to extract patterns when a conversation is resolved/archived.

    Opens its own database session (the request session is closed by the time
    background tasks run), loads the conversation summary and linked insight
    data, then calls PatternExtractor to identify repeatable trading patterns.

    Args:
        conversation_id: ID of the conversation being closed.
        deep_insight_id: ID of the linked DeepInsight.
    """
    logger.info(
        f"Background pattern extraction starting for conversation {conversation_id}"
    )

    try:
        async with async_session_factory() as session:
            # Load conversation with messages
            result = await session.execute(
                select(InsightConversation)
                .options(selectinload(InsightConversation.messages))
                .where(InsightConversation.id == conversation_id)
            )
            conversation = result.scalar_one_or_none()

            if not conversation:
                logger.warning(
                    f"Conversation {conversation_id} not found for pattern extraction"
                )
                return

            # Build summary from conversation.summary or concatenated messages
            summary = conversation.summary or ""
            if not summary and conversation.messages:
                message_texts = [
                    f"{msg.role.value}: {msg.content}"
                    for msg in sorted(
                        conversation.messages, key=lambda m: m.created_at
                    )
                ]
                summary = "\n".join(message_texts)

            if not summary:
                logger.info(
                    f"No summary or messages for conversation {conversation_id}, "
                    "skipping pattern extraction"
                )
                return

            # Load the linked DeepInsight for insight context
            insight_result = await session.execute(
                select(DeepInsight).where(DeepInsight.id == deep_insight_id)
            )
            insight = insight_result.scalar_one_or_none()

            # Build insights list from the linked DeepInsight
            insights: list[dict[str, Any]] = []
            if insight:
                insights.append({
                    "title": insight.title,
                    "insight_type": insight.insight_type,
                    "action": insight.action,
                    "thesis": insight.thesis,
                    "primary_symbol": insight.primary_symbol,
                    "confidence": insight.confidence,
                    "time_horizon": insight.time_horizon,
                })

            # Run pattern extraction
            extractor = PatternExtractor(db_session=session)
            patterns = await extractor.extract_from_conversation_summary(
                conversation_id=uuid.UUID(int=conversation_id),
                summary=summary,
                insights=insights,
            )

            await session.commit()

            logger.info(
                f"Pattern extraction complete for conversation {conversation_id}: "
                f"{len(patterns)} patterns created"
            )

    except Exception:
        logger.exception(
            f"Pattern extraction failed for conversation {conversation_id}"
        )


# =============================================================================
# REST ENDPOINTS - CONVERSATIONS FOR INSIGHTS
# =============================================================================


@router.post("/insights/{insight_id}/conversations", response_model=InsightConversationResponse)
async def create_conversation_for_insight(
    insight_id: int,
    request: ConversationCreate | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Start a new conversation for an insight.

    Args:
        insight_id: ID of the DeepInsight to discuss.
        request: Optional conversation creation parameters.
        db: Database session.

    Returns:
        The created conversation.

    Raises:
        HTTPException: If insight not found.
    """
    # Verify insight exists
    insight = await _get_insight_or_404(insight_id, db)

    # Generate title if not provided
    title = (
        request.title
        if request and request.title
        else f"Discussion: {insight.title[:50]}"
    )

    # Create conversation
    conversation = InsightConversation(
        deep_insight_id=insight_id,
        title=title,
        status=ConversationStatus.ACTIVE,
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)

    logger.info(f"Created conversation {conversation.id} for insight {insight_id}")

    return _format_conversation_response(conversation)


@router.get("/insights/{insight_id}/conversations", response_model=InsightConversationListResponse)
async def list_conversations_for_insight(
    insight_id: int,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
    status: ConversationStatus | None = None,
):
    """List all conversations for an insight.

    Args:
        insight_id: ID of the DeepInsight.
        db: Database session.
        limit: Maximum number of conversations to return.
        offset: Number of conversations to skip.
        status: Optional filter by conversation status.

    Returns:
        Paginated list of conversations.

    Raises:
        HTTPException: If insight not found.
    """
    # Verify insight exists
    await _get_insight_or_404(insight_id, db)

    # Build query
    query = (
        select(InsightConversation)
        .where(InsightConversation.deep_insight_id == insight_id)
        .order_by(desc(InsightConversation.created_at))
    )

    if status:
        query = query.where(InsightConversation.status == status)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Apply pagination
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    conversations = result.scalars().all()

    # Get message counts for each conversation
    items = []
    for conv in conversations:
        msg_count_result = await db.scalar(
            select(func.count())
            .where(InsightConversationMessage.conversation_id == conv.id)
        )
        mod_count_result = await db.scalar(
            select(func.count())
            .where(InsightModification.conversation_id == conv.id)
        )
        items.append(
            _format_conversation_response(
                conv,
                message_count=msg_count_result or 0,
                modification_count=mod_count_result or 0,
            )
        )

    return InsightConversationListResponse(
        items=items,
        total=total,
        has_more=(offset + limit) < total,
    )


# =============================================================================
# REST ENDPOINTS - CONVERSATIONS
# =============================================================================


@router.get("/conversations", response_model=InsightConversationListResponse)
async def list_all_conversations(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
    status: ConversationStatus | None = None,
):
    """List all conversations across all insights.

    Args:
        db: Database session.
        limit: Maximum number of conversations to return.
        offset: Number of conversations to skip.
        status: Optional filter by conversation status.

    Returns:
        Paginated list of conversations with insight info.
    """
    # Build query
    query = (
        select(InsightConversation)
        .order_by(desc(InsightConversation.updated_at))
    )

    if status:
        query = query.where(InsightConversation.status == status)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Apply pagination
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    conversations = result.scalars().all()

    # Get message and modification counts for each conversation
    items = []
    for conv in conversations:
        msg_count_result = await db.scalar(
            select(func.count())
            .where(InsightConversationMessage.conversation_id == conv.id)
        )
        mod_count_result = await db.scalar(
            select(func.count())
            .where(InsightModification.conversation_id == conv.id)
        )
        items.append(
            _format_conversation_response(
                conv,
                message_count=msg_count_result or 0,
                modification_count=mod_count_result or 0,
            )
        )

    return InsightConversationListResponse(
        items=items,
        total=total,
        has_more=(offset + limit) < total,
    )


@router.get("/conversations/{conversation_id}", response_model=InsightConversationDetailResponse)
async def get_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    message_limit: int = Query(default=50, le=200),
):
    """Get a conversation with its recent messages.

    Args:
        conversation_id: ID of the conversation.
        db: Database session.
        message_limit: Maximum number of messages to include.

    Returns:
        Conversation details with messages.

    Raises:
        HTTPException: If conversation not found.
    """
    # Load conversation with messages
    result = await db.execute(
        select(InsightConversation)
        .options(
            selectinload(InsightConversation.messages),
            selectinload(InsightConversation.modifications),
        )
        .where(InsightConversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Get message count
    msg_count = len(conversation.messages)

    # Get pending modifications count
    pending_mods = [
        m for m in conversation.modifications
        if m.status == ModificationStatus.PENDING
    ]

    # Format recent messages (newest first, then reverse for chronological)
    sorted_messages = sorted(
        conversation.messages, key=lambda m: m.created_at, reverse=True
    )[:message_limit]
    sorted_messages.reverse()

    recent_messages = [
        InsightConversationMessageResponse(
            id=m.id,
            conversation_id=m.conversation_id,
            role=m.role.value,
            content=m.content,
            content_type=m.content_type.value,
            metadata_=m.metadata_,
            parent_message_id=m.parent_message_id,
            created_at=m.created_at,
        )
        for m in sorted_messages
    ]

    pending_modifications = [
        InsightModificationResponse(
            id=m.id,
            deep_insight_id=m.deep_insight_id,
            conversation_id=m.conversation_id,
            message_id=m.message_id,
            modification_type=m.modification_type.value,
            field_modified=m.field_modified,
            previous_value=m.previous_value,
            new_value=m.new_value,
            reason=m.reason,
            status=m.status.value,
            approved_at=m.approved_at,
            rejected_reason=m.rejected_reason,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )
        for m in pending_mods
    ]

    return InsightConversationDetailResponse(
        id=conversation.id,
        deep_insight_id=conversation.deep_insight_id,
        title=conversation.title,
        status=conversation.status.value,
        message_count=msg_count,
        modification_count=len(conversation.modifications),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        closed_at=conversation.closed_at,
        summary=conversation.summary,
        research_context=conversation.research_context,
        recent_messages=recent_messages,
        pending_modifications=pending_modifications,
    )


@router.patch("/conversations/{conversation_id}", response_model=InsightConversationResponse)
async def update_conversation(
    conversation_id: int,
    request: ConversationUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Update a conversation's title or status.

    When the status changes to RESOLVED or ARCHIVED, pattern extraction is
    triggered as a background task to identify repeatable trading patterns
    from the conversation content.

    Args:
        conversation_id: ID of the conversation.
        request: Update parameters.
        background_tasks: FastAPI background tasks for async pattern extraction.
        db: Database session.

    Returns:
        The updated conversation.

    Raises:
        HTTPException: If conversation not found.
    """
    conversation = await _get_conversation_or_404(conversation_id, db)

    if request.title is not None:
        conversation.title = request.title

    status_closing = False
    if request.status is not None:
        conversation.status = ConversationStatus(request.status.value)
        if request.status in (ConversationStatus.ARCHIVED, ConversationStatus.RESOLVED):
            conversation.closed_at = datetime.utcnow()
            status_closing = True

    await db.commit()
    await db.refresh(conversation)

    # Trigger pattern extraction in background when conversation closes
    if status_closing:
        background_tasks.add_task(
            _extract_patterns_from_conversation,
            conversation_id=conversation.id,
            deep_insight_id=conversation.deep_insight_id,
        )
        logger.info(
            f"Queued pattern extraction for conversation {conversation_id} "
            f"(status -> {conversation.status.value})"
        )

    # Get counts
    msg_count = await db.scalar(
        select(func.count())
        .where(InsightConversationMessage.conversation_id == conversation_id)
    )
    mod_count = await db.scalar(
        select(func.count())
        .where(InsightModification.conversation_id == conversation_id)
    )

    return _format_conversation_response(
        conversation,
        message_count=msg_count or 0,
        modification_count=mod_count or 0,
    )


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a conversation and all its messages.

    Args:
        conversation_id: ID of the conversation.
        db: Database session.

    Returns:
        Success message.

    Raises:
        HTTPException: If conversation not found.
    """
    conversation = await _get_conversation_or_404(conversation_id, db)

    await db.delete(conversation)
    await db.commit()

    logger.info(f"Deleted conversation {conversation_id}")

    return {"status": "deleted", "conversation_id": conversation_id}


# =============================================================================
# WEBSOCKET ENDPOINT - STREAMING CHAT
# =============================================================================


@router.websocket("/conversations/{conversation_id}/chat")
async def insight_chat_websocket(
    websocket: WebSocket,
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
):
    """WebSocket endpoint for streaming insight conversation chat.

    Message Protocol:
    - Client sends: {"id": "msg-id", "message": "user question"}
    - Server sends (ack): {"type": "ack", "message_id": "msg-id"}
    - Server sends (assistant_chunk): {"type": "assistant_chunk", "content": "...", "message_id": "..."}
    - Server sends (modification_proposal): {"type": "modification_proposal", "data": {...}, "message_id": "..."}
    - Server sends (research_request): {"type": "research_request", "data": {...}, "message_id": "..."}
    - Server sends (done): {"type": "done", "message_id": "..."}
    - Server sends (error): {"type": "error", "error": "...", "message_id": "..."}

    Args:
        websocket: The WebSocket connection.
        conversation_id: ID of the conversation.
        db: Database session.
    """
    # Verify conversation exists
    result = await db.execute(
        select(InsightConversation).where(InsightConversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        await websocket.close(code=4004, reason="Conversation not found")
        return

    if conversation.status != ConversationStatus.ACTIVE:
        await websocket.close(code=4003, reason="Conversation is not active")
        return

    client_id = f"insight_{conversation_id}_{uuid.uuid4().hex[:8]}"
    await manager.connect(websocket, client_id)

    # Get the conversation agent
    agent = get_insight_conversation_agent()

    try:
        while True:
            # Receive message from client
            raw_data = await websocket.receive_text()

            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                await manager.send_message(client_id, {
                    "type": "error",
                    "error": "Invalid JSON message",
                })
                continue

            message = data.get("message", "")
            message_id = data.get("id", str(uuid.uuid4()))

            if not message.strip():
                await manager.send_message(client_id, {
                    "type": "error",
                    "error": "Empty message",
                    "message_id": message_id,
                })
                continue

            # Send acknowledgment
            await manager.send_message(client_id, {
                "type": "ack",
                "message_id": message_id,
            })

            # Save user message to database
            try:
                user_msg = await agent.save_message(
                    conversation_id=conversation_id,
                    role=MessageRole.USER,
                    content=message,
                    metadata={"client_message_id": message_id},
                )
            except Exception as e:
                logger.error(f"Failed to save user message: {e}")
                await manager.send_message(client_id, {
                    "type": "error",
                    "error": "Failed to save message",
                    "message_id": message_id,
                })
                continue

            # Stream response from agent
            full_response = ""
            try:
                async for chunk in agent.chat(message, conversation_id):
                    full_response += chunk
                    await manager.send_message(client_id, {
                        "type": "assistant_chunk",
                        "content": chunk,
                        "message_id": message_id,
                    })

                # Detect modification proposal
                modification_proposal = agent._detect_modification_intent(full_response)
                if modification_proposal:
                    # Save modification to database
                    mod_record = await _save_modification_proposal(
                        db=db,
                        conversation=conversation,
                        message_id=user_msg.id,
                        proposal=modification_proposal,
                    )

                    await manager.send_message(client_id, {
                        "type": "modification_proposal",
                        "data": {
                            "modification_id": mod_record.id,
                            "field": modification_proposal.field,
                            "old_value": modification_proposal.old_value,
                            "new_value": modification_proposal.new_value,
                            "reasoning": modification_proposal.reasoning,
                            "modification_type": modification_proposal.modification_type.value,
                        },
                        "message_id": message_id,
                    })

                # Detect research request
                research_request = agent._detect_research_intent(full_response)
                if research_request:
                    # Save research request to database
                    research_record = await _save_research_request(
                        db=db,
                        conversation=conversation,
                        message_id=user_msg.id,
                        request=research_request,
                    )

                    await manager.send_message(client_id, {
                        "type": "research_request",
                        "data": {
                            "research_id": research_record.id,
                            "focus_area": research_request.focus_area,
                            "specific_questions": research_request.specific_questions,
                            "related_symbols": research_request.related_symbols,
                            "research_type": research_request.research_type.value,
                        },
                        "message_id": message_id,
                    })

                # Clean and save assistant message
                clean_response = agent._clean_response(full_response)
                await agent.save_message(
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT,
                    content=clean_response,
                    metadata={
                        "client_message_id": message_id,
                        "has_modification": modification_proposal is not None,
                        "has_research": research_request is not None,
                    },
                )

                # Send done signal
                await manager.send_message(client_id, {
                    "type": "done",
                    "message_id": message_id,
                })

            except Exception as e:
                logger.error(f"Error processing chat for client {client_id}: {e}")
                await manager.send_message(client_id, {
                    "type": "error",
                    "error": str(e),
                    "message_id": message_id,
                })

    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"Unexpected error for client {client_id}: {e}")
        manager.disconnect(client_id)


async def _save_modification_proposal(
    db: AsyncSession,
    conversation: InsightConversation,
    message_id: int,
    proposal: ModificationProposal,
) -> InsightModification:
    """Save a modification proposal to the database.

    Args:
        db: Database session.
        conversation: The parent conversation.
        message_id: ID of the triggering message.
        proposal: The modification proposal.

    Returns:
        The created modification record.
    """
    modification = InsightModification(
        deep_insight_id=conversation.deep_insight_id,
        conversation_id=conversation.id,
        message_id=message_id,
        modification_type=proposal.modification_type,
        field_modified=proposal.field,
        previous_value={"value": proposal.old_value} if proposal.old_value else None,
        new_value={"value": proposal.new_value},
        reason=proposal.reasoning,
        status=ModificationStatus.PENDING,
    )
    db.add(modification)
    await db.commit()
    await db.refresh(modification)

    logger.info(
        f"Created modification proposal {modification.id} "
        f"for insight {conversation.deep_insight_id}"
    )

    return modification


async def _save_research_request(
    db: AsyncSession,
    conversation: InsightConversation,
    message_id: int,
    request: ResearchRequest,
) -> FollowUpResearch:
    """Save a research request to the database.

    Args:
        db: Database session.
        conversation: The parent conversation.
        message_id: ID of the triggering message.
        request: The research request.

    Returns:
        The created research record.
    """
    research = FollowUpResearch(
        conversation_id=conversation.id,
        source_message_id=message_id,
        research_type=request.research_type,
        query=request.focus_area,
        parameters={
            "specific_questions": request.specific_questions,
            "related_symbols": request.related_symbols,
        },
        status=ResearchStatus.PENDING,
    )
    db.add(research)
    await db.commit()
    await db.refresh(research)

    logger.info(
        f"Created research request {research.id} "
        f"for conversation {conversation.id}"
    )

    return research
