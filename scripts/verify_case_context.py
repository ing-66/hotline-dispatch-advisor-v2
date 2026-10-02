"""Real-LLM verification of case jurisdiction and multi-level knowledge rules."""

from __future__ import annotations

import json
from pathlib import Path

from backend.config import Settings
from backend.db.session import SessionLocal
from backend.domain.models import (
    AnalysisRecord, AnswerCitation, Feedback, Message, SavedCase, WorkOrder,
)
from backend.gateways.factory import create_knowledge_gateway, create_llm_gateway
from backend.services.core import AnalysisService, WorkOrderService


CASES = [
    ("物业垃圾", "市民反映所在小区物业服务企业长期不清理楼道和公共区域垃圾，垃圾桶满溢无人更换，多次向物业反映均未处理，希望主管部门督促整改。"),
    ("电梯故障", "市民反映所在住宅小区电梯频繁故障，多次出现停梯和困人情况，物业一直未彻底维修，希望有关部门介入处理。"),
    ("拖欠工资", "市民反映所在公司已经连续两个月拖欠工资，多次向公司负责人催讨仍未支付，希望有关部门帮助处理。"),
    ("路灯故障", "市民反映家附近道路多盏路灯长期不亮，夜间出行存在安全隐患，希望有关单位尽快维修。"),
    ("无证经营", "市民反映附近一家商铺疑似长期无证经营，且占道摆放商品，影响周边居民生活，希望有关部门核查处理。"),
    ("建筑垃圾", "市民反映住宅附近长期有人堆放建筑垃圾，迟迟无人清理，扬尘和异味影响居民生活，希望主管部门处理。"),
    ("噪声投诉", "市民反映附近商铺每天深夜播放高音量音乐，严重影响居民休息，多次沟通无效，希望有关部门处理。"),
    ("明确外区", "市民反映天河区某小区物业长期不清理公共区域垃圾，希望主管部门处理。"),
]


def main() -> None:
    settings = Settings(llm_gateway_mode="real")
    knowledge = create_knowledge_gateway(settings)
    llm = create_llm_gateway(settings)
    db = SessionLocal()
    order_ids: list[str] = []
    rows: list[dict] = []
    try:
        service = WorkOrderService(db)
        for label, content in CASES:
            order = service.create(label, content, source="案例上下文验证", status="new",
                                   metadata_json={"verification": "case-context"})
            order_ids.append(order.id)
            analysis = AnalysisService(db, knowledge, llm).analyze(
                order, ["department_duties", "responsibilities", "regulations", "historical_cases"])
            db.expire_all()
            record = db.get(AnalysisRecord, analysis.id)
            rows.append({
                "case": label,
                "first": record.recommended_department_text,
                "confidence": record.confidence,
                "insufficient": bool(record.conclusion.startswith("依据不足")),
                "conclusion": record.conclusion,
            })
            print(label, "|", record.recommended_department_text, "|", record.confidence,
                  "| insufficient:", bool(record.conclusion.startswith("依据不足")))
        outside = rows[-1]
        assert "天河" in (outside["conclusion"] or "") or "非白云" in (outside["conclusion"] or "")
    finally:
        # Remove generated orders/analyses, keep existing user data.
        if order_ids:
            analyses = db.query(AnalysisRecord).filter(AnalysisRecord.work_order_id.in_(order_ids)).all()
            aids = [a.id for a in analyses]
            if aids:
                db.query(SavedCase).filter(SavedCase.analysis_id.in_(aids)).delete(synchronize_session=False)
                db.query(AnswerCitation).filter(AnswerCitation.analysis_id.in_(aids)).delete(synchronize_session=False)
                db.query(Feedback).filter(Feedback.analysis_id.in_(aids)).delete(synchronize_session=False)
                db.query(Message).filter(Message.analysis_id.in_(aids)).update({Message.analysis_id: None}, synchronize_session=False)
                db.query(AnalysisRecord).filter(AnalysisRecord.id.in_(aids)).delete(synchronize_session=False)
            db.query(WorkOrder).filter(WorkOrder.id.in_(order_ids)).delete(synchronize_session=False)
        db.commit()
        db.close()
    out = Path(r"D:\热线派单系统V2-data\llm\case_context_result.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved:", out)


if __name__ == "__main__":
    main()
