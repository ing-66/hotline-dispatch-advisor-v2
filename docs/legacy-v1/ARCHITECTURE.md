# 系统架构

## 当前架构（阶段0基线）

- `web/server.cjs`：原生 Node HTTP 服务，同时提供3786顾问页和3790小助手页。
- `web/static`：两个单文件前端；当前无登录、用户和权限体系。
- `web/lib/store.js`：使用 Node 内置 SQLite，保存会话、消息和案例。
- `kb_service/api.py`：FastAPI知识检索接口。
- `kb_service/engine.py`：BGE-M3向量召回、SQLite FTS5词法召回及RRF融合。
- Qdrant：独立Windows进程，正式集合为`hotline_dispatch_v1`。
- `knowledge-original`：839份拆分前原始Markdown，只作原件归档。
- `knowledge-source`：清洗、拆分后的检索摄入资料，不是原件归档。

当前Qdrant服务实际存储在`data/qdrant-server`。`config.yaml`中的`qdrant_path`仅在没有配置`qdrant_url`的嵌入模式下使用；当前通过`qdrant_url=http://127.0.0.1:6333`访问独立服务。

## 目标架构

```text
顾问/小助手/管理后台
        |
Node业务API：登录、RBAC、会话、知识CRUD、审计
        |                         |
      MySQL                 受控原文件存储
        |
Python知识服务：解析、切片、索引任务
        |                         |
     Qdrant                    SQLite FTS5
```

MySQL保存业务事实、知识版本、解析正文、切片正文和任务状态；Qdrant与FTS5均为可重建索引。第一期仅支持Markdown，但文件格式字段和解析器接口必须允许后续加入PDF、DOCX。

## 运行入口

- 统一启动：`启动热线派单顾问与小助手.cmd`
- 状态检查：`status.ps1`
- 顾问：`http://127.0.0.1:3786/`
- 小助手：`http://127.0.0.1:3790/`
- 知识API：`http://127.0.0.1:8088/health`
- Qdrant：`http://127.0.0.1:6333/healthz`

## 数据安全边界

- 不得将`knowledge-source`当作原始资料覆盖`knowledge-original`。
- 不得直接修改SQLite或Qdrant伪造任务状态。
- 不得把`config.yaml`、`web/config.json`、`web/.env`提交到Git或写入交接文档。
- 更新知识必须创建版本；删除知识默认软删除，并通过任务同步清理检索索引。
