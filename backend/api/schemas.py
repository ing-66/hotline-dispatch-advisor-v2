"""Unified HTTP request/response schemas for the Business API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int


class WorkOrderCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1)
    request_type: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=500)
    source: str | None = Field(default=None, max_length=100)
    event_time: datetime | None = None
    status: str | None = Field(default=None, max_length=30)


class WorkOrderUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    content: str | None = Field(default=None, min_length=1)
    request_type: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=500)
    source: str | None = Field(default=None, max_length=100)
    event_time: datetime | None = None
    status: str | None = Field(default=None, max_length=30)


class WorkOrderResponse(ORMModel):
    id: str
    source_case_id: str | None
    title: str
    content: str
    request_type: str | None
    address: str | None
    source: str | None
    event_time: datetime | None
    actual_department_id: str | None
    status: str
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AnalysisCreate(BaseModel):
    knowledge_base_ids: list[str] | None = Field(
        default=None,
        description="知识库范围，缺省为四类全部：department_duties/responsibilities/regulations/historical_cases",
    )
    prompt_version: str = "v2-dify-style"


class AnalysisResponse(ORMModel):
    id: str
    work_order_id: str
    conversation_id: str | None
    trigger_message_id: str | None
    model_provider: str
    model_name: str
    prompt_version: str
    retrieval_version: str
    primary_department_id: str | None
    recommended_department_text: str | None
    recommended_departments_json: list[Any]
    conclusion: str
    responsibility_boundary: str | None
    confidence: float | None
    risk_warning: str | None
    evidence_summary: str | None
    input_snapshot_json: dict[str, Any]
    raw_output_json: dict[str, Any]
    created_at: datetime


class CitationResponse(ORMModel):
    id: str
    analysis_id: str
    knowledge_base_id: str | None
    evidence_id: str
    document_id: str | None
    document_title: str | None
    external_id: str | None
    point_id: str | None
    content_snapshot: str
    citation_type: str
    score: float | None
    metadata: dict[str, Any]
    created_at: datetime


class FeedbackCreate(BaseModel):
    feedback_type: str = Field(min_length=1, max_length=50)
    adopted: bool | None = None
    final_department_id: str | None = None
    comment: str | None = None


class FeedbackResponse(ORMModel):
    id: str
    analysis_id: str
    user_id: str | None
    feedback_type: str
    adopted: bool | None
    final_department_id: str | None
    comment: str | None
    created_at: datetime


class SavedCaseCreate(BaseModel):
    work_order_id: str
    analysis_id: str | None = None
    user_id: str | None = None
    case_type: str = "typical"
    note: str | None = None


class SavedCaseResponse(ORMModel):
    id: str
    work_order_id: str
    analysis_id: str | None
    user_id: str | None
    case_type: str
    note: str | None
    created_at: datetime


class ConversationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    status: str | None = Field(default=None, max_length=30)


class ConversationResponse(ORMModel):
    id: str
    user_id: str | None
    title: str
    status: str
    created_at: datetime


class MessageCreate(BaseModel):
    role: str = Field(min_length=1, max_length=20)
    content: str = Field(min_length=1)


class MessageResponse(ORMModel):
    id: str
    conversation_id: str
    role: str
    content: str
    model_name: str | None
    analysis_id: str | None
    metadata_json: dict[str, Any]
    created_at: datetime
