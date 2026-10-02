from sqlalchemy import inspect, select, text

from backend.db.session import SessionLocal, engine
from backend.domain.models import AnalysisRecord, AnswerCitation, Conversation, Feedback, Message, SavedCase, WorkOrder
from backend.gateways.contracts import AnalysisResult, RetrievalResult
from backend.gateways.mocks import MockKnowledgeGateway, MockLLMGateway
from backend.services.core import AnalysisService, ConversationService, WorkOrderService

expected_tables = {
    "users", "departments", "work_orders", "analysis_records", "answer_citations",
    "feedback", "conversations", "messages", "saved_cases", "knowledge_bases",
}
assert expected_tables <= set(inspect(engine).get_table_names())

db = SessionLocal()
order_id = conversation_id = analysis_id = None
try:
    charset = db.execute(text(
        "SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME "
        "FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = DATABASE()"
    )).one()
    assert charset[0] == "utf8mb4"
    table_collations = db.execute(text(
        "SELECT TABLE_NAME, TABLE_COLLATION FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME <> 'alembic_version'"
    )).all()
    assert len(table_collations) == len(expected_tables)
    assert all((collation or "").startswith("utf8mb4_") for _, collation in table_collations)

    content = "市民反映住宅小区物业服务企业长期未履行管理责任，希望主管部门督促整改。"
    work_orders = WorkOrderService(db)
    order = work_orders.create("物业服务", content, request_type="投诉", metadata_json={"来源": "热线", "emoji": "☎️"})
    order_id = order.id
    assert work_orders.repo.get(order.id).content == content
    assert work_orders.repo.get(order.id).metadata_json["emoji"] == "☎️"
    assert work_orders.update(order.id, title="物业管理投诉").title == "物业管理投诉"

    conversations = ConversationService(db)
    conversation = conversations.create("MySQL 集成验证")
    conversation_id = conversation.id
    conversations.add_message(conversation.id, "user", content)
    conversations.add_message(conversation.id, "assistant", "已收到")
    db.expire_all()
    assert len(conversations.repo.get(conversation.id).messages) == 2

    item = RetrievalResult("mysql-evidence", "regulations", None, "doc-1", "物业条例", "point-1", "法规快照", 0.95)
    llm = MockLLMGateway(AnalysisResult("住房主管部门", "应督促整改", ["mysql-evidence"], confidence=0.9))
    analysis = AnalysisService(db, MockKnowledgeGateway([item]), llm).analyze(order, ["regulations"])
    analysis_id = analysis.id
    db.expire_all()
    loaded = db.get(AnalysisRecord, analysis.id)
    assert loaded.input_snapshot_json["content"] == content
    assert loaded.citations[0].content_snapshot == "法规快照"
    assert work_orders.soft_delete(order.id).status == "deleted"
    print(f"MySQL verification passed: charset={charset[0]}, table_collations=utf8mb4, tables={len(expected_tables)}, CRUD/JSON/Chinese/conversation/analysis=PASS")
finally:
    if analysis_id:
        db.query(AnswerCitation).filter(AnswerCitation.analysis_id == analysis_id).delete()
        db.query(Feedback).filter(Feedback.analysis_id == analysis_id).delete()
        db.query(Message).filter(Message.analysis_id == analysis_id).update({Message.analysis_id: None})
        db.query(AnalysisRecord).filter(AnalysisRecord.id == analysis_id).delete()
    if conversation_id:
        db.query(Message).filter(Message.conversation_id == conversation_id).delete()
        db.query(Conversation).filter(Conversation.id == conversation_id).delete()
    if order_id:
        db.query(SavedCase).filter(SavedCase.work_order_id == order_id).delete()
        db.query(WorkOrder).filter(WorkOrder.id == order_id).delete()
    db.commit()
    db.close()
