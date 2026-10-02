import httpx
import pytest

from backend.gateways.qdrant_adapter import (
    KnowledgeAuthenticationError,
    KnowledgeCollectionError,
    KnowledgeConnectionError,
    KnowledgeResponseError,
    KnowledgeTimeoutError,
    QdrantKnowledgeAdapter,
)


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_adapter_normalizes_missing_metadata_and_empty_records():
    def handler(request):
        return httpx.Response(200, json={"records": [
            {"content": "依据", "score": "0.8", "title": "政策"},
            {"content": "", "metadata": None},
            "invalid",
        ]})
    result = QdrantKnowledgeAdapter("http://kb", "key", "collection", client=client(handler)).search("物业", ["department_duties"])
    assert len(result) == 1
    assert result[0].metadata["source_type"] == "department_duty"
    assert result[0].content == "依据"


def test_adapter_uses_one_batch_request_for_multiple_categories():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        assert request.url.path == "/retrieval/batch"
        return httpx.Response(200, json={"records_by_category": {
            "机构职责（知识源顶层 01）": [{"content": "职责依据", "score": 0.9}],
            "权责清单（知识源顶层 02）": [{"content": "权责依据", "score": 0.8}],
        }})

    result = QdrantKnowledgeAdapter("http://kb", "key", "collection", client=client(handler)).search(
        "物业", ["department_duties", "responsibilities"]
    )
    assert calls == ["/retrieval/batch"]
    assert {item.knowledge_base_id for item in result} == {"department_duties", "responsibilities"}


def test_adapter_handles_empty_results():
    adapter = QdrantKnowledgeAdapter("http://kb", "key", "collection", client=client(lambda _: httpx.Response(200, json={"records": []})))
    assert adapter.search("物业", ["department_duties"]) == []


@pytest.mark.parametrize("status,error", [(401, KnowledgeAuthenticationError), (404, KnowledgeCollectionError)])
def test_adapter_maps_http_errors(status, error):
    adapter = QdrantKnowledgeAdapter("http://kb", "key", "collection", client=client(lambda _: httpx.Response(status)))
    with pytest.raises(error): adapter.search("物业", ["department_duties"])


def test_adapter_maps_timeout():
    def handler(request): raise httpx.ReadTimeout("timeout", request=request)
    adapter = QdrantKnowledgeAdapter("http://kb", "key", "collection", client=client(handler))
    with pytest.raises(KnowledgeTimeoutError): adapter.search("物业", ["department_duties"])

def test_adapter_maps_connection_failure():
    def handler(request): raise httpx.ConnectError("unreachable", request=request)
    adapter = QdrantKnowledgeAdapter("http://kb", "key", "collection", client=client(handler))
    with pytest.raises(KnowledgeConnectionError): adapter.search("物业", ["department_duties"])


def test_adapter_rejects_malformed_response():
    adapter = QdrantKnowledgeAdapter("http://kb", "key", "collection", client=client(lambda _: httpx.Response(200, json={"records": {}})))
    with pytest.raises(KnowledgeResponseError): adapter.search("物业", ["department_duties"])


def test_health_detects_collection_mismatch():
    payload = {"collection": "wrong", "qdrant": {"ok": True}}
    adapter = QdrantKnowledgeAdapter("http://kb", "key", "expected", client=client(lambda _: httpx.Response(200, json=payload)))
    with pytest.raises(KnowledgeCollectionError): adapter.health()
