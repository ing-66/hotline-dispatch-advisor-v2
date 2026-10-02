"""Real-LLM checks for granularity + historical-case fact leakage."""

from __future__ import annotations

import json

from backend.config import Settings
from backend.db.session import SessionLocal
from backend.domain.models import AnalysisRecord, AnswerCitation, Feedback, SavedCase, WorkOrder
from backend.gateways.factory import create_knowledge_gateway, create_llm_gateway
from backend.services.core import AnalysisService, WorkOrderService


CASES = [
    ("路灯", "市民反映家附近一段道路有多盏路灯长期不亮，已经持续一个多月，夜间道路较黑，老人和学生出行存在安全隐患，希望有关单位尽快维修。"),
    ("餐饮油烟噪声", "市民反映楼下餐饮店每天营业至凌晨，排放大量油烟，同时店外顾客喧哗严重，长期影响楼上居民休息，多次与商家沟通无果，希望有关部门处理。"),
    ("树木倾斜", "市民反映小区外道路旁一棵大树明显倾斜，部分树枝已经伸到机动车道上，近日风雨天气较多，担心树木倒下影响车辆和行人安全，希望有关单位尽快检查处理。"),
]


def main() -> None:
    settings = Settings(llm_gateway_mode="real")
    knowledge = create_knowledge_gateway(settings)
    llm = create_llm_gateway(settings)
    db = SessionLocal()
    ids: list[str] = []
    results = []
    try:
        for label, content in CASES:
            order = WorkOrderService(db).create(label, content, metadata_json={"verification": "granularity"})
            ids.append(order.id)
            analysis = AnalysisService(db, knowledge, llm).analyze(
                order, ["department_duties", "responsibilities", "regulations", "historical_cases"])
            db.expire_all()
            record = db.get(AnalysisRecord, analysis.id)
            dept = record.recommended_department_text or ""
            conclusion = record.conclusion or ""
            result = {
                "case": label,
                "dept": dept,
                "confidence": record.confidence,
                "insufficient": conclusion.startswith("依据不足"),
                "leaks_tangjing": "棠景" in (dept + conclusion),
                "conclusion": conclusion,
            }
            results.append(result)
            print(label, "|", dept, "|", record.confidence, "| insufficient", result["insufficient"])
        assert results[0]["confidence"] is not None and results[0]["confidence"] > 0
        assert not results[0]["insufficient"]
        assert not results[2]["leaks_tangjing"], "tree case must not infer 棠景街"
        assert not results[1]["insufficient"]
    finally:
        if ids:
            analyses = db.query(AnalysisRecord).filter(AnalysisRecord.work_order_id.in_(ids)).all()
            aids = [a.id for a in analyses]
            if aids:
                db.query(SavedCase).filter(SavedCase.analysis_id.in_(aids)).delete(synchronize_session=False)
                db.query(AnswerCitation).filter(AnswerCitation.analysis_id.in_(aids)).delete(synchronize_session=False)
                db.query(Feedback).filter(Feedback.analysis_id.in_(aids)).delete(synchronize_session=False)
                db.query(AnalysisRecord).filter(AnalysisRecord.id.in_(aids)).delete(synchronize_session=False)
            db.query(WorkOrder).filter(WorkOrder.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
        db.close()
    print("CASE_GRANULARITY: PASS")
    out = r"D:\热线派单系统V2-data\llm\case_granularity_result.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
