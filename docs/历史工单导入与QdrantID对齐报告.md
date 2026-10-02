# 历史工单导入与 MySQL/Qdrant ID 对齐报告

日期：2026-09-07

## 结论

```text
历史工单与 Qdrant ID 对齐结果：成功
```

本阶段完成了：

- MySQL `work_orders` 导入 5,143 条真实历史工单（幂等验证通过）。
- Qdrant `hotline_dispatch_v2` 中 5,143 个 `historical_case` Point 补齐
  `work_order_id`、`source_case_id`、`knowledge_type`。
- 双向追溯与 RAG 引用回查真实链路验证通过。

## 1. 数据来源

原始资料位于 V2 工作区：

```text
assets/knowledge-source/03_历史工单案例\
├─ 举报__拆分   667 个
├─ 咨询__拆分  1,928 个
├─ 建议__拆分   356 个
├─ 投诉__拆分  1,703 个
└─ 求助__拆分   489 个
```

合计 5,143 个案例文件；原始聚合文档位于
`assets/knowledge-original/C. 历史案例库/官方工单案例/`（举报/咨询/建议/投诉/求助
5 个 Markdown）。Qdrant `historical_case` 由这些资料的检索切片生成，共 5,148 个
Point：5,143 个对应真实案例，另有 5 个是每类文档的标题头 Point。

## 2. 原始编号核查

对全部原始资料检索以下字段：工单编号、工单号、受理编号、流水号、案件编号等。

结果：**原始资料不存在任何稳定工单编号**。因此不能“直接沿用原编号”。

`source_case_id` 采用确定性 fallback 方案，不随机生成：

```text
source_case_id = HC-<诉求类型>-<10位十六进制>
```

其中 10 位十六进制取自源文件名自带的内容哈希前缀，该前缀经全量校验等于
源文件完整内容的 `sha256` 前 10 位（5,143/5,143 通过）。同一案例重复执行导入
会得到相同 `source_case_id`。

说明：这是内容派生的稳定标识，不是原始业务部门签发的工单号。未来如果获得
权威工单号来源，应新增字段映射任务再统一替换，不影响已建关联。

## 3. 字段映射（work_orders）

| work_orders 字段 | 来源 |
|---|---|
| `source_case_id` | `HC-<诉求类型>-<源文件名哈希前10位>` |
| `title` | 案例标题（`## ` 一级小标题，长度 ≤300） |
| `content` | `【事项内容】` 正文 |
| `request_type` | `【诉求类型】`，并与目录类型交叉校验 |
| `source` | `广州12345历史工单官方案例` |
| `event_time` | `【留言时间】` 解析为 datetime |
| `status` | `completed` |
| `actual_department_id` | 按第 4 节规则映射；无法映射为 NULL |
| `metadata_json` | 源文件路径、源序号、文件/正文 sha256、原始承办单位等 |

5,143 条均成功解析：无空正文、无空标题、无重复 `source_case_id`、时间范围
2019-01-08 ~ 2026-08-18。

## 4. 部门映射

原则：部门主数据只来自 V2 既有权威知识资产，**不从历史案例自由生成**；
无法可靠映射的一律置 NULL 并进入异常清单，不猜测、不伪造。

### 主数据来源与规模

从 `01_机构职责`、`02_权责清单` 资产中仅保留带明确白云区限定的实体，
共注册 26 条 `departments`：

- 02 权责清单中的白云区部门全称（含广州市/白云区限定）；
- 01 镇街资料中可证实的一条镇街实体：`广州市白云区人民政府-江高镇`。

01 镇街拆分资料中其余文件顶部标题存在重复/错位（大量文件首行均为“江高镇”，
正文却出现人和镇等），未达到可证实标准，因此未纳入主数据。

### 匹配规则（保守，防跨区错配）

1. 规范化后精确匹配；
2. 去掉可选的“广州市”前缀后精确匹配（仅在名称含“白云区”时生效）；
3. `白云区人民政府/白云区政府 - <镇街>` 后缀匹配已注册的白云区镇街实体。

结果：

```text
5,143 条中 5 条可映射（均指向 广州市白云区人民政府-江高镇）
其余 5,138 条保留 actual_department_id = NULL，原始名称进入异常清单
```

