# 真实 Qdrant 接入报告

## 架构

`AnalysisService → KnowledgeGateway → QdrantKnowledgeAdapter → Knowledge API → Qdrant`

Mock Gateway 保留，通过 `KNOWLEDGE_GATEWAY_MODE` 在 `mock` 与 `qdrant` 间切换。

## 实际环境

- Knowledge API：`http://127.0.0.1:8088`
- Qdrant：`http://127.0.0.1:6333`
- Collection：`hotline_dispatch_v2`
- Point 数：20,916

## 测试结果

- 真实健康检查：PASS
- 部门职责检索：PASS
- 权责清单检索：PASS
- 政策法规检索：PASS
- 历史案例检索：PASS
- 真实检索 → Mock LLM → analysis_records → answer_citations → 重新读取：PASS
- 连接失败、超时、鉴权失败、Collection/端点不存在、空结果、缺失 metadata、异常结构：PASS
- 既有自动测试：PASS

## 遗留问题

当前历史案例 Point 的 payload 只有 `point_id/chunk_id/document_id/category/source_path` 等字段，没有 `case_id` 或 `source_record_id`；现有 V2 MySQL 也没有独立 `historical_cases` 表。遵循“不修改已冻结 MySQL 架构”的约束，本次未新增表或伪造映射，因此历史案例尚不能通过 `case_id` 回溯 MySQL。

