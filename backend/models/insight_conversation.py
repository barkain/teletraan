"""Insight conversation models for AI-augmented insight exploration.

This module defines the data models for linking conversations to DeepInsights,
enabling contextual AI conversations grounded in research findings.
"""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

from .base import TimestampMixin


class ConversationStatus(str, enum.Enum):
    """Status of an insight conversation."""

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    RESOLVED = "RESOLVED"


class MessageRole(str, enum.Enum):
    """Role of the message sender, following Claude's convention."""

    USER = "USER"
    ASSISTANT = "ASSISTANT"
    SYSTEM = "SYSTEM"
    TOOL = "TOOL"


class ContentType(str, enum.Enum):
    """Type of message content for proper rendering."""

    TEXT = "TEXT"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"


class ModificationType(str, enum.Enum):
    """Types of modifications that can be made to insights from conversations."""

    THESIS_UPDATE = "THESIS_UPDATE"
    CONFIDENCE_CHANGE = "CONFIDENCE_CHANGE"
    RISK_ADDED = "RISK_ADDED"
    RISK_REMOVED = "RISK_REMOVED"
    SYMBOL_ADDED = "SYMBOL_ADDED"
    SYMBOL_REMOVED = "SYMBOL_REMOVED"
    ACTION_CHANGED = "ACTION_CHANGED"
    TIME_HORIZON_CHANGED = "TIME_HORIZON_CHANGED"
    INVALIDATED = "INVALIDATED"


