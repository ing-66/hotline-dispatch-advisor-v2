# assistant-ui 原版 Starter 恢复报告

日期：2026-09-08

## 结论

```text
assistant-ui原版恢复结果：成功
```

## 推翻的内容

上一版“热线研判工作台”（自定义 Sidebar、新建/历史/收藏导航、自定义 Header、
底部大 Textarea、自定义 AnalysisResultCard）已整体移除，相关页面文件已删除：

```text
app/chat.tsx
app/style.css
components/SidePanel.tsx
components/AnalysisResultCard.tsx
```

## 原版来源

在 `D:\assistant-ui-reference` 用官方 CLI 生成 default Starter Template：

```powershell
npx assistant-ui@latest create assistant-ui-reference --template default --use-npm
npx assistant-ui add thread threadlist-sidebar
npx shadcn add sidebar separator breadcrumb tooltip
```

随后将原版 `app/`、`components/`、`hooks/`、`globals.css`、Tailwind 配置迁入
当前 `frontend`，确认与原版截图一致后再接入业务。

## 保留的业务代码

```text
frontend/lib/api/client.ts
frontend/lib/api/types.ts
frontend/lib/api.test.ts
frontend/.env.example（NEXT_PUBLIC_API_BASE_URL）
```

## 原版恢复内容

```text
assistant-ui Logo / New Thread / Thread List
Sidebar + GitHub + View Source
Header + Breadcrumb（Build Your Own ChatGPT UX > Starter Template）
How can I help you today?
Send a message... 原版 Composer 与发送按钮
```

## Runtime 与 Business API

保留 `AssistantRuntimeProvider + useLocalRuntime(ChatModelAdapter)`：

```text
Composer Submit
→ POST /api/work-orders
→ POST /api/work-orders/{id}/analyses
→ GET /api/analyses/{id}/citations
→ Markdown 转成原生 assistant message
```

结果以 Markdown 显示：建议承办单位、研判结论、责任边界、风险提示、置信度、
依据列表（历史案例保留工单号）。

## 验证

```text
frontend npm run build：PASS
frontend npm test：2 passed（API Client，Mock，不耗真实模型）
backend pytest -q：41 passed
真实浏览器（原版 Composer → 真实 RAG + DeepSeek → 原生 Message）：PASS
```

截图：

```text
D:\热线派单系统V2-data\frontend-shots\starter\initial-1366.png
D:\热线派单系统V2-data\frontend-shots\starter\initial-1920.png
D:\热线派单系统V2-data\frontend-shots\starter\result-message.png
```
