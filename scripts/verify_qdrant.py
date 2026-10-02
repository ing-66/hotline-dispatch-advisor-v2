from backend.db.session import SessionLocal
from backend.domain.models import AnalysisRecord, AnswerCitation, Feedback, Message, SavedCase, WorkOrder
from backend.gateways.factory import create_knowledge_gateway
from backend.gateways.contracts import AnalysisResult
from backend.gateways.mocks import MockLLMGateway
from backend.services.core import AnalysisService, WorkOrderService

query = "市民反映住宅小区物业服务企业长期不履行管理责任，多次反映仍未处理公共区域环境卫生问题，希望主管部门督促整改。"
gateway = create_knowledge_gateway()
health = gateway.health()
assert health["qdrant"]["ok"] and health["qdrant"]["points"] > 0

groups = {}
for knowledge_type in ("department_duties", "responsibilities", "regulations", "historical_cases"):
    groups[knowledge_type] = gateway.search(query, [knowledge_type], top_k=2)
    assert groups[knowledge_type], f"no real result for {knowledge_type}"
    assert all(item.content and item.metadata["source_type"] for item in groups[knowledge_type])

evidence = groups["department_duties"][0]
llm = MockLLMGateway(AnalysisResult("住房主管部门", "应根据检索依据督促物业企业整改。", [evidence.evidence_id], confidence=0.9))
db = SessionLocal()
order_id = analysis_id = None
try:
    order = WorkOrderService(db).create("物业服务企业履责问题", query, metadata_json={"verification": "real-qdrant"})
    order_id = order.id
    analysis = AnalysisService(db, gateway, llm).analyze(order, ["department_duties"])
    analysis_id = analysis.id
    db.expire_all()
    loaded = db.get(AnalysisRecord, analysis.id)
    assert loaded and loaded.citations and loaded.citations[0].point_id
    assert loaded.citations[0].content_snapshot == evidence.content
    historical_case_linked = any(item.metadata.get("case_id") for item in groups["historical_cases"])
    print(f"Qdrant verification passed: collection={health['collection']}, points={health['qdrant']['points']}, four_types=PASS, analysis/citation persistence=PASS, historical_case_id={historical_case_linked}")
finally:
    if analysis_id:
        db.query(AnswerCitation).filter(AnswerCitation.analysis_id == analysis_id).delete()
        db.query(Feedback).filter(Feedback.analysis_id == analysis_id).delete()
        db.query(Message).filter(Message.analysis_id == analysis_id).update({Message.analysis_id: None})
        db.query(AnalysisRecord).filter(AnalysisRecord.id == analysis_id).delete()
    if order_id:
        db.query(SavedCase).filter(SavedCase.work_order_id == order_id).delete()
        db.query(WorkOrder).filter(WorkOrder.id == order_id).delete()
    db.commit()
    db.close()

