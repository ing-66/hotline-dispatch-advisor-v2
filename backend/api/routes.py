import json
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.api.schemas import (
    AnalysisCreate,
    AnalysisResponse,
    CitationResponse,
    ConversationCreate,
    ConversationUpdate,
    ConversationResponse,
    FeedbackCreate,
    FeedbackResponse,
    MessageCreate,
    MessageResponse,
    Page,
    SavedCaseCreate,
    SavedCaseResponse,
    WorkOrderCreate,
    WorkOrderResponse,
    WorkOrderUpdate,
)
from backend.db.session import get_db
from backend.gateways.contracts import KnowledgeGateway, LLMGateway
from backend.gateways.factory import create_knowledge_gateway, create_llm_gateway
from backend.services.analysis_context import build_case_context
from backend.services.core import (
    AnalysisQueryService,
    AnalysisService,
    ConversationService,
    FeedbackService,
    SavedCaseService,
    WorkOrderService,
)


router = APIRouter(prefix="/api")
ALL_KNOWLEDGE_IDS = ["department_duties", "responsibilities", "regulations", "historical_cases"]


def get_knowledge_gateway() -> KnowledgeGateway:
    return create_knowledge_gateway()


def get_llm_gateway() -> LLMGateway:
    return create_llm_gateway()


def page_of(items: list[Any], page: int, page_size: int, total: int) -> dict[str, Any]:
    return {"items": items, "page": page, "page_size": page_size, "total": total}


def citation_out(citation) -> CitationResponse:
    data = {key: getattr(citation, key) for key in (
        "id", "analysis_id", "knowledge_base_id", "evidence_id", "document_id",
        "document_title", "external_id", "point_id", "content_snapshot",
        "citation_type", "score", "created_at",
    )}
    data["metadata"] = citation.metadata_json or {}
    return CitationResponse(**data)


def work_order_service(db: Session) -> WorkOrderService:
    return WorkOrderService(db)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    """Readiness includes the persistence dependency; liveness intentionally does not."""
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


# ---------------------------------------------------------------------------
# Work orders
# ---------------------------------------------------------------------------

@router.post("/work-orders", status_code=status.HTTP_201_CREATED, response_model=WorkOrderResponse)
def create_work_order(payload: WorkOrderCreate, db: Session = Depends(get_db)):
    values = payload.model_dump(exclude_unset=True)
    item = WorkOrderService(db).create(values.pop("title"), values.pop("content"), **values)
    return WorkOrderResponse.model_validate(item)


@router.get("/work-orders", response_model=Page[WorkOrderResponse])
def list_work_orders(
    db: Session = Depends(get_db),
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: str | None = Query(default=None, alias="status"),
    request_type: str | None = None,
    department_id: str | None = None,
    keyword: str | None = None,
):
    items, total = WorkOrderService(db).list(
        page=page, page_size=page_size, status=status_filter,
        request_type=request_type, department_id=department_id, keyword=keyword,
    )
    return page_of([WorkOrderResponse.model_validate(i) for i in items], page, page_size, total)


