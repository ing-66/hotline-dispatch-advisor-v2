# Business API HTTP 业务闭环报告

日期：2026-09-07

## 结论

```text
HTTP API业务闭环结果：成功
```

## 1. 本阶段目标

在不修改 Service/Gateway/MySQL/RAG/LLM 架构的前提下，把已有后端能力通过规范
FastAPI HTTP 接口完整暴露，覆盖：工单、AI 研判、引用、反馈、收藏、会话/消息。

## 2. 新增/补齐的 HTTP 端点

### 工单

```text
POST   /api/work-orders
GET    /api/work-orders?page=&page_size=&status=&request_type=&department_id=&keyword=
PATCH  /api/work-orders/{id}
DELETE /api/work-orders/{id}      （软删除 status=deleted）
GET    /api/work-orders/{id}
```

### AI 研判与引用

```text
POST   /api/work-orders/{id}/analyses
GET    /api/work-orders/{id}/analyses?page=&page_size=
GET    /api/analyses/{id}
GET    /api/analyses/{id}/citations
```

### 反馈

```text
POST /api/analyses/{id}/feedback
GET  /api/analyses/{id}/feedback
```

### 收藏案例

```text
POST   /api/saved-cases
GET    /api/saved-cases?page=&page_size=
DELETE /api/saved-cases/{id}
```

### 会话/消息

```text
POST /api/conversations
GET  /api/conversations?page=&page_size=
GET  /api/conversations/{id}
POST /api/conversations/{id}/messages
GET  /api/conversations/{id}/messages
```

健康检查与文档：

```text
GET /api/health
GET /docs（FastAPI 自动 Swagger）
```

## 3. 统一响应 Schema

`backend/api/schemas.py` 提供：

```text
WorkOrderCreate/Update/Response
AnalysisCreate/Response
CitationResponse
FeedbackCreate/Response
SavedCaseCreate/Response
ConversationCreate/Response
MessageCreate/Response
Page<T>（items/page/page_size/total 统一分页）
```

所有列表接口使用同一分页结构，不再直接返回裸 ORM。

## 4. 状态码与错误映射

```text
200/201/204：查询/创建/删除成功
400：业务参数错误（如非法 evidence 引用）
404：资源不存在
409：冲突（已删除工单发起研判、重复收藏）
422：Schema 校验失败
503：KnowledgeGatewayError / LLMGatewayError 统一受控映射
```

Business API 不会向前端泄漏 Python traceback 或供应商内部错误。

## 5. AI 研判链路

`POST /api/work-orders/{id}/analyses` 只调用 `AnalysisService.analyze`：

```text
读取 work_order → KnowledgeGateway 真实检索 → RealLLM/配置网关
→ Evidence/evidence_id 校验 → analysis_records → answer_citations → 事务提交
```

Router 不重写业务链路；失败（RAG/LLM/校验）不会留下半成品正式研判。

## 6. 历史案例跳转

`answer_citations.metadata` 保留 `work_order_id/source_case_id`。前端拿到
`knowledge_type=historical_case` 引用后，调用

```text
GET /api/work-orders/{work_order_id}
```

即可查看原始历史工单。未新增 `historical_cases` 业务实体。

## 7. Service/Repository 最小补充

- Repository：工单分页/筛选、研判分页、会话/消息查询、反馈查询、收藏 CRUD。
- Service：只读查询方法、重复收藏冲突检测；没有改动业务语义。
- 新增 `AnalysisQueryService`：只读访问研判，不需要任何 Gateway。

## 8. 测试

### 自动测试（默认 Mock，不消耗真实模型）

`pytest -q`：41 passed。

覆盖：

- 工单创建/列表/分页/筛选/详情/更新/软删除/不存在 ID/422
- 发起研判/同单多次研判/历史列表/详情/引用
- 非法 evidence → 400
- 反馈创建/列表/非法 analysis_id
- 收藏/列表/重复 409/删除
- 会话/消息全流程
- KnowledgeGatewayError → 503
- LLMGatewayError → 503
- /docs 与 /openapi.json

普通 API 测试依赖 `MockKnowledgeGateway`/`MockLLMGateway`，不会调用真实模型。

### 真实 HTTP 闭环（verify_business_api.py）

以 `LLM_GATEWAY_MODE=real` 启动 Business API 后执行：

```text
HTTP 创建工单
→ HTTP 发起真实 AI 研判（deepseek）
→ HTTP 历史研判列表/研判详情
→ HTTP 引用列表
→ historical_case 引用 → GET 原 work_order（回查 PASS）
→ HTTP 提交/读取 feedback
→ HTTP 收藏/列表/取消收藏
→ HTTP 会话/消息
```

结果：PASS。验证用数据随后清理，JSON 报告保存在
`D:\热线派单系统V2-data\api\verify_business_api.json`。

## 9. 遗留

- 会话消息目前只是记录型写入，未接入聊天智能体（会话与正式研判仍属两套对象）。
- 收藏/反馈没有用户认证上下文（权限系统属后续任务）。
- 前端尚未接入这些端点。
- `PATCH /work-orders` 不开放系统字段与部门直接修改，部门修正仍走反馈语义。
