# ADR-009：业务数据库改用 MySQL

状态：接受。

V2 业务事实唯一真源由 PostgreSQL 调整为 MySQL 8，字符集固定为 `utf8mb4`。Qdrant 仍是独立的 RAG 知识检索层；Gateway、业务表职责和依赖方向不变。本决策覆盖冻结需求文档中所有 PostgreSQL 选型表述。

