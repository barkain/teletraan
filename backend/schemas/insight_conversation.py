"""Pydantic schemas for insight conversations API."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# Enums for API contracts
class ConversationStatus(str, Enum):
    """Status of an insight conversation."""

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    RESOLVED = "RESOLVED"


class MessageRole(str, Enum):
    """Role of the message sender."""

    USER = "USER"
    ASSISTANT = "ASSISTANT"
    SYSTEM = "SYSTEM"
    TOOL = "TOOL"


class ContentType(str, Enum):
    """Type of message content."""

    TEXT = "TEXT"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"


class ModificationType(str, Enum):
    """Types of modifications to insights."""

    THESIS_UPDATE = "THESIS_UPDATE"
    CONFIDENCE_CHANGE = "CONFIDENCE_CHANGE"
    RISK_ADDED = "RISK_ADDED"
    RISK_REMOVED = "RISK_REMOVED"
    SYMBOL_ADDED = "SYMBOL_ADDED"
    SYMBOL_REMOVED = "SYMBOL_REMOVED"
    ACTION_CHANGED = "ACTION_CHANGED"
    TIME_HORIZON_CHANGED = "TIME_HORIZON_CHANGED"
    INVALIDATED = "INVALIDATED"


class ModificationStatus(str, Enum):
    """Approval status of a modification."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ResearchType(str, Enum):
    """Types of follow-up research."""

    SCENARIO_ANALYSIS = "SCENARIO_ANALYSIS"
    DEEP_DIVE = "DEEP_DIVE"
    CORRELATION_CHECK = "CORRELATION_CHECK"
    WHAT_IF = "WHAT_IF"


class ResearchStatus(str, Enum):
    """Status of follow-up research."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# Request Schemas
class ConversationCreate(BaseModel):
    """Request schema for creating a new conversation."""

    title: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Optional title for the conversation. Auto-generated if not provided.",
    )


class ConversationUpdate(BaseModel):
    """Request schema for updating a conversation."""

    title: Optional[str] = Field(default=None, max_length=255)
    status: Optional[ConversationStatus] = None


class MessageCreate(BaseModel):
    """Request schema for creating a new message."""

    content: str = Field(..., min_length=1, max_length=32000)
    request_modification: bool = Field(
        default=False,
        description="Signal intent to modify the insight based on this message.",
    )
    spawn_research: Optional["SpawnResearchRequest"] = Field(
        default=None,
        description="Request to spawn follow-up research.",
    )


class SpawnResearchRequest(BaseModel):
    """Request schema for spawning follow-up research."""

    research_type: ResearchType
    parameters: dict[str, Any] = Field(default_factory=dict)


class ModificationApproval(BaseModel):
    """Request schema for approving a modification."""

    reason: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional reason for approval.",
    )


class ModificationRejection(BaseModel):
    """Request schema for rejecting a modification."""

    reason: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Reason for rejection.",
    )


# Response Schemas
class MessageMetadata(BaseModel):
    """Metadata associated with a conversation message."""

    model_config = ConfigDict(extra="allow")

    tool_name: Optional[str] = None
    tool_args: Optional[dict[str, Any]] = None
    token_usage: Optional[dict[str, int]] = None
    model: Optional[str] = None


class InsightConversationMessageResponse(BaseModel):
    """Response schema for a conversation message."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: MessageRole
    content: str
    content_type: ContentType
    metadata_: Optional[dict[str, Any]] = Field(default=None, alias="metadata")
    parent_message_id: Optional[int] = None
    created_at: datetime


class InsightModificationResponse(BaseModel):
    """Response schema for an insight modification."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    deep_insight_id: int
    conversation_id: Optional[int]
    message_id: Optional[int]
    modification_type: ModificationType
    field_modified: str
    previous_value: Optional[Any]
    new_value: Optional[Any]
    reason: str
    status: ModificationStatus
    approved_at: Optional[datetime]
    rejected_reason: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime] = None


class FollowUpResearchResponse(BaseModel):
    """Response schema for follow-up research."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    source_message_id: Optional[int]
    research_type: ResearchType
    query: str
    parameters: Optional[dict[str, Any]]
    status: ResearchStatus
    result_insight_id: Optional[int]
    error_message: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]


class InsightConversationResponse(BaseModel):
    """Response schema for an insight conversation."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    deep_insight_id: int
    title: str
    status: ConversationStatus
    message_count: int = 0
    modification_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    summary: Optional[str] = None


class InsightConversationDetailResponse(InsightConversationResponse):
    """Detailed response schema including messages and modifications."""

    research_context: Optional[dict[str, Any]] = None
    recent_messages: list[InsightConversationMessageResponse] = Field(
        default_factory=list
    )
    pending_modifications: list[InsightModificationResponse] = Field(
        default_factory=list
    )


class ConversationCloseResponse(BaseModel):
    """Response schema for closing a conversation."""

    summary: str
    modification_count: int
    research_spawned_count: int


# List Response Schemas
class InsightConversationListResponse(BaseModel):
    """Paginated list of conversations."""

    items: list[InsightConversationResponse]
    total: int
    has_more: bool = False


class InsightConversationMessageListResponse(BaseModel):
    """Paginated list of messages."""

    items: list[InsightConversationMessageResponse]
    total: int
    has_more: bool = False


class InsightModificationListResponse(BaseModel):
    """Paginated list of modifications."""

    items: list[InsightModificationResponse]
    total: int
    has_more: bool = False


class FollowUpResearchListResponse(BaseModel):
    """Paginated list of research requests."""

    items: list[FollowUpResearchResponse]
    total: int
    has_more: bool = False


# WebSocket Message Schemas
class InsightChatMessage(BaseModel):
    """Client-to-server WebSocket message for insight chat."""

    id: str = Field(..., description="Client-generated UUID for the message")
    message: str = Field(..., min_length=1, max_length=32000)
    request_modification: bool = False
    spawn_research: Optional[SpawnResearchRequest] = None


class ServerMessageType(str, Enum):
    """Types of server-to-client WebSocket messages."""

    ACK = "ack"
    TEXT = "text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    MODIFICATION_PROPOSED = "modification_proposed"
    RESEARCH_SPAWNED = "research_spawned"
    RESEARCH_COMPLETE = "research_complete"
    DONE = "done"
    ERROR = "error"


class ProposedModification(BaseModel):
    """Details of a proposed insight modification."""

    modification_id: int
    field: str
    current_value: Any
    proposed_value: Any
    reason: str


class SpawnedResearch(BaseModel):
    """Details of spawned research."""

    research_id: int
    status: ResearchStatus
    estimated_duration_seconds: Optional[int] = None


class ServerMessage(BaseModel):
    """Server-to-client WebSocket message."""

    type: ServerMessageType
    message_id: Optional[str] = None
    content: Optional[str] = None
    modification: Optional[ProposedModification] = None
    research: Optional[SpawnedResearch] = None
    error: Optional[str] = None


# Update forward references
MessageCreate.model_rebuild()
