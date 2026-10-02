from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.domain.models import AnalysisRecord, Conversation, Department, Feedback, Message, SavedCase, WorkOrder


class WorkOrderRepository:
    def __init__(self, db: Session): self.db = db
    def add(self, item: WorkOrder) -> WorkOrder:
        self.db.add(item); self.db.flush(); return item
    def get(self, item_id: str) -> WorkOrder | None: return self.db.get(WorkOrder, item_id)
    def update(self, item: WorkOrder, **values) -> WorkOrder:
        for key, value in values.items(): setattr(item, key, value)
        self.db.flush(); return item
    def soft_delete(self, item: WorkOrder) -> WorkOrder:
        item.status = "deleted"; self.db.flush(); return item

    def list(self, *, page: int, page_size: int, status: str | None = None,
             request_type: str | None = None, department_id: str | None = None,
             keyword: str | None = None) -> tuple[list[WorkOrder], int]:
        filters = []
        if status is None:
            filters.append(WorkOrder.status != "deleted")
        else:
            filters.append(WorkOrder.status == status)
        if request_type:
            filters.append(WorkOrder.request_type == request_type)
        if department_id:
            filters.append(WorkOrder.actual_department_id == department_id)
        if keyword:
            like = f"%{keyword}%"
            filters.append(or_(WorkOrder.title.like(like), WorkOrder.content.like(like),
                               WorkOrder.source_case_id.like(like)))
        base = select(WorkOrder).where(*filters)
        total = int(self.db.scalar(select(func.count()).select_from(WorkOrder).where(*filters)) or 0)
        rows = list(self.db.scalars(base.order_by(WorkOrder.created_at.desc())
                                    .offset((page - 1) * page_size).limit(page_size)))
        return rows, total


class AnalysisRepository:
    def __init__(self, db: Session): self.db = db
    def add(self, item: AnalysisRecord) -> AnalysisRecord:
        self.db.add(item); self.db.flush(); return item
    def get(self, item_id: str) -> AnalysisRecord | None:
        return self.db.get(AnalysisRecord, item_id)
    def list_for_work_order(self, work_order_id: str, *, page: int | None = None,
                            page_size: int = 20) -> tuple[list[AnalysisRecord], int]:
        base = select(AnalysisRecord).where(AnalysisRecord.work_order_id == work_order_id)
        total = int(self.db.scalar(select(func.count()).select_from(AnalysisRecord)
                                   .where(AnalysisRecord.work_order_id == work_order_id)) or 0)
        query = base.order_by(AnalysisRecord.created_at.desc())
        if page is not None:
            query = query.offset((page - 1) * page_size).limit(page_size)
        return list(self.db.scalars(query)), total


class ConversationRepository:
    def __init__(self, db: Session): self.db = db
    def add(self, item: Conversation) -> Conversation:
        self.db.add(item); self.db.flush(); return item
    def add_message(self, item: Message) -> Message:
        self.db.add(item); self.db.flush(); return item
    def get(self, item_id: str) -> Conversation | None: return self.db.get(Conversation, item_id)
    def update(self, item: Conversation, **values) -> Conversation:
        for key, value in values.items():
            setattr(item, key, value)
        self.db.flush()
        return item
    def list(self, *, page: int, page_size: int) -> tuple[list[Conversation], int]:
        filters = [Conversation.status != "deleted"]
        total = int(self.db.scalar(select(func.count()).select_from(Conversation).where(*filters)) or 0)
        rows = list(self.db.scalars(select(Conversation).where(*filters).order_by(Conversation.created_at.desc())
                                    .offset((page - 1) * page_size).limit(page_size)))
        return rows, total
    def list_messages(self, conversation_id: str) -> list[Message]:
        return list(self.db.scalars(select(Message).where(Message.conversation_id == conversation_id)
                                    .order_by(Message.created_at.asc())))


class FeedbackRepository:
    def __init__(self, db: Session): self.db = db
    def add(self, item: Feedback) -> Feedback:
        self.db.add(item); self.db.flush(); return item
    def get(self, item_id: str) -> Feedback | None:
        return self.db.get(Feedback, item_id)
    def list_for_analysis(self, analysis_id: str) -> list[Feedback]:
        return list(self.db.scalars(select(Feedback).where(Feedback.analysis_id == analysis_id)
                                    .order_by(Feedback.created_at.asc())))


class SavedCaseRepository:
    def __init__(self, db: Session): self.db = db
    def add(self, item) -> object:
        self.db.add(item); self.db.flush(); return item
    def get(self, item_id: str):
        return self.db.get(SavedCase, item_id)
    def list(self, *, page: int, page_size: int) -> tuple[list, int]:
        total = int(self.db.scalar(select(func.count()).select_from(SavedCase)) or 0)
        rows = list(self.db.scalars(select(SavedCase).order_by(SavedCase.created_at.desc())
                                    .offset((page - 1) * page_size).limit(page_size)))
        return rows, total
    def delete(self, item) -> None:
        self.db.delete(item); self.db.flush()


class DepartmentRepository:
    def __init__(self, db: Session): self.db = db
    def get_by_name(self, name: str) -> Department | None:
        return self.db.scalar(select(Department).where(Department.name == name))
