# 已确认的改造决策

1. 产品定位是多人使用的热线派单智能辅助系统和知识库管理后台，不在本轮建设完整12345工单流转、催办、超期和办结系统。
2. 引入MySQL作为用户、权限、会话、知识版本、切片、审计和任务状态的权威数据源。
3. Qdrant只保存向量及检索载荷，FTS5只保存关键词索引；两者必须可以从MySQL和原始文件重建。
4. 原始Markdown位于`knowledge-original`，派生检索资料位于`knowledge-source`，二者不得混淆。
5. 知识后台第一期只接受Markdown；数据库使用通用格式字段，解析器采用可扩展接口，为PDF和DOCX预留入口，但不得在未实现时宣称支持。
6. 原文件保存在受控文件目录（未来可替换为MinIO/NAS），MySQL保存路径、SHA-256、版本和解析正文，不把文件二进制直接塞进MySQL。
7. 切片正文保存到MySQL；Qdrant向量不复制进MySQL。
8. 文档修改创建新版本，索引成功后才切换当前版本；失败时旧版本继续服务。
9. 文档删除默认软删除，原文件和审计记录不立即清除。
10. 改造按阶段推进，每阶段必须满足验收门槛后才能进入下一阶段。

## 阶段2 认证与 RBAC 决策（2026-09-03）

11. **认证机制：服务端不透明 Session + HttpOnly Cookie**（而非 JWT）。
    理由：当前是单进程同源 Node Web（`web/server.cjs`），无跨域/分布式/移动端需求；不透明 Session 可在服务端即时撤销（停用/退出/改密即失效），无 JWT 的退出/撤销/轮换复杂度。不引入 JWT 依赖。
12. **Session 存储与令牌安全**：登录生成 32 字节随机令牌（`crypto.randomBytes(32).toString('base64url')`）下发为 `sid` Cookie；**数据库只存令牌的 SHA-256 摘要**（`auth_sessions.token_hash`），数据库泄露不直接可用。Cookie 设 `HttpOnly; SameSite=Lax; Path=/`；生产环境按配置加 `Secure`。管理后台与认证/管理 API 走独立端口 3791（与页面同源），旧 3786/3790 前端不读取该 Cookie。
13. **CSRF 防护：双重提交 Cookie + Origin 校验**（等效同源防护）。所有非 GET/HEAD/OPTIONS 请求要求 `X-CSRF-Token` 头等于同站 `csrf_token` Cookie，并校验 `Origin`（缺失或非白名单返回 403）。`SameSite=Lax` 作为第二道防线。
14. **密码哈希：bcrypt（bcryptjs，cost 10）**。纯 JS 无原生编译，Windows 可复现；禁止 SHA-256/可逆加密/明文。登录失败统一返回“用户名或密码错误”，不泄露账号是否存在；日志与响应不含密码/令牌/Cookie。
15. **登录防暴力：`login_attempts` 表 + 计数窗口**。同一用户名 15 分钟内失败 ≥5 次则返回 429 并拒绝登录；成功后清除该用户名失败记录。按 IP 的分布式限流留待阶段8（本阶段为最小可用方案）。
16. **最后管理员保护**：不允许停用、删除或撤销「最后一个有效系统管理员」的管理员角色/权限；服务端强制校验。
17. **角色与权限模型**：四类初始角色（`system_admin` 系统管理员、`kb_admin` 知识管理员、`kb_reviewer` 知识审核员、`user` 普通用户）。权限码最小充分：用户管理 `user:list/view/create/update/disable/reset_password`、部门 `dept:list/view/create/update/disable`、角色授权 `role:list/view/assign`、系统配置 `system:config`、审计 `audit:view`，并为知识管理预留 `kb:view/edit/review/publish`（阶段4 启用）。种子数据经幂等 CLI 写入，管理员密码不硬编码（初始化 CLI 从环境变量读取）。
18. **Node/MySQL 边界**：Node 管理后台经 `mysql2` 连接池访问 MySQL；SQL 全部参数化并封装在 `web/lib/` 的 repository/service 层，路由层不出现 SQL。凭据读取优先级：`web/.env` 的 `DB_*` 环境变量 → 根 `config.yaml` 的 `mysql:` 段（轻量解析），两者均不进入 Git。Python 侧（`kb_service`）仍只做检索与（未来）索引任务，不承担用户入口认证。
19. **既有入口的临时状态**：阶段3 完成会话归属迁移前，3786/3790 的聊天/历史/案例接口保持“未登录可访问”的开发态（管理功能除外），并在交接文档中明示“不得对外宣称可安全多人开放”；全局模型配置接口 `/api/config` **读与写均仅系统管理员**（未登录 401、无权 403），响应与日志不含 API Key，写操作同时受 CSRF 保护。

