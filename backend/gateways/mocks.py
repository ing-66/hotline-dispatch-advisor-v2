from typing import Any

from backend.gateways.contracts import (
    AnalysisResult,
    KnowledgeGateway,
    KnowledgePublisher,
    LLMGateway,
    RetrievalResult,
)


class MockKnowledgeGateway(KnowledgeGateway):
    def __init__(self, results: list[RetrievalResult] | None = None):
        self.results = results or []

    def search(self, query: str, knowledge_base_ids: list[str], top_k: int = 8,
               filters: dict[str, Any] | None = None) -> list[RetrievalResult]:
        allowed = set(knowledge_base_ids)
        return [r for r in self.results if r.knowledge_base_id in allowed][:top_k]


class MockLLMGateway(LLMGateway):
    def __init__(self, result: AnalysisResult | None = None):
        self.provider = "mock"
        self.model_name = "mock-model"
        self.result = result or AnalysisResult(
            recommended_department="待人工研判",
            conclusion="Mock 研判结果",
            citation_references=[],
            confidence=0.5,
        )

    def analyze(self, work_order: dict[str, Any], evidence: list[RetrievalResult],
                prompt_version: str) -> AnalysisResult:
        return self.result

    def analyze_stream(self, work_order: dict[str, Any], evidence: list[RetrievalResult],
                       prompt_version: str):
        yield '{"recommended_department":"待人工研判"}'
        return self.result


class MockKnowledgePublisher(KnowledgePublisher):
    def __init__(self):
        self.cases: dict[str, dict[str, Any]] = {}

    def upsert_case(self, work_order_id: str, case_payload: dict[str, Any]) -> None:
        self.cases[work_order_id] = case_payload

    def delete_case(self, work_order_id: str) -> None:
        self.cases.pop(work_order_id, None)
