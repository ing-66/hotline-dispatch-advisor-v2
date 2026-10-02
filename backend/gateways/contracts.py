from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generator


@dataclass(frozen=True)
class RetrievalResult:
    evidence_id: str
    knowledge_base_id: str
    external_id: str | None
    document_id: str | None
    document_title: str | None
    point_id: str | None
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisResult:
    recommended_department: str
    conclusion: str
    citation_references: list[str]
    competent_authority: str | None = None
    collaborating_units: list[str] = field(default_factory=list)
    decision_status: str = "needs_fact_check"
    missing_facts: list[str] = field(default_factory=list)
    evidence_items: list[dict[str, str]] = field(default_factory=list)
    responsibility_boundary: str | None = None
    confidence: float | None = None
    risk_warning: str | None = None


class KnowledgeGateway(ABC):
    @abstractmethod
    def search(self, query: str, knowledge_base_ids: list[str], top_k: int = 12,
               filters: dict[str, Any] | None = None) -> list[RetrievalResult]: ...


class LLMGateway(ABC):
    @abstractmethod
    def analyze(self, work_order: dict[str, Any], evidence: list[RetrievalResult],
                prompt_version: str) -> AnalysisResult: ...

    def analyze_stream(self, work_order: dict[str, Any], evidence: list[RetrievalResult],
                       prompt_version: str) -> Generator[str, None, AnalysisResult]:
        raise NotImplementedError


class KnowledgePublisher(ABC):
    @abstractmethod
    def upsert_case(self, work_order_id: str, case_payload: dict[str, Any]) -> None: ...

    @abstractmethod
    def delete_case(self, work_order_id: str) -> None: ...
