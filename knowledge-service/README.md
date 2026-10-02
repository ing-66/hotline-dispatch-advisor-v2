# Knowledge Service（知识服务独立目录）

本目录是从旧项目 `D:\热线派单系统` 独立迁出的 Knowledge API 代码与本地配置，
归属于 `D:\热线派单系统V2` 管理。大型运行时资产（模型、Qdrant storage、
索引、快照、日志）存放在独立的 runtime 数据目录：

```text
D:\热线派单系统V2-data\
├─ models\                    # BAAI/bge-m3、BAAI/bge-reranker-v2-m3（HF 缓存）
├─ qdrant\qdrant.exe          # Qdrant 1.19.0 可执行文件
├─ qdrant\storage\            # Qdrant storage（含 hotline_dispatch_v2）
├─ qdrant-snapshots\          # Qdrant 快照（含迁移快照）
├─ indexes\                   # lexical_v2.sqlite3 / manifest.sqlite3
├─ kb-assets\                 # 文件存储（健康检查用）
└─ logs\                      # 服务日志
```

## 目录

```text
knowledge-service\
├─ kb_service\                # Knowledge API 包（入口 kb_service.api:app）
├─ config\
│  ├─ config.example.yaml     # 模板（无密钥，可提交）
│  └─ config.yaml             # 本机真实配置（已 gitignore）
├─ requirements.txt           # 与旧环境一致的固定版本
├─ .venv\                     # 本机虚拟环境（已 gitignore）
└─ README.md
```

## 外部契约（未改变）

- `GET /health`：返回 Qdrant、lexical、文件存储状态。
- `POST /retrieval`：`Bearer <api_key>` 鉴权，返回四类知识的真实检索记录。
- Collection 名称保持 `hotline_dispatch_v2`。

## 环境变量

运行脚本默认由 V2 `scripts/` 下的启动脚本设置；也可直接设置：

```text
HOTLINE_KB_CONFIG=knowledge-service/config/config.yaml
KB_ASSET_ROOT=<runtime>/kb-assets
HF_HOME=<runtime>/models
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

`config.py` 支持 `KB_API_KEY`、`KB_COLLECTION`、`KB_QDRANT_URL`、`KB_MODEL_CACHE`、
`KB_LEXICAL_DB` 等环境变量覆盖，方便部署时不留本地路径。

## 首次搭建

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config\config.example.yaml config\config.yaml
# 编辑 config.yaml：填写 runtime 数据目录真实路径与 api_key
```

## 启动与验证（推荐从 V2 根目录调用）

```powershell
.\scripts\start_qdrant.ps1
.\scripts\start_knowledge_api.ps1
python .\scripts\verify_knowledge_service.py
python .\scripts\verify_qdrant.py
```

如需重建空实例的 Collection（异常恢复场景）：

```powershell
python .\scripts\restore_qdrant_snapshot.py `
  --snapshot "D:\热线派单系统V2-data\qdrant-snapshots\hotline_dispatch_v2\<snapshot>.snapshot"
```

## 停止

```powershell
.\scripts\stop_knowledge_api.ps1
.\scripts\stop_qdrant.ps1
```

## 迁移说明

本次迁移只搬移现有可用资产，没有重建知识库、没有重新 Embedding、
没有修改检索算法与 Knowledge API 外部契约。MySQL 已从 Knowledge API
健康检查中解耦（`mysql.enabled=false`），检索链路不再依赖 V1 开发库。

> 旧项目目录 `D:\热线派单系统` 在本目录可用后已不再是 V2 运行依赖；
> 是否删除由用户决定，本仓库不自动删除。
