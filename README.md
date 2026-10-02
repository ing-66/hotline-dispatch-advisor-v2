# 热线派单系统 V2

独立的 12345 热线工单智能研判系统。架构与实施边界以 `docs/热线派单顾问_V2_需求实施与起步计划_架构冻结版.md` 为准。

## 当前目录

- `frontend/`：assistant-ui 前端
- `backend/`：Business API
- `knowledge-service/`：独立迁出的 Knowledge API 代码与本地配置
- `docs/`：V2 冻结需求及 V1 参考文档
- `assets/`：本地知识资料挂载位置；公开仓库只提供目录说明，不包含真实知识库或历史工单
- `scripts/`：项目脚本
- `tests/`：测试

大型知识服务运行时资产位于独立的 sibling 数据目录
`D:\热线派单系统V2-data`（Qdrant 可执行文件/storage/快照、模型缓存、
lexical 索引、kb-assets、日志），不在 Git 跟踪范围内。
具体迁移内容与验证结果见 `docs/知识服务独立迁移报告.md`。

> **公开版数据边界：** 本仓库只发布程序、配置模板和技术文档。原始知识资料、历史
> 工单、数据库、Qdrant storage、模型缓存和真实密钥均不发布。部署者需要自行准备合法、
> 已脱敏的数据源；没有真实知识库和模型凭据时，请使用 `demo` 档位体验界面和业务闭环。

## 一键启动（交付入口）

首次使用先确认 `.env` 已配置。默认使用可独立运行的正式模式：本地 SQLite
保存新工单，启用真实 Qdrant 知识库和真实 LLM，不依赖 Docker/MySQL：

```powershell
.\启动系统.ps1
```

启动成功后访问 <http://127.0.0.1:3000>。停止全部本项目进程：

```powershell
.\停止系统.ps1
```

另有两个明确区分的运行档位：

```powershell
.\启动系统.ps1 -Profile production  # MySQL + 真实知识库 + 真实 LLM
.\启动系统.ps1 -Profile demo        # SQLite + Mock，仅演示/离线验收，结果不可用于派单
```

`production` 需要 Docker Desktop；`standalone` 是本机推荐正式使用方式。若 Python
不在 PATH，设置 `HOTLINE_PYTHON` 为 Python 3.11+ 的完整路径。日志和本地数据库均在
`D:\热线派单系统V2-data`，不会写入源码目录。

独立体检（正式模式须检查知识链路）：

```powershell
.\scripts\health_check.ps1 -RequireKnowledge
```

## 分组件启动（维护用）

```powershell
.\scripts\start_qdrant.ps1            # Qdrant :6333（storage 位于 V2-data）
.\scripts\start_knowledge_api.ps1     # Knowledge API :8088（V2 独立 venv）
.\scripts\start_business_api.ps1      # Business API :8000；默认遵循 .env
.\scripts\start_frontend.ps1 -Mode prod
```

生产档业务数据库为 MySQL 8.4（`utf8mb4`），默认端口 `3306`；独立档使用 SQLite。
存活/就绪检查：`GET http://127.0.0.1:8000/api/health`、
`GET http://127.0.0.1:8000/api/ready`、`GET http://127.0.0.1:8088/health`、
`http://127.0.0.1:6333/healthz`。

真实知识检索通过独立 Knowledge API 访问 Qdrant。配置 `QDRANT_URL`、`QDRANT_API_KEY`、`QDRANT_COLLECTION`、`QDRANT_TIMEOUT`；生产使用 `KNOWLEDGE_GATEWAY_MODE=qdrant`，测试可切换为 `mock`。业务 Service 不直接依赖 Qdrant SDK。

真实模型研判通过 `backend/gateways/real_llm.py` 接入（默认 Mock，`real` 模式不自动回退）。
配置 `LLM_GATEWAY_MODE`、`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_TIMEOUT`、
`LLM_TEMPERATURE`、`LLM_MAX_TOKENS`。运行真实链路验证：

```powershell
python scripts/verify_llm.py
```

验证知识服务：

```powershell
python scripts/verify_knowledge_service.py
python scripts/verify_qdrant.py
```

历史工单数据与 Qdrant ID 对齐（详情见 `docs/历史工单导入与QdrantID对齐报告.md`）：

```powershell
python -m scripts.import_department_master --apply
python -m scripts.import_historical_work_orders --apply
python -m scripts.sync_historical_cases_to_qdrant --apply
python -m scripts.verify_case_alignment
```

真实 LLM 接入报告见 `docs/真实LLM接入报告.md`。

## Business API 主要端点

| 功能 | 端点 |
|---|---|
| 健康检查 | `GET /api/health` |
| 工单 CRUD/列表 | `POST/GET/PATCH/DELETE /api/work-orders[/{id}]` |
| 发起研判 | `POST /api/work-orders/{id}/analyses` |
| 研判历史/详情 | `GET /api/work-orders/{id}/analyses`、`GET /api/analyses/{id}` |
| 引用依据 | `GET /api/analyses/{id}/citations` |
| 人工反馈 | `POST/GET /api/analyses/{id}/feedback` |
| 收藏案例 | `POST/GET/DELETE /api/saved-cases[/{id}]` |
| 会话/消息 | `POST/GET /api/conversations[/{id}[/messages]]` |

列表接口统一 `{items,page,page_size,total}`；交互文档见 `http://127.0.0.1:8000/docs`。
详细说明与真实 HTTP 闭环验证见 `docs/BusinessAPI业务闭环报告.md`。

当前 MySQL `work_orders` 已导入 5,143 条历史工单；Qdrant 5,143 个
`historical_case` Point 已带 `work_order_id/source_case_id`。

旧项目目录 `D:\热线派单系统` 已不再是 V2 运行依赖；是否删除由用户决定。

前端在另一终端启动：

```powershell
Set-Location frontend
npm install
npm run dev
```

前端已恢复 assistant-ui 官方 default Starter 视觉并接入 Business API
（见 `docs/assistant-ui原版恢复报告.md`）：

```text
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

运行前端测试：`npm test`；真实浏览器验证：`node frontend/scripts/verify_starter_browser.mjs`。

运行后端测试：

```powershell
pytest
```
