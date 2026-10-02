# assistant-ui 前端接入 Business API 报告

日期：2026-09-07

## 结论

```text
assistant-ui前端接入结果：成功
```

## 保留的 assistant-ui 核心

- `AssistantRuntimeProvider` + `useLocalRuntime`（保留 Runtime）
- `ThreadPrimitive.Root / Viewport / Empty / Messages`
- `MessagePrimitive.Root / Parts`（默认 text 渲染 + 自定义 data part）
- `ComposerPrimitive.Root` 作为 Composer 容器

未自行重做 Sidebar/Thread/MessageBubble；结构化研判通过 assistant-ui 的
`data` part 渲染在 assistant 消息内。

## Composer 说明

assistant-ui 0.15 的 `ComposerPrimitive.Input/Send` 在当前 Runtime 组合下
isEditing/composer 状态不联动（按钮长期 disabled），因此保留 Composer Root，
消息提交改用受控输入 + `aui.thread.append`（仍走 assistant-ui 消息生命周期）。

## API Client 与类型

```text
frontend/lib/api/client.ts   # 统一 fetch，base=NEXT_PUBLIC_API_BASE_URL
frontend/lib/api/types.ts    # WorkOrder/Analysis/Citation/Feedback/SavedCase/Conversation/Message/PaginatedResponse
frontend/.env.example
```

业务组件：

```text
AnalysisResultCard：建议部门/结论/责任边界/风险/置信度/引用展开/反馈/收藏/历史案例抽屉
SidePanel：新建研判 / 历史研判 / 收藏案例
HistoryPanel：最近工单 + 多次研判列表 + 重新研判
SavedPanel：收藏列表 + 取消收藏
```

## 真实浏览器闭环

`frontend/scripts/verify_browser_loop.mjs`（Playwright + 本机 Chrome）完整执行：

```text
Composer 输入工单 → 真实 RAG → 真实 DeepSeek → AnalysisResultCard
→ Citation 展开 → historical_case 查看原工单 → Feedback → 收藏/取消/收藏
→ 历史研判 + 重新研判 → 收藏入口 → 1366×768 / 1920×1080
```

结果：PASS。截图保存在 `D:\热线派单系统V2-data\frontend-shots\`。

## 测试与构建

```text
frontend: vitest 5 passed（API Client + AnalysisResultCard，Mock API，不消耗模型）
frontend: next build PASS
backend:  pytest 41 passed（无回归）
```

## 遗留

- `ComposerPrimitive.Input/Send` 因库版本状态问题未直接使用，提交控件为最小替代；
- Conversation/Messages API 已封装但 UI 未使用（本阶段禁止新增聊天 Agent）；
- Saved 列表仅展示工单 ID/备注，未做完整收藏详情页；
- 依赖 CORS 仅允许本机 3000/127.0.0.1:3000，部署时需按环境扩展。
