"""Unit tests for the OpenAI-compatible real LLM adapter (no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from backend.gateways.contracts import RetrievalResult
from backend.gateways.real_llm import (
    LLMAuthenticationError,
    LLMQuotaError,
    LLMRateLimitError,
    LLMResponseError,
    LLMServerError,
    LLMTimeoutError,
    LLMValidationError,
    OpenAICompatibleLLMAdapter,
)


def evidence(eid: str = "hc:evidence-1") -> RetrievalResult:
    return RetrievalResult(
        evidence_id=eid,
        knowledge_base_id="historical_cases",
        external_id="HC-x",
        document_id="doc-1",
        document_title="历史案例",
        point_id="point-1",
        content="某部门曾处理类似事项。",
        score=0.9,
        metadata={"source_type": "historical_case", "source_case_id": "HC-x"},
    )


def valid_payload_json(overrides: dict | None = None) -> str:
    value = {
        "recommended_department": "白云区住房建设和交通局",
        "conclusion": "依据现有证据，建议由区住建部门处理。",
        "citation_references": ["hc:evidence-1"],
        "responsibility_boundary": "涉及电梯安全，市场监管部门协同。",
        "confidence": 0.86,
        "risk_warning": "建议联系物业核实。",
    }
    if overrides:
        value.update(overrides)
    return json.dumps(value, ensure_ascii=False)


def make_adapter(handler) -> OpenAICompatibleLLMAdapter:
    transport = httpx.MockTransport(handler)
    return OpenAICompatibleLLMAdapter(
        base_url="https://example.invalid",
        api_key="test-key",
        model="test-model",
        client=httpx.Client(transport=transport, timeout=10.0),
    )


def test_parses_valid_json_and_maps_fields():
    adapter = make_adapter(lambda request: httpx.Response(200, json={
        "choices": [{"message": {"content": valid_payload_json()}}],
    }))
    result = adapter.analyze({"title": "t", "content": "c"}, [evidence()], "v1")
    assert result.recommended_department == "白云区住房建设和交通局"
    assert result.citation_references == ["hc:evidence-1"]
    assert result.confidence == pytest.approx(0.60)
    assert result.decision_status == "needs_fact_check"
    assert any("历史同类受理记录" in fact for fact in result.missing_facts)
    assert result.responsibility_boundary


def test_strips_markdown_code_fence():
    content = f"```json\n{valid_payload_json()}\n```"
    adapter = make_adapter(lambda request: httpx.Response(200, json={
        "choices": [{"message": {"content": content}}],
    }))
    result = adapter.analyze({"content": "c"}, [evidence()], "v1")
    assert result.recommended_department == "白云区住房建设和交通局"


def test_rejects_invalid_json():
    adapter = make_adapter(lambda request: httpx.Response(200, json={
        "choices": [{"message": {"content": "不是 JSON"}}],
    }))
    with pytest.raises(LLMResponseError):
        adapter.analyze({"content": "c"}, [evidence()], "v1")


def test_rejects_missing_required_field():
    content = valid_payload_json({"conclusion": None})
    adapter = make_adapter(lambda request: httpx.Response(200, json={
        "choices": [{"message": {"content": content}}],
    }))
    with pytest.raises(LLMValidationError):
        adapter.analyze({"content": "c"}, [evidence()], "v1")


def test_rejects_unknown_evidence_id():
    content = valid_payload_json({"citation_references": ["hc:made-up"]})
    adapter = make_adapter(lambda request: httpx.Response(200, json={
        "choices": [{"message": {"content": content}}],
    }))
    with pytest.raises(LLMValidationError, match="hc:made-up"):
        adapter.analyze({"content": "c"}, [evidence()], "v1")


def test_rejects_empty_content():
    adapter = make_adapter(lambda request: httpx.Response(200, json={
        "choices": [{"message": {"content": "   "}}],
    }))
    with pytest.raises(LLMResponseError):
        adapter.analyze({"content": "c"}, [evidence()], "v1")


@pytest.mark.parametrize("status,error_type", [
    (401, LLMAuthenticationError),
    (403, LLMAuthenticationError),
    (402, LLMQuotaError),
    (429, LLMRateLimitError),
    (502, LLMServerError),
])
def test_maps_http_errors(status, error_type):
    adapter = make_adapter(lambda request, s=status: httpx.Response(s, json={"error": "x"}))
    with pytest.raises(error_type):
        adapter.analyze({"content": "c"}, [evidence()], "v1")


def test_maps_timeout():
    def handler(request):
        raise httpx.ReadTimeout("timeout")

    adapter = make_adapter(handler)
    with pytest.raises(LLMTimeoutError):
        adapter.analyze({"content": "c"}, [evidence()], "v1")
