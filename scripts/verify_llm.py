"""Explicit real-LLM end-to-end verification.

Runs the complete chain with a REAL model (never Mock):
    work_order -> MySQL -> AnalysisService -> KnowledgeGateway -> Knowledge API
    -> Qdrant -> Evidence Pack -> RealLLMAdapter -> structured validation
    -> analysis_records -> answer_citations -> reload

Also verifies repeated analysis on the same order and historical-case citation
traceback. Synthetic orders/analyses are removed afterwards; results are saved
as a JSON report (no API keys/secrets).

Usage:
    python scripts/verify_llm.py [--keep] [--out <json>]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import Settings
from backend.db.session import SessionLocal
from backend.domain.models import (
    AnalysisRecord, AnswerCitation, Feedback, Message, SavedCase, WorkOrder,
)
from backend.gateways.factory import create_knowledge_gateway, create_llm_gateway
from backend.services.core import AnalysisService, WorkOrderService


CASES = [
    ("物业/公共区域卫生",
     "市民反映住宅小区物业服务企业长期不履行管理责任，公共区域垃圾无人清理、绿化长期失管，多次反映仍未整改，希望主管部门督促物业企业履职。"),
    ("劳动工资",
     "市民在白云区某餐饮店工作，离职后老板拖欠两个月工资并拒绝出具欠条，希望劳动监察部门介入追讨工资。"),
    ("市场监管",
     "市民投诉某超市销售过期食品且未明码标价，要求市场监管部门现场检查并依法处理。"),
    ("城市管理/占道与噪声",
     "市民投诉夜市餐饮店占用人行道经营、食客深夜喧哗噪声扰民，同时油烟直排，希望城管和生态环境部门联合处理。"),
    ("公共设施/电梯",
     "市民反映某高层住宅电梯连续多日故障，物业维修迟缓，存在安全隐患，希望特种设备监管部门督促处理。"),
    ("职责边界模糊",
     "市民咨询既有住宅加装电梯的规划许可与施工监管分别由哪些部门负责，同时反映施工期间占道堆放材料影响通行。"),
    ("历史案例引用",
     "市民反映临街商铺招牌脱落砸坏车辆，物业与商铺互相推诿，希望主管部门明确责任并协调赔偿。"),
]


def load_settings() -> Settings:
    settings = Settings(llm_gateway_mode="real")
    if not settings.llm_api_key:
        raise SystemExit("LLM_API_KEY missing; cannot run real LLM verification")
    if not settings.llm_model:
        raise SystemExit("LLM_MODEL missing; cannot run real LLM verification")
    print(f"real LLM endpoint={settings.llm_base_url} model={settings.llm_model} provider-mode={settings.llm_gateway_mode}")
    return settings


def verify_result(analysis: AnalysisRecord, evidence_count: int) -> dict[str, Any]:
    citations = analysis.citations
    assert analysis.conclusion
    assert analysis.recommended_department_text
    assert citations, "no citations saved"
    assert analysis.model_provider != "mock", "model_provider must be real"
    assert analysis.model_name, "model_name missing"
    linked = [c for c in citations if c.metadata_json.get("work_order_id")]
    return {
        "analysis_id": analysis.id,
        "provider": analysis.model_provider,
        "model": analysis.model_name,
        "evidence_count": evidence_count,
        "citation_count": len(citations),
        "recommended_department": analysis.recommended_department_text,
        "confidence": analysis.confidence,
        "has_historical_link": bool(linked),
        "historical_work_order_id": linked[0].metadata_json.get("work_order_id") if linked else None,
        "conclusion_head": (analysis.conclusion or "")[:160],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="keep synthetic orders/analyses")
    parser.add_argument("--out", default=r"D:\热线派单系统V2-data\llm\verify_llm_result.json")
    args = parser.parse_args()

    settings = load_settings()
    knowledge = create_knowledge_gateway(settings)
    llm = create_llm_gateway(settings)
    db = SessionLocal()
    order_ids: list[str] = []
    analysis_ids: list[str] = []
    report: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "provider": getattr(llm, "provider", None),
        "model": getattr(llm, "model_name", None),
        "cases": [],
        "multi_analysis": None,
    }
    try:
        service = WorkOrderService(db)
        first_order_id = None
        for index, (label, content) in enumerate(CASES, start=1):
            order = service.create(label, content, source="真实LLM链路验证", status="new",
                                   metadata_json={"verification": "real-llm"})
            order_ids.append(order.id)
            if first_order_id is None:
                first_order_id = order.id

            evidence = knowledge.search(content, list(("department_duties", "responsibilities",
                                                       "regulations", "historical_cases")), top_k=6)
            assert evidence, f"case {label}: no evidence recalled"
            analysis = AnalysisService(db, knowledge, llm).analyze(order, [
                "department_duties", "responsibilities", "regulations", "historical_cases",
            ])
            analysis_ids.append(analysis.id)
            db.expire_all()
            result = verify_result(db.get(AnalysisRecord, analysis.id), len(evidence))
            result["case_label"] = label
            report["cases"].append(result)
            print(f"[{index}/{len(CASES)}] {label}: PASS "
                  f"provider={result['provider']} citations={result['citation_count']} "
                  f"historical_link={result['has_historical_link']}")

        # Repeated real analysis on the same order: must not overwrite.
        first_order = db.get(WorkOrder, first_order_id)
        evidence = knowledge.search(first_order.content, ["historical_cases"], top_k=4)
        second = AnalysisService(db, knowledge, llm).analyze(first_order, ["historical_cases"])
        analysis_ids.append(second.id)
        db.expire_all()
        records = db.query(AnalysisRecord).filter(AnalysisRecord.work_order_id == first_order_id).order_by(AnalysisRecord.created_at).all()
        assert len(records) == 2, f"expected 2 analysis records, got {len(records)}"
        assert len({r.id for r in records}) == 2
        assert all(r.citations for r in records)
        report["multi_analysis"] = {
            "work_order_id": first_order_id,
            "analysis_count": len(records),
            "analysis_ids": [r.id for r in records],
            "citation_counts": [len(r.citations) for r in records],
        }
        print("repeated real analysis PASS: two independent records/citations")

        linked = next((r for r in report["cases"] if r.get("historical_work_order_id")), None)
        if linked:
            historical = db.get(WorkOrder, linked["historical_work_order_id"])
            assert historical and historical.source_case_id, "historical work order lookup failed"
            report["historical_trace"] = {
                "from_citation_work_order_id": linked["historical_work_order_id"],
                "historical_source_case_id": historical.source_case_id,
                "historical_title": historical.title,
            }
            print("historical_case citation -> MySQL work_orders trace PASS")
        else:
            raise SystemExit("no historical_case citation was produced; trace verification failed")

        report["status"] = "PASS"
    finally:
        if not args.keep:
            for aid in analysis_ids:
                db.query(AnswerCitation).filter(AnswerCitation.analysis_id == aid).delete()
                db.query(Feedback).filter(Feedback.analysis_id == aid).delete()
                db.query(Message).filter(Message.analysis_id == aid).update({Message.analysis_id: None})
                db.query(AnalysisRecord).filter(AnalysisRecord.id == aid).delete()
            for oid in order_ids:
                db.query(SavedCase).filter(SavedCase.work_order_id == oid).delete()
                db.query(WorkOrder).filter(WorkOrder.id == oid).delete()
            db.commit()
        db.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report written: {out}")


if __name__ == "__main__":
    sys.exit(main())
