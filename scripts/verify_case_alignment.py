"""End-to-end verification of MySQL <-> Qdrant historical case alignment.

Checks:
  1. Qdrant -> MySQL: random linked points resolve to existing work_orders.
  2. MySQL -> Qdrant: random work_orders resolve to linked Qdrant points.
  3. RAG citation: real retrieval -> MockLLM -> analysis_records/answer_citations
     metadata carries work_order_id/source_case_id that resolves to the source
     historical work order.

Reads MySQL and Qdrant; creates and cleans one synthetic work order/analysis.

Usage:
    python scripts/verify_case_alignment.py [--sample 20] [--seed 42]
"""

from __future__ import annotations

import argparse
import random
import sys
from typing import Any

import httpx

from backend.db.session import SessionLocal
from backend.domain.models import (
    AnalysisRecord, AnswerCitation, Feedback, Message, SavedCase, WorkOrder,
)
from backend.gateways.contracts import AnalysisResult
from backend.gateways.factory import create_knowledge_gateway
from backend.gateways.mocks import MockLLMGateway
from backend.services.core import AnalysisService, WorkOrderService


QDRANT = "http://127.0.0.1:6333"
COLLECTION = "hotline_dispatch_v2"
CATEGORY = "历史工单案例（知识源顶层 03）"


def scroll_historical_points() -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    offset = None
    with httpx.Client(trust_env=False, timeout=120.0) as client:
        while True:
            body: dict[str, Any] = {
                "filter": {"must": [{"key": "category", "match": {"value": CATEGORY}}]},
                "limit": 1000,
                "with_payload": True,
                "with_vector": False,
            }
            if offset is not None:
                body["offset"] = offset
            response = client.post(f"{QDRANT}/collections/{COLLECTION}/points/scroll", json=body)
            response.raise_for_status()
            payload = response.json()
            batch = payload["result"]["points"]
            points.extend(batch)
            offset = payload["result"].get("next_page_offset")
            if offset is None:
                break
    return points


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    random.seed(args.seed)

    db = SessionLocal()
    synthetic_order_id = synthetic_analysis_id = None
    try:
        rows = db.query(WorkOrder).filter(WorkOrder.source_case_id.isnot(None)).all()
        by_id = {row.id: row for row in rows}
        assert len(rows) == 5143, f"expected 5143 historical work orders, got {len(rows)}"
        source_case_ids = {row.source_case_id for row in rows}
        assert len(source_case_ids) == len(rows), "source_case_id must be unique"

        points = scroll_historical_points()
        linked = [p for p in points if (p.get("payload") or {}).get("work_order_id")]
        print(f"qdrant historical points={len(points)} linked={len(linked)}")

        # Qdrant -> MySQL
        q2m_checked = 0
        for point in random.sample(linked, min(args.sample, len(linked))):
            payload = point["payload"]
            row = by_id.get(payload["work_order_id"])
            assert row is not None, f"missing mysql row for {payload['work_order_id']}"
            assert row.source_case_id == payload["source_case_id"], "source_case_id mismatch"
            assert row.title == (payload.get("section") or row.title), "section/title mismatch"
            q2m_checked += 1

        # MySQL -> Qdrant
        m2q_checked = 0
        linked_by_wo: dict[str, list[dict[str, Any]]] = {}
        for point in linked:
            linked_by_wo.setdefault(point["payload"]["work_order_id"], []).append(point)
        for row in random.sample(rows, min(args.sample, len(rows))):
            point_list = linked_by_wo.get(row.id, [])
            assert point_list, f"no qdrant point for work order {row.id}"
            assert all(p["payload"].get("source_case_id") == row.source_case_id for p in point_list)
            m2q_checked += 1

        # RAG citation trace
        gateway = create_knowledge_gateway()
        query = "市民反映住宅小区物业服务企业长期不履行管理责任，多次反映仍未处理公共区域环境卫生问题，希望主管部门督促整改。"
        evidence = gateway.search(query, ["historical_cases"], top_k=5)
        linked_evidence = [e for e in evidence if e.metadata.get("work_order_id")]
        assert linked_evidence, "no linked historical_case evidence returned"
        chosen = linked_evidence[0]
        expected_wo_id = chosen.metadata["work_order_id"]
        llm = MockLLMGateway(AnalysisResult("历史案例引用验证", "用于验证引用可回查原始工单。", [chosen.evidence_id], confidence=0.5))
        order = WorkOrderService(db).create("历史案例引用验证", query, metadata_json={"verification": "case-alignment"})
        synthetic_order_id = order.id
        analysis = AnalysisService(db, gateway, llm).analyze(order, ["historical_cases"])
        synthetic_analysis_id = analysis.id
        db.expire_all()
        citation = db.get(AnalysisRecord, analysis.id).citations[0]
        citation_wo_id = citation.metadata_json.get("work_order_id")
        citation_sc_id = citation.metadata_json.get("source_case_id")
        assert citation_wo_id == expected_wo_id, "citation work_order_id mismatch"
        target = by_id.get(citation_wo_id)
        assert target is not None and target.source_case_id == citation_sc_id
        print(f"Qdrant->MySQL checked={q2m_checked} PASS")
        print(f"MySQL->Qdrant checked={m2q_checked} PASS")
        print(f"RAG citation trace PASS: evidence -> work_order_id={citation_wo_id} source_case_id={citation_sc_id}")
        print(f"answer_citations metadata keys: {sorted(citation.metadata_json.keys())}")
    finally:
        if synthetic_analysis_id:
            db.query(AnswerCitation).filter(AnswerCitation.analysis_id == synthetic_analysis_id).delete()
            db.query(Feedback).filter(Feedback.analysis_id == synthetic_analysis_id).delete()
            db.query(Message).filter(Message.analysis_id == synthetic_analysis_id).update({Message.analysis_id: None})
            db.query(AnalysisRecord).filter(AnalysisRecord.id == synthetic_analysis_id).delete()
        if synthetic_order_id:
            db.query(SavedCase).filter(SavedCase.work_order_id == synthetic_order_id).delete()
            db.query(WorkOrder).filter(WorkOrder.id == synthetic_order_id).delete()
        db.commit()
        db.close()


if __name__ == "__main__":
    sys.exit(main())
