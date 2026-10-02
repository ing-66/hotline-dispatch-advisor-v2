# 热线派单外部知识库

本项目的程序、知识源、模型、向量、词法索引、缓存和日志全部位于 `D:\热线派单系统`。拆分前原始 Markdown 资料位于 `knowledge-original`；供检索摄入的清洗、拆分资料位于 `knowledge-source`。不要将 `knowledge-source` 误作原始资料归档。

检索链：BGE-M3 稠密向量召回 + SQLite FTS5 词法召回 + RRF 融合 + BGE 重排。

知识库 API 保留兼容的 `POST /retrieval` 协议；正式问答已由本项目直接调用云端模型，不再依赖 Dify。

Qdrant 以原生 Windows 服务端运行在 `127.0.0.1:6333`，与 Docker 和 WeKnora 隔离。执行 `start-qdrant.ps1` 或 `start.ps1` 可启动服务。
## 稳定启动

双击 `启动热线派单顾问与小助手.cmd`。脚本会依次启动 Qdrant、知识库 API 和统一 Web 后端，通过健康检查后打开“热线派单顾问”和“派单小助手”；已经运行的服务不会重复启动。旧入口 `启动热线派单助手.cmd` 仅转调这一正式入口。

正常标志为命令窗口显示 `READY`，并可访问：

- 顾问：`http://127.0.0.1:3786/`
- 小助手：`http://127.0.0.1:3790/`
- 管理后台：`http://127.0.0.1:3791/`
- 知识库健康检查：`http://127.0.0.1:8088/health`

运行日志位于 `logs`。正式用户、会话、案例、知识元数据与索引任务位于 MySQL；`web/data/store.sqlite3` 仅作为历史只读回退，不再由正式进程写入。839份受控知识原件位于 `data/kb-assets`。云模型密钥仅保存在本机配置中，不得提交或对外发送。

查看统一运行状态：`powershell -File .\status.ps1`。完整管理员操作与恢复边界见 `migration/ADMIN_OPERATIONS_GUIDE.md`。

若启动失败，先关闭遗留的同名服务后重试，并查看 `logs/api.stderr.log` 与 `logs/web.stderr.log`。不要通过反复修改依赖或启动脚本临时绕过错误。