class ModificationStatus(str, enum.Enum):
    """Approval status of a proposed modification."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ResearchType(str, enum.Enum):
    """Types of follow-up research that can be spawned from conversations."""

    SCENARIO_ANALYSIS = "SCENARIO_ANALYSIS"
    DEEP_DIVE = "DEEP_DIVE"
    CORRELATION_CHECK = "CORRELATION_CHECK"
    WHAT_IF = "WHAT_IF"


class ResearchStatus(str, enum.Enum):
    """Status of a follow-up research request."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class InsightConversation(TimestampMixin, Base):
    """Model for conversations linked to DeepInsights.

    Enables AI-augmented exploration of market insights, storing conversation
    context and tracking modifications that arise from discussions.

    Attributes:
        id: Primary key
        deep_insight_id: Foreign key to the linked DeepInsight
        title: Conversation title (auto-generated or user-defined)
        status: Current status (ACTIVE, ARCHIVED, RESOLVED)
        closed_at: Timestamp when conversation was closed
        summary: AI-generated summary when conversation closes
        research_context: Snapshot of insight context at conversation creation
    """

    __tablename__ = "insight_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    deep_insight_id: Mapped[int] = mapped_column(
        ForeignKey("deep_insights.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus),
        default=ConversationStatus.ACTIVE,
        index=True,
    )
    closed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    research_context: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # Relationships
    messages: Mapped[list["InsightConversationMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="InsightConversationMessage.created_at",
    )
    modifications: Mapped[list["InsightModification"]] = relationship(
        back_populates="conversation",
        foreign_keys="InsightModification.conversation_id",
    )
    research_requests: Mapped[list["FollowUpResearch"]] = relationship(
        back_populates="conversation",
    )

    __table_args__ = (
        Index("ix_insight_conv_insight_status", "deep_insight_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<InsightConversation(id={self.id}, insight_id={self.deep_insight_id}, "
            f"status={self.status!r}, title={self.title!r})>"
        )


class InsightConversationMessage(TimestampMixin, Base):
    """Model for individual messages within an insight conversation.

    Stores all messages exchanged during a conversation, including user messages,
    AI responses, and tool interactions.

    Attributes:
        id: Primary key
        conversation_id: Foreign key to the parent conversation
        role: Message role (USER, ASSISTANT, SYSTEM, TOOL)
        content: The message content
        content_type: Type of content (TEXT, TOOL_CALL, TOOL_RESULT)
        metadata: Additional info (tool details, token usage, model info)
        parent_message_id: For threaded replies (optional)
    """

    __tablename__ = "insight_conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("insight_conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[ContentType] = mapped_column(
        Enum(ContentType),
        default=ContentType.TEXT,
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",  # Column name in DB
        JSON,
        nullable=True,
    )
    parent_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("insight_conversation_messages.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    conversation: Mapped["InsightConversation"] = relationship(
        back_populates="messages",
    )
    replies: Mapped[list["InsightConversationMessage"]] = relationship(
        back_populates="parent_message",
        remote_side="InsightConversationMessage.parent_message_id",
    )
    parent_message: Mapped["InsightConversationMessage | None"] = relationship(
        back_populates="replies",
        remote_side="InsightConversationMessage.id",
        foreign_keys=[parent_message_id],
    )

    __table_args__ = (
        Index("ix_conv_messages_conv_created", "conversation_id", "created_at"),
    )

    def __repr__(self) -> str:
        content_preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return (
            f"<InsightConversationMessage(id={self.id}, role={self.role!r}, "
            f"content={content_preview!r})>"
        )


class InsightModification(TimestampMixin, Base):
    """Model for tracking modifications to insights arising from conversations.

    Provides full audit trail of changes with before/after values and
    optional approval workflow.

    Attributes:
        id: Primary key
        deep_insight_id: Foreign key to the modified insight
        conversation_id: Foreign key to the source conversation
        message_id: Foreign key to the triggering message (optional)
        modification_type: Type of modification
        field_modified: Name of the field that was changed
        previous_value: Value before modification (JSON)
        new_value: Value after modification (JSON)
        reason: Justification for the modification
        status: Approval status (PENDING, APPROVED, REJECTED)
        approved_at: Timestamp when modification was approved
        rejected_reason: Reason for rejection (if rejected)
    """

    __tablename__ = "insight_modifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    deep_insight_id: Mapped[int] = mapped_column(
        ForeignKey("deep_insights.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("insight_conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("insight_conversation_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    modification_type: Mapped[ModificationType] = mapped_column(
        Enum(ModificationType),
        nullable=False,
    )
    field_modified: Mapped[str] = mapped_column(String(100), nullable=False)
    previous_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ModificationStatus] = mapped_column(
        Enum(ModificationStatus),
        default=ModificationStatus.PENDING,
        index=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    conversation: Mapped["InsightConversation | None"] = relationship(
        back_populates="modifications",
        foreign_keys=[conversation_id],
    )

    __table_args__ = (
        Index("ix_modifications_insight_status", "deep_insight_id", "status"),
        Index("ix_modifications_insight_approved", "deep_insight_id", "approved_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<InsightModification(id={self.id}, type={self.modification_type!r}, "
            f"field={self.field_modified!r}, status={self.status!r})>"
        )


class FollowUpResearch(TimestampMixin, Base):
    """Model for follow-up research requests spawned from conversations.

    Enables users to trigger focused research (e.g., "what if?" scenarios)
    from conversation discoveries.

    Attributes:
        id: Primary key
        conversation_id: Foreign key to the source conversation
        source_message_id: Foreign key to the message that triggered research
        research_type: Type of research (SCENARIO_ANALYSIS, DEEP_DIVE, etc.)
        query: User's research question
        parameters: Research parameters (symbols, timeframes, scenarios)
        status: Current status (PENDING, RUNNING, COMPLETED, FAILED, CANCELLED)
        result_insight_id: Foreign key to the resulting new DeepInsight
        error_message: Error message if research failed
        completed_at: Timestamp when research completed
    """

    __tablename__ = "follow_up_research"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("insight_conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    source_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("insight_conversation_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    research_type: Mapped[ResearchType] = mapped_column(
        Enum(ResearchType),
        nullable=False,
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[ResearchStatus] = mapped_column(
        Enum(ResearchStatus),
        default=ResearchStatus.PENDING,
        # Note: index is defined in __table_args__ as ix_follow_up_research_status
    )
    result_insight_id: Mapped[int | None] = mapped_column(
        ForeignKey("deep_insights.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Relationships
    conversation: Mapped["InsightConversation"] = relationship(
        back_populates="research_requests",
    )

    __table_args__ = (
        Index("ix_follow_up_research_status", "status"),
        Index("ix_follow_up_research_conv_status", "conversation_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<FollowUpResearch(id={self.id}, type={self.research_type!r}, "
            f"status={self.status!r})>"
        )