未映射原因主要为：原始承办单位为市级部门简称、其他行政区部门/镇街、
企业（供电/供水/地铁/排水公司等）、`广州政务` 平台主体，以及现有知识资产
未覆盖的部门；另有 5 个“无部门”案例。完整清单见
`D:\热线派单系统V2-data\historical-import\import_apply.json` 的
`unmapped_raw_sample` 与异常相关统计。

## 5. 幂等性

```text
第一次执行：inserted=5,143
第二次执行：inserted=0，skipped_existing=5,143
```

以 `source_case_id` 为唯一识别键；当前 Schema 中该列为普通索引而非唯一约束，
导入程序自身保证不重复插入。

## 6. Qdrant 同步

只更新 payload metadata，未重新 Embedding、未改 Vector、未改 Point ID、
未重建 Collection、未改检索算法。

同步结果：

```text
Qdrant historical_case Point 总数：5,148
成功补充 work_order_id + source_case_id：5,143
未关联（文档标题头 Point，无业务事实）：5
```

每个真实案例 Point 新增：

```text
knowledge_type = historical_case
work_order_id  = <work_orders.id>
source_case_id = <work_orders.source_case_id>
```

5 个文档标题头 Point 只标注 `knowledge_type=historical_case` 与
`document_header=true`，不写入业务 ID。

同步脚本：`scripts/sync_historical_cases_to_qdrant.py`（默认 dry-run，`--apply`
写入；支持重复执行）。

## 7. 引用链路

Knowledge API `/retrieval` 现在会把 payload 中的 `knowledge_type`、
`work_order_id`、`source_case_id` 放回 record metadata；
`QdrantKnowledgeAdapter` 保留这些字段并把 `source_case_id` 作为
`case_id`/`external_id` 的回查键。`AnalysisService` 落库时整份 metadata 进入
`answer_citations.metadata_json`，因此引用快照可回查原始历史工单。

## 8. 验证结果

| 验证项 | 结果 |
|---|---|
| MySQL `work_orders` 总数 | 5,143 |
| `source_case_id` 重复 | 0 |
| 空正文/空标题/非 completed | 0 |
| 中文内容 | PASS |
| `departments` 主数据 | 26 条（权威资产来源） |
| 可映射 `actual_department_id` | 5 条；其余 5,138 条 NULL（异常清单） |
| Qdrant historical_case | 5,148（5,143 已关联 + 5 文档头） |
| Qdrant→MySQL 抽查 20 条 | PASS |
| MySQL→Qdrant 抽查 20 条 | PASS |
| RAG 引用→answer_citations→work_order_id→MySQL | PASS |
| `pytest -q` | 18 passed |
| `verify_mysql.py` | PASS |
| `verify_qdrant.py` | PASS（`historical_case_id=True`） |

## 9. 脚本清单

```text
scripts/analyze_historical_case_sources.py        # 只读全量映射分析
scripts/import_department_master.py               # 部门主数据（幂等）
scripts/import_historical_work_orders.py          # 工单导入（幂等，默认 dry-run）
scripts/sync_historical_cases_to_qdrant.py        # Qdrant payload 同步
scripts/verify_case_alignment.py                  # 双向追溯 + RAG 引用验证
```

## 10. 异常与遗留

1. 原始历史案例无权威工单编号，`source_case_id` 为内容派生的确定性 fallback；
   获得权威编号后应做映射迁移。
2. 5 个文档标题头 Point 无法关联业务工单，已标记 `document_header=true`，
   检索仍可能命中，后续如需可考虑在 Knowledge API 过滤或单独处理。
3. 部门主数据仅覆盖知识资产可证实的白云区实体，5,138 条历史工单暂无
   `actual_department_id`；补齐全市部门主数据属于独立数据工程任务。
4. Qdrant 中没有“只有检索副本、找不到原始工单”的案例（全部 5,143 个案例
   均有 MySQL 行）；5 个标题头不属于案例。
5. 未新增 `historical_cases` 表；`saved_cases`、`answer_citations` 职责未变。

## 11. 运行产物

中间报告与 JSON 快照保存在 `D:\热线派单系统V2-data\historical-import\`：

```text
analysis.json / import_dryrun*.json / import_apply.json / import_repeat.json
department_master_dryrun.json / department_master_apply.json
department_coverage.json
sync_dryrun.json / sync_apply.json / sync_final.json
```

这些 JSON 不包含数据库密码或 API Key。
