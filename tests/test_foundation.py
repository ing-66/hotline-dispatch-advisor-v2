from sqlalchemy import func, select
from backend.domain.models import AnswerCitation, Feedback, Message
from backend.gateways.contracts import AnalysisResult, RetrievalResult
from backend.gateways.mocks import MockKnowledgeGateway, MockLLMGateway
from backend.repositories.core import AnalysisRepository
from backend.services.core import AnalysisService, ConversationService, FeedbackService, WorkOrderService

def evidence(evidence_id="e-1"):
    return RetrievalResult(evidence_id, "regulations", None, "doc-1", "法规", "point-1", "法规内容快照", 0.9)

def test_01_create_work_order(db):
    item = WorkOrderService(db).create("欠薪", "拖欠工资三个月")
    assert item.id and item.content == "拖欠工资三个月"

def test_02_multiple_analyses_do_not_overwrite(db):
    order = WorkOrderService(db).create("测试", "诉求")
    service = AnalysisService(db, MockKnowledgeGateway(), MockLLMGateway())
    first, second = service.analyze(order, []), service.analyze(order, [])
    assert first.id != second.id and len(AnalysisRepository(db).list_for_work_order(order.id)) == 2

def test_03_analysis_saves_multiple_citations(db):
    order = WorkOrderService(db).create("测试", "诉求")
    items = [evidence("e-1"), evidence("e-2")]
    llm = MockLLMGateway(AnalysisResult("人社部门", "结论", ["e-1", "e-2"]))
    record = AnalysisService(db, MockKnowledgeGateway(items), llm).analyze(order, ["regulations"])
    assert db.scalar(select(func.count()).select_from(AnswerCitation).where(AnswerCitation.analysis_id == record.id)) == 2

def test_04_conversation_has_multiple_messages(db):
    service = ConversationService(db); conversation = service.create("会话")
    service.add_message(conversation.id, "user", "问题"); service.add_message(conversation.id, "assistant", "答复")
    assert db.scalar(select(func.count()).select_from(Message).where(Message.conversation_id == conversation.id)) == 2

def test_05_feedback_does_not_overwrite_analysis(db):
    order = WorkOrderService(db).create("测试", "诉求")
    record = AnalysisService(db, MockKnowledgeGateway(), MockLLMGateway()).analyze(order, [])
    original = record.conclusion
    FeedbackService(db).create(record.id, "correct_department", adopted=False, comment="需修正")
    db.refresh(record)
    assert record.conclusion == original and db.scalar(select(func.count()).select_from(Feedback)) == 1

def test_06_service_uses_mock_knowledge_gateway(db):
    order = WorkOrderService(db).create("测试", "诉求")
    llm = MockLLMGateway(AnalysisResult("部门", "有依据", ["e-1"]))
    record = AnalysisService(db, MockKnowledgeGateway([evidence()]), llm).analyze(order, ["regulations"])
    assert record.citations[0].content_snapshot == "法规内容快照"

def test_07_service_uses_mock_llm_gateway(db):
    order = WorkOrderService(db).create("测试", "诉求")
    result = AnalysisResult("人社部门", "劳动保障事项", [])
    record = AnalysisService(db, MockKnowledgeGateway(), MockLLMGateway(result)).analyze(order, [])
    assert record.recommended_department_text == "人社部门"

def test_08_gateways_are_replaceable_without_service_change(db):
    class AlternateKnowledge(MockKnowledgeGateway): pass
    class AlternateLLM(MockLLMGateway): pass
    order = WorkOrderService(db).create("测试", "诉求")
    assert AnalysisService(db, AlternateKnowledge(), AlternateLLM()).analyze(order, []).id

def test_rejects_unknown_evidence_reference(db):
    order = WorkOrderService(db).create("测试", "诉求")
    llm = MockLLMGateway(AnalysisResult("部门", "错误引用", ["missing"]))
    try: AnalysisService(db, MockKnowledgeGateway(), llm).analyze(order, [])
    except ValueError as error: assert "unknown evidence" in str(error)
    else: raise AssertionError("unknown evidence ID must be rejected")

def test_direct_evidence_is_grouped_by_responsible_unit(db):
    order = WorkOrderService(db).create("入学", "咨询公办小学学位分配")
    result = AnalysisResult(
        "白云区教育局",
        "由区教育局核查处理",
        [],
        evidence_items=[
            {"source": "白云区教育局", "quote": "负责全区学前教育、基础教育、职业教育和成人教育事业与发展的统筹管理工作"},
            {"source": "白云区教育局", "quote": "按权限制订各级各类学校的招生计划并指导实施，管理本区教育招生考试工作。"},
            {"source": "白云区教育局", "quote": "按权限制订各级各类学校的招生计划并指导实施，管理本区教育招生考试工作。"},
            {"source": "白云区民政局", "quote": "负责社会救助工作"},
        ],
    )
    record = AnalysisService(db, MockKnowledgeGateway(), MockLLMGateway(result)).analyze(order, [])
    assert record.evidence_summary == (
        "“白云区教育局”负责：\n\n"
        "- 全区学前教育、基础教育、职业教育和成人教育事业与发展的统筹管理工作\n"
        "- 按权限制订各级各类学校的招生计划并指导实施，管理本区教育招生考试工作。\n\n"
        "“白云区民政局”负责：\n\n"
        "- 社会救助工作"
    )

def test_mysql_portable_crud_chinese_and_json(db):
    service = WorkOrderService(db)
    content = "市民反映住宅小区物业服务企业长期未履行管理责任，希望主管部门督促整改。"
    item = service.create("物业服务", content, metadata_json={"来源": "热线", "emoji": "☎️"})
    loaded = service.repo.get(item.id)
    assert loaded.content == content and loaded.metadata_json["emoji"] == "☎️"
    assert service.update(item.id, title="物业管理投诉").title == "物业管理投诉"
    assert service.soft_delete(item.id).status == "deleted"
