# 可复现与恢复说明

本仓库只保存程序、配置模板和技术文档。真实知识资料、历史工单、数据库、向量快照、模型缓存和密钥不进入公开 Git 历史。

## 固定运行基线

- Windows 11 / PowerShell 7
- Python 3.11+（最后验证环境为 3.13.15）
- Node.js 22.20+；前端使用已提交的 `frontend/package-lock.json` 执行 `npm ci`
- Qdrant 1.19.0
- `BAAI/bge-m3` revision `5617a9f61b028005a4858fdac845db406aefb181`
- `BAAI/bge-reranker-v2-m3` revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`

## 全新重建

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

py -3.13 -m venv knowledge-service\.venv
.\knowledge-service\.venv\Scripts\python.exe -m pip install -r knowledge-service\requirements.txt

Set-Location frontend
npm ci
Set-Location ..

Copy-Item .env.example .env
Copy-Item knowledge-service\config\config.example.yaml knowledge-service\config\config.yaml
```

下载 Qdrant 1.19.0 的 Windows 可执行文件至 sibling 数据目录 `热线派单系统V2-data\qdrant\qdrant.exe`。模型可按上述固定 revision 下载到 `热线派单系统V2-data\models`。公开演示可直接使用 `demo` 档位，不需要真实知识数据或密钥。

## 私有运行状态恢复

授权用户可从私有仓库 `ing-66/hotline-dispatch-advisor-v1-archive` 的 Release `runtime-recovery-2026-10-09` 下载 `hotline-runtime-recovery-20261009.7z`。该加密资产包含 V1/V2 的配置、839 份知识资料、词法索引、Qdrant 快照和历史导入材料。解密密码不在 GitHub 中，只保存在清理任务生成的本地恢复密钥文件。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest
Set-Location frontend
npm test
npm run build
```

恢复真实数据后再执行 `scripts/health_check.ps1 -RequireKnowledge`、`scripts/verify_qdrant.py` 和 `scripts/verify_case_alignment.py`。
