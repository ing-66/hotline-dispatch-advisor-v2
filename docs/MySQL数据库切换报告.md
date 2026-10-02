# MySQL 数据库切换报告

## 变更结果

- 业务数据库：MySQL 8.0，本机 `hotline_ai`
- ORM：SQLAlchemy（保持不变）
- 驱动：PyMySQL
- 字符集/排序规则：`utf8mb4` / `utf8mb4_unicode_ci`
- RAG：Qdrant 与 KnowledgeGateway 保持不变

## 表结构

保留原有 10 张核心表及外键关系，没有新增或删除业务表。为实际查询字段补充了 MySQL 普通索引：工单类型、状态、承办部门、创建时间，以及研判/会话消息的关联键与创建时间。

## 验证

- 真实 MySQL 连接：PASS
- 空库初始化：PASS
- Alembic upgrade / downgrade / upgrade：PASS
- 10 张业务表及全部表 `utf8mb4`：PASS
- 工单创建、查询、更新、软删除：PASS
- 中文与 Emoji：PASS
- JSON 写入和读取：PASS
- 会话及两条消息重新读取：PASS
- AI 研判、引用快照保存和重新读取：PASS
- MockKnowledgeGateway RAG 边界测试：PASS

## 遗留事项

- 当前项目尚未配置真实 Qdrant Adapter/端点，因此只能确认 Qdrant 架构、资产和 Mock 检索测试未受影响，无法执行真实 Qdrant 连接测试。
- 本机 `.env` 为完成验证临时使用 root；生产环境应使用按最小权限配置的 `hotline_app`，示例配置已按此保留。

