"""HTTP API tests with mock gateways (no real model/network)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.routes import get_knowledge_gateway, get_llm_gateway
from backend.db.base import Base
from backend.db.session import get_db
from backend.domain import models  # noqa: F401
from backend.gateways.contracts import AnalysisResult, RetrievalResult
from backend.gateways.mocks import MockKnowledgeGateway, MockLLMGateway
from backend.gateways.qdrant_adapter import KnowledgeGatewayError
from backend.gateways.real_llm import LLMGatewayError
from backend.main import app


def sample_evidence() -> RetrievalResult:
    return RetrievalResult("e-1", "regulations", "ext-1", "doc-1", "物业条例",
                           "point-1", "法规快照内容", 0.9,
                           {"work_order_id": "hist-1", "source_case_id": "HC-x"})


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    session = testing_session()

    def override_db():
        yield session
        session.rollback()
        session.close()

    def override_knowledge():
        return MockKnowledgeGateway([sample_evidence()])

    def override_llm():
        return MockLLMGateway(AnalysisResult("住建部门", "有依据结论", ["e-1"], confidence=0.9))

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_knowledge_gateway] = override_knowledge
    app.dependency_overrides[get_llm_gateway] = override_llm
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


def create_order(client, title="物业投诉", content="物业不作为", request_type="投诉"):
    response = client.post("/api/work-orders", json={
        "title": title, "content": content, "request_type": request_type,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_work_order_crud_pagination_and_soft_delete(client):
    first = create_order(client, "物业投诉")
    second = create_order(client, "欠薪投诉")

    listed = client.get("/api/work-orders", params={"page": 1, "page_size": 1}).json()
    assert listed["total"] == 2 and len(listed["items"]) == 1
    assert listed["page"] == 1 and listed["page_size"] == 1

    detail = client.get(f"/api/work-orders/{first['id']}")
    assert detail.status_code == 200 and detail.json()["content"] == "物业不作为"

    filtered = client.get("/api/work-orders", params={"keyword": "欠薪"}).json()
    assert filtered["total"] == 1

    updated = client.patch(f"/api/work-orders/{first['id']}", json={"title": "物业投诉（已改）"})
    assert updated.status_code == 200 and updated.json()["title"] == "物业投诉（已改）"

    deleted = client.delete(f"/api/work-orders/{first['id']}")
    assert deleted.status_code == 204
    after = client.get("/api/work-orders").json()
    assert after["total"] == 1
    assert client.get(f"/api/work-orders/{second['id']}").status_code == 200
    assert client.get("/api/work-orders/not-exist").status_code == 404


def test_work_order_validation_422(client):
    response = client.post("/api/work-orders", json={"title": ""})
    assert response.status_code == 422


def test_analysis_create_list_detail_and_citations(client):
    order = create_order(client)
    first = client.post(f"/api/work-orders/{order['id']}/analyses",
                        json={"knowledge_base_ids": ["regulations"]})
    assert first.status_code == 201, first.text
    assert first.json()["model_provider"] == "mock"
    second = client.post(f"/api/work-orders/{order['id']}/analyses",
                         json={"knowledge_base_ids": ["regulations"]})
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]

    history = client.get(f"/api/work-orders/{order['id']}/analyses").json()
    assert history["total"] == 2
    detail = client.get(f"/api/analyses/{first.json()['id']}")
    assert detail.status_code == 200
    citations = client.get(f"/api/analyses/{first.json()['id']}/citations")
    assert citations.status_code == 200
    assert citations.json()[0]["metadata"]["work_order_id"] == "hist-1"
    assert client.get("/api/analyses/not-exist").status_code == 404


def test_analysis_stream_emits_real_fields_and_persists(client):
    order = create_order(client)
    with client.stream(
        "POST", f"/api/work-orders/{order['id']}/analyses/stream",
        json={"knowledge_base_ids": ["regulations"]},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert '"phase": "retrieving"' in body
    assert '"type": "field"' in body
    assert '"field": "recommended_department"' in body
    assert '"type": "done"' in body
    history = client.get(f"/api/work-orders/{order['id']}/analyses").json()
    assert history["total"] == 1


def test_analysis_rejects_unknown_evidence_400(client):
    app.dependency_overrides[get_llm_gateway] = lambda: MockLLMGateway(
        AnalysisResult("部门", "错误引用", ["missing"]))
    order = create_order(client)
    response = client.post(f"/api/work-orders/{order['id']}/analyses",
                           json={"knowledge_base_ids": ["regulations"]})
    assert response.status_code == 400


def test_feedback_create_and_list(client):
    order = create_order(client)
    analysis = client.post(f"/api/work-orders/{order['id']}/analyses",
                           json={"knowledge_base_ids": ["regulations"]}).json()
    created = client.post(f"/api/analyses/{analysis['id']}/feedback", json={
        "feedback_type": "correct_department", "adopted": False,
        "final_department_id": None, "comment": "建议改派",
    })
    assert created.status_code == 201
    assert created.json()["comment"] == "建议改派"
    listed = client.get(f"/api/analyses/{analysis['id']}/feedback")
    assert listed.status_code == 200 and len(listed.json()) == 1
    assert client.post("/api/analyses/not-exist/feedback", json={
        "feedback_type": "adopt"}).status_code == 404


def test_saved_cases_flow(client):
    order = create_order(client)
    analysis = client.post(f"/api/work-orders/{order['id']}/analyses",
                           json={"knowledge_base_ids": ["regulations"]}).json()
    first = client.post("/api/saved-cases", json={
        "work_order_id": order["id"], "analysis_id": analysis["id"], "case_type": "typical",
    })
    assert first.status_code == 201
    duplicate = client.post("/api/saved-cases", json={
        "work_order_id": order["id"], "analysis_id": analysis["id"], "case_type": "typical",
    })
    assert duplicate.status_code == 409
    listed = client.get("/api/saved-cases").json()
    assert listed["total"] == 1
    assert client.delete(f"/api/saved-cases/{first.json()['id']}").status_code == 204
    assert client.delete(f"/api/saved-cases/{first.json()['id']}").status_code == 404


def test_conversation_and_message_flow(client):
    created = client.post("/api/conversations", json={"title": "会话一"})
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    listed = client.get("/api/conversations").json()
    assert listed["total"] == 1
    detail = client.get(f"/api/conversations/{conversation_id}")
    assert detail.status_code == 200

    message = client.post(f"/api/conversations/{conversation_id}/messages",
                          json={"role": "user", "content": "你好"})
    assert message.status_code == 201
    messages = client.get(f"/api/conversations/{conversation_id}/messages")
    assert len(messages.json()) == 1
    assert client.post("/api/conversations/not-exist/messages",
                       json={"role": "user", "content": "x"}).status_code == 404


def test_knowledge_gateway_error_maps_to_503(client):
    def broken():
        raise KnowledgeGatewayError("qdrant down")

    app.dependency_overrides[get_knowledge_gateway] = broken
    order = create_order(client)
    response = client.post(f"/api/work-orders/{order['id']}/analyses",
                           json={"knowledge_base_ids": ["regulations"]})
    assert response.status_code == 503
    assert response.json()["error"] == "knowledge_unavailable"


def test_llm_gateway_error_maps_to_503(client):
    def broken():
        raise LLMGatewayError("llm down")

    app.dependency_overrides[get_llm_gateway] = broken
    order = create_order(client)
    response = client.post(f"/api/work-orders/{order['id']}/analyses",
                           json={"knowledge_base_ids": ["regulations"]})
    assert response.status_code == 503
    assert response.json()["error"] == "llm_unavailable"


def test_openapi_and_docs_available(client):
    docs = client.get("/docs")
    assert docs.status_code == 200
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    assert "/api/work-orders" in paths
    assert "/api/analyses/{analysis_id}/citations" in paths


def test_readiness_checks_database(client):
    response = client.get("/api/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
