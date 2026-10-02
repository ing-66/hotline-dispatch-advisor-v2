from __future__ import annotations

from collections import OrderedDict

from sqlalchemy.orm import Session

from backend.domain.models import AnswerCitation, AnalysisRecord, Conversation, Feedback, Message, SavedCase, WorkOrder
from backend.gateways.contracts import KnowledgeGateway, LLMGateway
from backend.services.analysis_context import build_case_context
from backend.repositories.core import (
    AnalysisRepository,
    ConversationRepository,
    FeedbackRepository,
    SavedCaseRepository,
    WorkOrderRepository,
)


class WorkOrderService:
    def __init__(self, db: Session): self.db, self.repo = db, WorkOrderRepository(db)
    def create(self, title: str, content: str, **values) -> WorkOrder:
        item = self.repo.add(WorkOrder(title=title, content=content, **values)); self.db.commit(); return item
    def get(self, item_id: str) -> WorkOrder | None:
        return self.repo.get(item_id)
    def update(self, item_id: str, **values) -> WorkOrder:
        item = self.repo.get(item_id)
        if item is None: raise LookupError("Work order not found")
        self.repo.update(item, **values); self.db.commit(); return item
    def soft_delete(self, item_id: str) -> WorkOrder:
        item = self.repo.get(item_id)
        if item is None: raise LookupError("Work order not found")
        self.repo.soft_delete(item); self.db.commit(); return item
    def list(self, **kwargs) -> tuple[list[WorkOrder], int]:
        return self.repo.list(**kwargs)


class ConversationService:
    def __init__(self, db: Session): self.db, self.repo = db, ConversationRepository(db)
    def create(self, title: str, user_id: str | None = None) -> Conversation:
        item = self.repo.add(Conversation(title=title, user_id=user_id)); self.db.commit(); return item
    def get(self, conversation_id: str) -> Conversation | None:
        return self.repo.get(conversation_id)
    def list(self, **kwargs) -> tuple[list[Conversation], int]:
        return self.repo.list(**kwargs)
    def update(self, conversation_id: str, **values) -> Conversation:
        item = self.repo.get(conversation_id)
        if item is None:
            raise LookupError("Conversation not found")
        self.repo.update(item, **values)
        self.db.commit()
        return item
    def add_message(self, conversation_id: str, role: str, content: str, **values) -> Message:
        item = self.repo.add_message(Message(conversation_id=conversation_id, role=role, content=content, **values)); self.db.commit(); return item
    def list_messages(self, conversation_id: str) -> list[Message]:
        return self.repo.list_messages(conversation_id)


class FeedbackService:
    def __init__(self, db: Session): self.db, self.repo = db, FeedbackRepository(db)
    def create(self, analysis_id: str, feedback_type: str, **values) -> Feedback:
        item = self.repo.add(Feedback(analysis_id=analysis_id, feedback_type=feedback_type, **values)); self.db.commit(); return item
    def get(self, feedback_id: str) -> Feedback | None:
        return self.repo.get(feedback_id)
    def list_for_analysis(self, analysis_id: str) -> list[Feedback]:
        return self.repo.list_for_analysis(analysis_id)


class SavedCaseService:
    def __init__(self, db: Session): self.db, self.repo = db, SavedCaseRepository(db)
    def create(self, work_order_id: str, **values) -> SavedCase:
        duplicate = self.db.query(SavedCase).filter_by(
            work_order_id=work_order_id,
            analysis_id=values.get("analysis_id"),
            user_id=values.get("user_id"),
        ).first()
        if duplicate is not None:
            raise ValueError("Duplicate saved case")
        item = SavedCase(work_order_id=work_order_id, **values)
        self.db.add(item)
        self.db.commit()
        return item
    def list(self, **kwargs) -> tuple[list[SavedCase], int]:
        return self.repo.list(**kwargs)
    def get(self, item_id: str) -> SavedCase | None:
        return self.repo.get(item_id)
    def delete(self, item_id: str) -> None:
        item = self.repo.get(item_id)
        if item is None:
            raise LookupError("Saved case not found")
        self.repo.delete(item); self.db.commit()


