from datetime import datetime
from pydantic import BaseModel, ConfigDict


class InsightBase(BaseModel):
    insight_type: str
    title: str
    description: str
    severity: str
    confidence: float


class InsightResponse(InsightBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    stock_id: int | None
    is_active: bool
    created_at: datetime
    expires_at: datetime | None


class InsightListResponse(BaseModel):
    insights: list[InsightResponse]
    total: int


class AnnotationCreate(BaseModel):
    note: str


class AnnotationUpdate(BaseModel):
    note: str


class AnnotationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    insight_id: int
    note: str
    created_at: datetime
    updated_at: datetime | None = None
