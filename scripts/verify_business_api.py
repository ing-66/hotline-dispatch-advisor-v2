"""Real HTTP business-loop verification against a running Business API.

Requires MySQL/Qdrant/Knowledge API running and the Business API started in
real-LLM mode:

    $env:LLM_GATEWAY_MODE = "real"
    uvicorn backend.main:app --host 127.0.0.1 --port 8000

The script then walks the complete HTTP loop:
    create work order -> real analysis -> list/detail/citations
    -> historical_case back to original work order -> feedback -> saved case

Synthetic rows are removed afterwards via the database; report JSON keeps results.

Usage:
    python scripts/verify_business_api.py [--base http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx

from backend.db.session import SessionLocal
from backend.domain.models import (
    AnalysisRecord, AnswerCitation, Conversation, Feedback, Message, SavedCase, WorkOrder,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--out", default=r"D:\热线派单系统V2-data\api\verify_business_api.json")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    report: dict[str, Any] = {}
    order_id = analysis_id = saved_case_id = None
    conversation_id = None
    try:
        with httpx.Client(base_url=base, timeout=300.0) as client:
            health = client.get("/api/health")
            assert health.status_code == 200
            report["health"] = health.json()

            content = (
                "市民反映临街商铺招牌脱落砸坏车辆，物业与商铺互相推诿，"
                "希望主管部门明确责任并协调赔偿。"
            )
            created = client.post("/api/work-orders", json={
                "title": "真实HTTP闭环验证-招牌脱落",
                "content": content,
                "request_type": "求助",
                "source": "HTTP闭环验证",
                "status": "new",
            })
            assert created.status_code == 201, created.text
            order = created.json()
            order_id = order["id"]

            analysis = client.post(f"/api/work-orders/{order_id}/analyses", json={})
            assert analysis.status_code == 201, analysis.text
            analysis_data = analysis.json()
            analysis_id = analysis_data["id"]
            assert analysis_data["model_provider"] != "mock"
            assert analysis_data["conclusion"]
            report["analysis"] = {
                "id": analysis_id,
                "provider": analysis_data["model_provider"],
                "model": analysis_data["model_name"],
                "recommended_department": analysis_data["recommended_department_text"],
                "confidence": analysis_data["confidence"],
            }
            print("HTTP real analysis PASS:", report["analysis"])

            history = client.get(f"/api/work-orders/{order_id}/analyses")
            assert history.status_code == 200 and history.json()["total"] >= 1
            detail = client.get(f"/api/analyses/{analysis_id}")
            assert detail.status_code == 200

            citations = client.get(f"/api/analyses/{analysis_id}/citations")
            assert citations.status_code == 200
            citation_list = citations.json()
            assert citation_list, "no citations"
            linked = [c for c in citation_list if c["metadata"].get("work_order_id")]
            assert linked, "no historical_case citation to trace"
            target = linked[0]["metadata"]
            original = client.get(f"/api/work-orders/{target['work_order_id']}")
            assert original.status_code == 200
            assert original.json()["source_case_id"] == target["source_case_id"]
            report["historical_trace"] = {
                "work_order_id": target["work_order_id"],
                "source_case_id": target["source_case_id"],
                "title": original.json()["title"],
            }
            print("HTTP historical_case back-to-work_order PASS")

            feedback = client.post(f"/api/analyses/{analysis_id}/feedback", json={
                "feedback_type": "correct_department",
                "adopted": False,
                "comment": "HTTP闭环验证反馈",
            })
            assert feedback.status_code == 201
            feedback_list = client.get(f"/api/analyses/{analysis_id}/feedback")
            assert feedback_list.status_code == 200 and len(feedback_list.json()) == 1
            report["feedback"] = feedback.json()
            print("HTTP feedback PASS")

            saved = client.post("/api/saved-cases", json={
                "work_order_id": order_id,
                "analysis_id": analysis_id,
                "case_type": "typical",
                "note": "HTTP闭环验证收藏",
            })
            assert saved.status_code == 201, saved.text
            saved_case_id = saved.json()["id"]
            saved_list = client.get("/api/saved-cases")
            assert saved_list.status_code == 200 and saved_list.json()["total"] >= 1
            removed = client.delete(f"/api/saved-cases/{saved_case_id}")
            assert removed.status_code == 204
            report["saved_case"] = "PASS"
            print("HTTP saved-case PASS")

            conversation = client.post("/api/conversations", json={"title": "HTTP闭环验证会话"})
            assert conversation.status_code == 201
            conversation_id = conversation.json()["id"]
            message = client.post(f"/api/conversations/{conversation_id}/messages",
                                  json={"role": "user", "content": "你好"})
            assert message.status_code == 201
            messages = client.get(f"/api/conversations/{conversation_id}/messages")
            assert messages.status_code == 200 and len(messages.json()) == 1
            report["conversation"] = "PASS"
            print("HTTP conversation/message PASS")
            report["status"] = "PASS"
    finally:
        db = SessionLocal()
        try:
            if saved_case_id:
                db.query(SavedCase).filter(SavedCase.id == saved_case_id).delete()
            if analysis_id:
                db.query(AnswerCitation).filter(AnswerCitation.analysis_id == analysis_id).delete()
                db.query(Feedback).filter(Feedback.analysis_id == analysis_id).delete()
                db.query(Message).filter(Message.analysis_id == analysis_id).update({Message.analysis_id: None})
                db.query(AnalysisRecord).filter(AnalysisRecord.id == analysis_id).delete()
            if conversation_id:
                db.query(Message).filter(Message.conversation_id == conversation_id).delete()
                db.query(Conversation).filter(Conversation.id == conversation_id).delete()
            if order_id:
                db.query(WorkOrder).filter(WorkOrder.id == order_id).delete()
            db.commit()
        finally:
            db.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report written: {out}")
    if report.get("status") != "PASS":
        raise SystemExit("HTTP business loop verification failed")


if __name__ == "__main__":
    main()
