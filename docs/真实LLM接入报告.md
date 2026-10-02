# 真实 LLM Adapter 接入报告

日期：2026-09-07

## 结论

```text
真实LLM接入结果：成功
```

## 1. 使用的真实模型

- 供应商：DeepSeek（OpenAI-compatible `chat/completions`）
- 端点：`https://api.deepseek.com`（来自 V2 `.env`）
- 模型：`deepseek-v4-flash`
- 模式：`LLM_GATEWAY_MODE=real`

真实 API Key 只存放在 V2 本地 `.env`（已 gitignore），本报告不含任何密钥。

## 2. Adapter 位置

```text
backend/gateways/real_llm.py
├─ OpenAICompatibleLLMAdapter（LLMGateway 实现）
├─ LLMGatewayError 及子类
└─ 结构化输出解析/校验
```

供应商切换只发生在 Gateway 层；`AnalysisService` 只依赖 `LLMGateway` 契约，
未绑定 DeepSeek/OpenAI SDK。

## 3. 配置

`.env` / `.env.example` 新增：

```text
LLM_GATEWAY_MODE=mock|real
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
LLM_TIMEOUT=
LLM_TEMPERATURE=
LLM_MAX_TOKENS=
```

默认 `.env` 保持 `LLM_GATEWAY_MODE=mock`，避免日常测试误消耗模型额度；
`scripts/verify_llm.py` 显式以 `real` 模式运行。

## 4. 契约与边界

- `LLMGateway.analyze` 输入/输出类型未改变；
- `AnalysisService` 的非法 `evidence_id` 拒绝规则原样保留；
- `MockLLMGateway` 未删除；
- `real` 模式任何失败都抛统一 `LLMGatewayError`，**绝不静默回退 Mock**；
- Adapter 只接收 `KnowledgeGateway.search` 产生的 `RetrievalResult` Evidence Pack，
  不接触 Qdrant/Knowledge API 原始结构。

## 5. 输入与 Evidence Pack

模型输入包含工单标题/正文、`prompt_version` 和受控 Evidence Pack。正文中由
Knowledge API 加进去的 `【证据ID：E1】`、`【文件名：…】` 标记会在送入模型前
清洗，避免模型把 E 序号误当引用键；可用引用键只有方括号中的真实
`evidence_id`。

Evidence Pack 继续受 `top_k` 约束，不把知识库全量塞给模型。

## 6. 结构化输出与校验

请求使用 `response_format={"type":"json_object"}`，并要求模型只输出 JSON。
输出必须经过：

```text
解析（去 Markdown 代码块/截断容错）
→ 必填字段检查
→ 类型检查
→ confidence 0~1 检查
→ evidence_id 白名单校验
→ AnalysisResult 映射
```

字段以当前 `backend/gateways/contracts.py::AnalysisResult` 为准：
`recommended_department/conclusion/citation_references/responsibility_boundary/
confidence/risk_warning`。政策依据、历史案例分析、协商参考等按系统提示归纳进
`conclusion`，未擅自扩展领域字段。

依据不足时，模型必须把 `recommended_department` 输出为
“依据不足，建议人工复核”、`conclusion` 以“依据不足”开头、`confidence=0`。

## 7. 错误处理与重试

统一错误类型（均继承 `LLMGatewayError`）：

- 未配置 Key/模型 → `LLMConfigurationError`
- 401/403 → `LLMAuthenticationError`
- 404 → `LLMModelNotFoundError`
- 429 → `LLMRateLimitError`
- 连接失败 → `LLMConnectionError`
- 超时 → `LLMTimeoutError`
- 5xx → `LLMServerError`
- 空回答/非法 JSON → `LLMResponseError`
- Schema/非法引用 → `LLMValidationError`

仅对“空回答、429、5xx、瞬时网络错误”做一次显式重试，仍失败则抛出受控错误；
不会切到 Mock。

## 8. 记录真实模型元数据

`AnalysisService` 通过 Gateway 通用属性读取 `provider` 与 `model_name` 写入
`analysis_records`，本次真实运行记录为：

```text
model_provider = deepseek
model_name     = deepseek-v4-flash
```

未为此扩展数据库表。

## 9. document_header 检索卫生

Knowledge API 检索在 dense 与 lexical 两条路径统一排除
`document_header=true`，5 个标题 Point 不再进入 Evidence Pack（未删除 Point、
未改 Vector/ID）。已在知识服务层验证，并加入回归脚本断言。

## 10. 真实链路验证

`scripts/verify_llm.py`（真实模型，非 Mock）共执行：

```text
7 条代表性工单 × 真实 RAG + 真实模型研判
+ 第 1 条工单追加第 2 次真实研判
```

覆盖：物业、劳动工资、市场监管、城市管理/占道噪声、公共设施/电梯、
职责边界模糊、历史案例引用。

结果：

| 用例 | 结果 |
|---|---|
| 物业/公共区域卫生 | PASS（模型判为依据不足，未虚构部门） |
| 劳动工资 | PASS（人力社保部门，conf=0.9） |
| 市场监管 | PASS（市场监管部门，conf=0.9） |
| 占道/噪声/油烟 | PASS（白云区城管/街道等，conf=0.7） |
| 电梯/特种设备 | PASS（市场监管/特种设备，conf=0.9） |
| 职责边界模糊 | PASS（规划自然资源等，conf=0.8） |
| 历史案例引用 | PASS（模型判为依据不足，但引用历史案例证据可追溯） |

每次研判均落库并重读 `analysis_records` 与 `answer_citations`；引用快照
保存了真实检索原文。

## 11. 同工单多次研判

同一 `work_order` 连续执行两次真实研判：

```text
analysis_records = 2 条独立记录（不同 id）
answer_citations = 各自独立引用快照（5 + 5）
无覆盖
```

## 12. 历史案例追溯

模型引用了 `historical_case` 证据后，

```text
answer_citations.metadata_json.work_order_id
→ MySQL work_orders
→ 找到原始历史工单（source_case_id 一致）
```

验证 PASS。

## 13. 回归

```text
pytest -q                    31 passed（新增 RealLLM Adapter 13 项 + 原 18 项）
verify_mysql.py             PASS
verify_qdrant.py            PASS
verify_case_alignment.py    PASS
verify_knowledge_service.py PASS（含 document_header 排除断言）
verify_llm.py               PASS
```

普通 pytest 全部使用 MockTransport/内存 SQLite，不消耗真实模型额度。

## 14. 遗留问题

- 少数组件（如物业卫生、外墙脱落类）模型按“依据不足”拒绝硬判，符合要求，
  但说明现有知识对部分场景召回仍偏弱，属于后续知识建设范围。
- 响应中 `request_id/token usage` 已由供应商返回，但当前 schema 未保存，
  仅日志可见；未扩展表。
- 实际使用的 `deepseek-v4-flash` 配置来自本机旧项目的运行配置；如需正式化，
  建议由用户在正式环境中配置生产 Key 与限流策略。
