"""Pydantic schemas for follow-up research API routes."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ResearchTypeEnum(str, Enum):
    """Research type filter values (mirrors models.insight_conversation.ResearchType)."""

    SCENARIO_ANALYSIS = "SCENARIO_ANALYSIS"
    DEEP_DIVE = "DEEP_DIVE"
    CORRELATION_CHECK = "CORRELATION_CHECK"
    WHAT_IF = "WHAT_IF"


class ResearchStatusEnum(str, Enum):
    """Research status filter values (mirrors models.insight_conversation.ResearchStatus)."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ResearchResponse(BaseModel):
    """Response schema for a single follow-up research record."""

    id: int = Field(description="Primary key")
    conversation_id: int = Field(description="Source conversation ID")
    research_type: str = Field(description="Type of research performed")
    query: str = Field(description="User's research question")
    parameters: Optional[dict] = Field(default=None, description="Research parameters")
    status: str = Field(description="Current status (PENDING, RUNNING, COMPLETED, FAILED, CANCELLED)")
    result_insight_id: Optional[int] = Field(default=None, description="ID of the resulting DeepInsight")
    error_message: Optional[str] = Field(default=None, description="Error message if research failed")
    completed_at: Optional[datetime] = Field(default=None, description="Timestamp when research completed")
    created_at: datetime = Field(description="Record creation timestamp")
    updated_at: Optional[datetime] = Field(default=None, description="Last update timestamp")

    # Joined summary fields from related DeepInsights
    parent_insight_summary: Optional[str] = Field(
        default=None,
        description="Title of the parent insight (from parameters.parent_insight_id)",
    )
    result_insight_summary: Optional[str] = Field(
        default=None,
        description="Title of the resulting insight",
    )

    model_config = {"from_attributes": True}


class ResearchListResponse(BaseModel):
    """Paginated list response for follow-up research records."""

    items: list[ResearchResponse]
    total: int = Field(description="Total number of matching records")


class ResearchCreateRequest(BaseModel):
    """Request schema for creating a new follow-up research."""

    parent_insight_id: Optional[int] = Field(
        default=None,
        description="ID of the parent DeepInsight to research further",
    )
    research_type: ResearchTypeEnum = Field(
        default=ResearchTypeEnum.DEEP_DIVE,
        description="Type of research to perform",
    )
    query: str = Field(
        description="Research question or topic",
        min_length=1,
        max_length=2000,
    )
    symbols: list[str] = Field(
        default_factory=list,
        description="Stock symbols to focus on (e.g., ['AAPL', 'MSFT'])",
    )
    questions: list[str] = Field(
        default_factory=list,
        description="Specific questions to address in the research",
    )