## 阶段3 会话迁移与隔离决策（2026-09-03）

20. **历史会话默认归属**：用户确认新建专用账号 `history`（显示名“历史数据”，`user` 角色，可登录查看历史）作为阶段0 冻结清单（78 会话/146 消息）的默认归属；初始口令随机生成，仅存本地 `logs/_history_pw.txt`（gitignore），不硬编码/不入库。
21. **测试残留清理授权**：正式 `web/data/store.sqlite3` 相对冻结基准多出的 5 会话/10 消息/3 案例，逐条 100% 判定为早期 `test-contract.ps1` 写入的测试残留（见 `migration/phase2-rbac/SQLITE_DATA_DIFFERENCE_REPORT.md`）。用户明确授权“清理后迁移”：删除前先做一致性只读备份（`backups/stage3-cleanup-20260903-160135/`），删除后校验计数 78/146/0 且 id 集合与冻结备份逐条一致（`migration/phase3-conversations/scripts/cleanup_store.py`）。
22. **会话存储切换**：阶段3 起生产会话/历史/案例存储切换为 MySQL（`conversations/messages/saved_cases`，0004/0005 迁移：`source_uuid` 幂等锚点 + `user_id NOT NULL`）；`web/lib/store.js` 改为工厂（`HOTLINE_STORE_BACKEND=mysql|sqlite`，默认 MySQL 启用即 mysql，sqlite 保留用于契约临时实例与回退）。SQLite `web/data/store.sqlite3` 转只读保留（不再被正式进程写入；多份备份留档）。
23. **聊天入口登录化与隔离**：3786/3790 的 `/api/chat`、`/api/conversations`、`/api/conversations/:id/messages`、`/api/cases` 全部要求登录（未登录 401）并受 CSRF 保护（已登录缺失/不匹配 403）；所有查询按当前登录用户 `user_id` 过滤，跨用户读取返回 404；前端（adviser/helper）自动跳登录页并回跳（`login?next=`，仅限本机 host）。决策 19 中“未登录可访问”的临时状态自本阶段起废止。

## 阶段4 Markdown知识管理决策（2026-09-03）

24. **上传协议与格式边界**：一期仅接受 `.md`。浏览器用 File API 读取文本后以 JSON 批量提交（每批最多20份、单份最多2MiB）；PDF/DOCX明确返回暂不支持。后续格式扩展沿用 `format/mime_type` 与解析器边界，不改变文档/版本模型。
25. **受控原件存储**：后台上传文件写入 `data/kb-assets/<sha前两位>/<sha256>.md`，使用内容寻址和独占创建；`file_assets` 保存路径、SHA-256、大小和上传人，重复内容复用同一资产记录。该目录与 `knowledge-original` 完全隔离，阶段4不导入或修改839份历史原件。
26. **版本审核与发布切换**：版本为追加型事实，不原地覆盖正文；状态流为 `draft → pending_review → approved/rejected`。审核通过生成MySQL切片并创建幂等索引任务；阶段4只提供“模拟成功”执行器用于验证任务与发布切换，真正写Qdrant/FTS5留到阶段5。只有任务成功才把版本置为 `published` 并更新文档当前版本。
27. **安全预览**：详情接口最多返回每版本前20,000字符；管理页用HTML转义后的 `<pre>` 纯文本展示，不解释Markdown内嵌HTML或执行脚本。

## 阶段5 增量索引生命周期决策（2026-09-03）

28. **先暂存、后激活**：新版本向量先以 `active=false` 写入隔离可重建索引，FTS在激活前不写入。全部切片成功后才激活新版本、清理旧版本并在MySQL事务中切换当前版本；失败或取消不影响旧发布版本。
29. **任务租约与断点恢复**：执行器以MySQL任务为权威，通过租约领取任务；过期租约可被其他执行器接管。成功任务项不会重复处理，失败项经显式重试回到待执行状态，确定性点ID保证upsert不增殖。
30. **正式索引保护**：阶段5自动化仅使用本地隔离Qdrant集合和临时FTS库。正式 `hotline_dispatch_v1`、正式FTS和839份历史原件不用于阶段5写入测试。

## 阶段6 知识管理前端决策（2026-09-04）

31. **已发布文档与草稿解耦**：新增、提交、驳回或取消后续版本时，不改变已有当前发布版本的文档状态和可检索性；只有新版本索引成功才切换发布指针。
32. **任务取消语义**：待执行或失败任务取消时立即进入 `canceled`；运行中任务通过 `cancel_requested` 在切片边界协作取消。
33. **前端与测试安全**：知识后台按权限隐藏操作但仍以服务端RBAC为准；错误展示隐藏路径和疑似凭据。阶段6闭环测试强制UTF-8、隔离Qdrant/FTS，并把test库记录及受控测试资产清理失败视为测试失败。