class AnalysisService:
    def __init__(self, db: Session, knowledge: KnowledgeGateway, llm: LLMGateway):
        self.db, self.repo, self.knowledge, self.llm = db, AnalysisRepository(db), knowledge, llm

    def analyze(self, work_order: WorkOrder, knowledge_base_ids: list[str], prompt_version: str = "v2-dify-style") -> AnalysisRecord:
        evidence = self.knowledge.search(work_order.content, knowledge_base_ids)
        analysis_context = build_case_context(work_order.content)
        result = self.llm.analyze({
            "id": work_order.id,
            "title": work_order.title,
            "content": work_order.content,
            **analysis_context,
        }, evidence, prompt_version)
        return self.persist(work_order, evidence, result, prompt_version)

    def persist(self, work_order: WorkOrder, evidence, result, prompt_version: str) -> AnalysisRecord:
        evidence_by_id = {item.evidence_id: item for item in evidence}
        unknown = set(result.citation_references) - evidence_by_id.keys()
        if unknown:
            raise ValueError(f"LLM returned unknown evidence IDs: {sorted(unknown)}")
        evidence_groups: OrderedDict[str, list[str]] = OrderedDict()
        for item in result.evidence_items:
            source_name = item.get("source") or "职责来源"
            quote = item.get("quote", "").strip()
            if quote.startswith("负责"):
                quote = quote[2:].lstrip()
            if quote and quote not in evidence_groups.setdefault(source_name, []):
                evidence_groups[source_name].append(quote)
        evidence_summary = "\n\n".join(
            f"“{source_name}”负责：\n\n" + "\n".join(f"- {quote}" for quote in quotes)
            for source_name, quotes in evidence_groups.items()
        ) or None

        record = self.repo.add(AnalysisRecord(
            work_order_id=work_order.id,
            model_provider=str(getattr(self.llm, "provider", "mock") or "mock"),
            model_name=str(getattr(self.llm, "model_name", "mock-model") or "mock-model"),
            prompt_version=prompt_version,
            recommended_department_text=result.recommended_department,
            recommended_departments_json=[
                {"role": "first_dispatch", "unit": result.recommended_department},
                {"role": "competent_authority", "unit": result.competent_authority or ""},
                *({"role": "collaborating", "unit": unit} for unit in result.collaborating_units),
                {"role": "decision_status", "value": result.decision_status},
                *({"role": "missing_fact", "value": fact} for fact in result.missing_facts),
            ],
            conclusion=result.conclusion, responsibility_boundary=result.responsibility_boundary,
            confidence=result.confidence, risk_warning=result.risk_warning,
            evidence_summary=evidence_summary,
            input_snapshot_json={"title": work_order.title, "content": work_order.content},
            raw_output_json={
                "citation_references": result.citation_references,
                "decision_status": result.decision_status,
                "missing_facts": result.missing_facts,
                "evidence": result.evidence_items,
            },
        ))
        for evidence_id in result.citation_references:
            item = evidence_by_id[evidence_id]
            self.db.add(AnswerCitation(
                analysis_id=record.id, evidence_id=item.evidence_id,
                document_id=item.document_id, document_title=item.document_title,
                external_id=item.external_id, point_id=item.point_id,
                content_snapshot=item.content, citation_type=item.knowledge_base_id,
                score=item.score, metadata_json=item.metadata,
            ))
        self.db.commit()
        return record
    def get(self, analysis_id: str) -> AnalysisRecord | None:
        return self.repo.get(analysis_id)
    def list_for_work_order(self, work_order_id: str, **kwargs) -> tuple[list[AnalysisRecord], int]:
        return self.repo.list_for_work_order(work_order_id, **kwargs)


class AnalysisQueryService:
    """Read-only analysis access; requires no LLM/Knowledge gateway."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = AnalysisRepository(db)

    def get(self, analysis_id: str) -> AnalysisRecord | None:
        return self.repo.get(analysis_id)

    def list_for_work_order(self, work_order_id: str, **kwargs) -> tuple[list[AnalysisRecord], int]:
        return self.repo.list_for_work_order(work_order_id, **kwargs)