@router.get("/work-orders/{work_order_id}", response_model=WorkOrderResponse)
def get_work_order(work_order_id: str, db: Session = Depends(get_db)):
    item = WorkOrderService(db).get(work_order_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work order not found")
    return WorkOrderResponse.model_validate(item)


@router.patch("/work-orders/{work_order_id}", response_model=WorkOrderResponse)
def update_work_order(work_order_id: str, payload: WorkOrderUpdate, db: Session = Depends(get_db)):
    values = payload.model_dump(exclude_unset=True)
    try:
        item = WorkOrderService(db).update(work_order_id, **values)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work order not found")
    return WorkOrderResponse.model_validate(item)


@router.delete("/work-orders/{work_order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_work_order(work_order_id: str, db: Session = Depends(get_db)):
    try:
        WorkOrderService(db).soft_delete(work_order_id)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work order not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# AI analyses
# ---------------------------------------------------------------------------

@router.post("/work-orders/{work_order_id}/analyses",
             status_code=status.HTTP_201_CREATED, response_model=AnalysisResponse)
def create_analysis(
    work_order_id: str,
    payload: AnalysisCreate,
    db: Session = Depends(get_db),
    knowledge: KnowledgeGateway = Depends(get_knowledge_gateway),
    llm: LLMGateway = Depends(get_llm_gateway),
):
    order = WorkOrderService(db).get(work_order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work order not found")
    if order.status == "deleted":
        raise HTTPException(status.HTTP_409_CONFLICT, "Deleted work order cannot be analyzed")
    ids = payload.knowledge_base_ids or ALL_KNOWLEDGE_IDS
    try:
        item = AnalysisService(db, knowledge, llm).analyze(order, ids, payload.prompt_version)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return AnalysisResponse.model_validate(item)


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _completed_json_fields(raw: str, emitted: set[str]) -> list[tuple[str, Any]]:
    decoder = json.JSONDecoder()
    completed = []
    for match in re.finditer(r'"([a-z_]+)"\s*:\s*', raw):
        key = match.group(1)
        if key in emitted:
            continue
        try:
            value, end = decoder.raw_decode(raw, match.end())
        except json.JSONDecodeError:
            continue
        remainder = raw[end:].lstrip()
        if not remainder or remainder[0] not in ",}":
            continue
        emitted.add(key)
        completed.append((key, value))
    return completed


@router.post("/work-orders/{work_order_id}/analyses/stream")
def stream_analysis(
    work_order_id: str,
    payload: AnalysisCreate,
    db: Session = Depends(get_db),
    knowledge: KnowledgeGateway = Depends(get_knowledge_gateway),
    llm: LLMGateway = Depends(get_llm_gateway),
):
    order = WorkOrderService(db).get(work_order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work order not found")
    if order.status == "deleted":
        raise HTTPException(status.HTTP_409_CONFLICT, "Deleted work order cannot be analyzed")
    ids = payload.knowledge_base_ids or ALL_KNOWLEDGE_IDS

    def events():
        try:
            yield _sse({"type": "phase", "phase": "retrieving", "message": "正在检索职责依据…"})
            evidence = knowledge.search(order.content, ids)
            yield _sse({"type": "phase", "phase": "generating", "message": "正在生成研判意见…"})
            context = build_case_context(order.content)
            stream = llm.analyze_stream({
                "id": order.id, "title": order.title, "content": order.content, **context,
            }, evidence, payload.prompt_version)
            raw = ""
            emitted: set[str] = set()
            while True:
                try:
                    chunk = next(stream)
                except StopIteration as stop:
                    result = stop.value
                    break
                raw += chunk
                for field, value in _completed_json_fields(raw, emitted):
                    yield _sse({"type": "field", "field": field, "value": value})
            record = AnalysisService(db, knowledge, llm).persist(order, evidence, result, payload.prompt_version)
            analysis = AnalysisResponse.model_validate(record)
            citations = [citation_out(citation) for citation in sorted(record.citations, key=lambda item: item.created_at)]
            yield _sse({
                "type": "done",
                "analysis": analysis.model_dump(mode="json"),
                "citations": [citation.model_dump(mode="json") for citation in citations],
            })
        except Exception as exc:  # errors after response headers must travel inside the stream
            db.rollback()
            yield _sse({"type": "error", "message": str(exc) or type(exc).__name__})

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


@router.get("/work-orders/{work_order_id}/analyses", response_model=Page[AnalysisResponse])
def list_analyses(
    work_order_id: str,
    db: Session = Depends(get_db),
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    order = WorkOrderService(db).get(work_order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work order not found")
    items, total = AnalysisQueryService(db).list_for_work_order(
        work_order_id, page=page, page_size=page_size)
    return page_of([AnalysisResponse.model_validate(i) for i in items], page, page_size, total)


@router.get("/analyses/{analysis_id}", response_model=AnalysisResponse)
def get_analysis(analysis_id: str, db: Session = Depends(get_db)):
    item = AnalysisQueryService(db).get(analysis_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")
    return AnalysisResponse.model_validate(item)


@router.get("/analyses/{analysis_id}/citations", response_model=list[CitationResponse])
def list_citations(analysis_id: str, db: Session = Depends(get_db)):
    item = AnalysisQueryService(db).get(analysis_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")
    return [citation_out(c) for c in sorted(item.citations, key=lambda x: x.created_at)]


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

@router.post("/analyses/{analysis_id}/feedback",
             status_code=status.HTTP_201_CREATED, response_model=FeedbackResponse)
def create_feedback(analysis_id: str, payload: FeedbackCreate, db: Session = Depends(get_db)):
    analysis = AnalysisQueryService(db).get(analysis_id)
    if analysis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")
    item = FeedbackService(db).create(analysis_id, payload.feedback_type,
                                      adopted=payload.adopted,
                                      final_department_id=payload.final_department_id,
                                      comment=payload.comment)
    return FeedbackResponse.model_validate(item)


@router.get("/analyses/{analysis_id}/feedback", response_model=list[FeedbackResponse])
def list_feedback(analysis_id: str, db: Session = Depends(get_db)):
    if AnalysisQueryService(db).get(analysis_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")
    return [FeedbackResponse.model_validate(f) for f in FeedbackService(db).list_for_analysis(analysis_id)]


# ---------------------------------------------------------------------------
# Saved cases
# ---------------------------------------------------------------------------

@router.post("/saved-cases", status_code=status.HTTP_201_CREATED, response_model=SavedCaseResponse)
def create_saved_case(payload: SavedCaseCreate, db: Session = Depends(get_db)):
    if WorkOrderService(db).get(payload.work_order_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Work order not found")
    analysis = AnalysisQueryService(db).get(payload.analysis_id) if payload.analysis_id else None
    if payload.analysis_id and analysis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")
    if analysis is not None and analysis.work_order_id != payload.work_order_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Analysis does not belong to the work order")
    try:
        item = SavedCaseService(db).create(payload.work_order_id, analysis_id=payload.analysis_id,
                                           user_id=payload.user_id, case_type=payload.case_type,
                                           note=payload.note)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return SavedCaseResponse.model_validate(item)


@router.get("/saved-cases", response_model=Page[SavedCaseResponse])
def list_saved_cases(
    db: Session = Depends(get_db),
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    items, total = SavedCaseService(db).list(page=page, page_size=page_size)
    return page_of([SavedCaseResponse.model_validate(i) for i in items], page, page_size, total)


@router.delete("/saved-cases/{saved_case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_case(saved_case_id: str, db: Session = Depends(get_db)):
    try:
        SavedCaseService(db).delete(saved_case_id)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved case not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Conversations and messages
# ---------------------------------------------------------------------------

@router.post("/conversations", status_code=status.HTTP_201_CREATED, response_model=ConversationResponse)
def create_conversation(payload: ConversationCreate, db: Session = Depends(get_db)):
    item = ConversationService(db).create(payload.title)
    return ConversationResponse.model_validate(item)


@router.get("/conversations", response_model=Page[ConversationResponse])
def list_conversations(
    db: Session = Depends(get_db),
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    items, total = ConversationService(db).list(page=page, page_size=page_size)
    return page_of([ConversationResponse.model_validate(i) for i in items], page, page_size, total)


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
def update_conversation(conversation_id: str, payload: ConversationUpdate, db: Session = Depends(get_db)):
    values = payload.model_dump(exclude_unset=True)
    status_value = values.get("status")
    if status_value is not None and status_value not in {"active", "archived", "deleted"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid conversation status")
    try:
        item = ConversationService(db).update(conversation_id, **values)
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return ConversationResponse.model_validate(item)


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(conversation_id: str, db: Session = Depends(get_db)):
    item = ConversationService(db).get(conversation_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return ConversationResponse.model_validate(item)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
def list_messages(conversation_id: str, db: Session = Depends(get_db)):
    service = ConversationService(db)
    if service.get(conversation_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return [MessageResponse.model_validate(m) for m in service.list_messages(conversation_id)]


@router.post("/conversations/{conversation_id}/messages",
             status_code=status.HTTP_201_CREATED, response_model=MessageResponse)
def add_message(conversation_id: str, payload: MessageCreate, db: Session = Depends(get_db)):
    service = ConversationService(db)
    if service.get(conversation_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    item = service.add_message(conversation_id, payload.role, payload.content)
    return MessageResponse.model_validate(item)
