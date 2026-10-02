"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  type ExternalStoreAdapter,
  type ThreadMessageLike,
  useExternalStoreRuntime,
  type AssistantRuntime,
} from "@assistant-ui/react";

import { api, ApiError } from "@/lib/api/client";
import type { Conversation } from "@/lib/api/types";
import { analyzeWorkOrderText, type AnalysisStreamEvent } from "@/lib/api/client";
import type { AnalysisResultBundle } from "@/lib/api/types";

type UiMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: Date;
  business?: { analysisId: string; workOrderId: string };
};

let localId = 0;
const nextId = () => `local-${Date.now()}-${localId++}`;
function like(message: UiMessage): ThreadMessageLike {
  const base: ThreadMessageLike = {
    id: message.id,
    role: message.role,
    content: [{ type: "text", text: message.content }],
    createdAt: message.createdAt,
  };
  if (message.role === "assistant") {
    const assistantParts = [
      { type: "text", text: message.content },
      ...(message.business
        ? [{ type: "data", name: "analysis_actions", data: message.business }]
        : []),
    ];
    return {
      ...base,
      content: assistantParts as ThreadMessageLike["content"],
      status: { type: "complete", reason: "stop" },
    };
  }
  return base;
}

function textFromAppend(message: {
  content?: readonly { type?: string; text?: string }[];
}): string {
  return (message.content || [])
    .filter((part): part is { type: string; text: string } => part.type === "text" && Boolean(part.text))
    .map((part) => part.text)
    .join("\n")
    .trim();
}

function formatAnalysis(result: AnalysisResultBundle): string {
  const { analysis } = result;
  const details = Array.isArray(analysis.recommended_departments_json)
    ? analysis.recommended_departments_json
    : [];
  const roleUnit = (role: string) => details.find((item) => item.role === role)?.unit || "";
  const roleValues = (role: string) => details
    .filter((item) => item.role === role)
    .map((item) => item.unit || item.value || "")
    .filter(Boolean);
  const firstDispatch = roleUnit("first_dispatch") || analysis.recommended_department_text || "暂不确定";
  const authority = roleUnit("competent_authority") || "暂不确定";
  const collaborators = roleValues("collaborating");
  const status = details.find((item) => item.role === "decision_status")?.value || "needs_fact_check";
  const missingFacts = roleValues("missing_fact");
  const lines: string[] = [];
  lines.push("【建议承办单位】");
  lines.push(`建议首派：**${firstDispatch}**`);
  lines.push(`业务主管：**${authority}**`);
  lines.push(`协同单位：${collaborators.length ? collaborators.join("、") : "无明确协同单位"}`);
  lines.push("", "【决策状态】", status);
  const confidence = analysis.confidence == null ? 0 : Math.round(analysis.confidence * 100);
  lines.push("", "【AI置信度】", `**${confidence}%**`);
  lines.push("", "【直接职责依据】");
  if (analysis.evidence_summary) {
    lines.push(analysis.evidence_summary);
  } else {
    lines.push("- 本次未召回可直接证明承办职责的原文依据；历史案例仅供内部参考，不作为直接职责依据展示。");
  }
  lines.push("", "【待核实条件】");
  lines.push(...(missingFacts.length ? missingFacts.map((fact) => `- ${fact}`) : ["- 无"]));
  lines.push("", "【研判说明】", analysis.conclusion);
  if (analysis.responsibility_boundary) lines.push("", "【责任边界】", analysis.responsibility_boundary);
  if (analysis.risk_warning) lines.push("", "【风险提示】", analysis.risk_warning);
  lines.push("", "【使用提示】本意见仅供人工复核。");
  return lines.join("\n");
}

function formatStreamingFields(fields: Record<string, unknown>, phaseMessage: string): string {
  const lines = [`⏳ ${phaseMessage}`];
  const text = (key: string) => typeof fields[key] === "string" ? String(fields[key]) : "";
  const list = (key: string) => Array.isArray(fields[key]) ? (fields[key] as unknown[]).map(String) : [];
  if (text("recommended_department")) {
    lines.push("", "【建议承办单位】", `建议首派：**${text("recommended_department")}**`);
    if (text("competent_authority")) lines.push(`业务主管：**${text("competent_authority")}**`);
    if (fields.collaborating_units !== undefined) {
      const units = list("collaborating_units");
      lines.push(`协同单位：${units.length ? units.join("、") : "无明确协同单位"}`);
    }
  }
  if (text("decision_status")) lines.push("", "【决策状态】", text("decision_status"));
  if (typeof fields.confidence === "number") {
    lines.push("", "【AI置信度】", `**${Math.round(Number(fields.confidence) * 100)}%**`);
  }
  // Evidence is shown only after server-side source attribution and quote
  // validation; raw model fields must not display an unattributed quotation.
  if (fields.missing_facts !== undefined) {
    const facts = list("missing_facts");
    lines.push("", "【待核实条件】", ...(facts.length ? facts.map((fact) => `- ${fact}`) : ["- 无"]));
  }
  if (text("conclusion")) lines.push("", "【研判说明】", text("conclusion"));
  if (text("responsibility_boundary")) lines.push("", "【责任边界】", text("responsibility_boundary"));
  if (text("risk_warning")) lines.push("", "【风险提示】", text("risk_warning"));
  return lines.join("\n");
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return "Business API 不可用，请稍后重试。";
    if (error.status === 503) return "AI 服务暂时不可用，请稍后重试。";
    return error.message;
  }
  return "请求失败，请稍后重试。";
}

export function useBusinessRuntime(): AssistantRuntime {
  const [conversations, setConversations] = useState<Conversation[] | null>(null);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const activeRef = useRef<string | null>(null);
  activeRef.current = activeThreadId;

  const refreshConversations = useCallback(async () => {
    try {
      const page = await api.getConversations(1, 100);
      setConversations(page.items);
    } catch {
      setConversations([]);
    }
  }, []);

  useEffect(() => {
    void refreshConversations();
  }, [refreshConversations]);

  const mapBackendMessages = useCallback((backendMessages: import("@/lib/api/types").Message[]): UiMessage[] => {
    return backendMessages.map((message) => ({
      id: `backend-${message.id}`,
      role: message.role === "user" ? "user" : "assistant",
      content: message.content,
      createdAt: new Date(message.created_at),
    }));
  }, []);

  const patchConversation = useCallback((conversationId: string, changes: Partial<Conversation>) => {
    setConversations((previous) =>
      changes.status === "deleted"
        ? (previous || []).filter((item) => item.id !== conversationId)
        : (previous || []).map((item) => (item.id === conversationId ? { ...item, ...changes } : item)),
    );
  }, []);

  const store: ExternalStoreAdapter<UiMessage> = {
    messages,
    setMessages: (next) => setMessages([...(next as UiMessage[])]),
    isRunning,
    convertMessage: (message) => like(message),
    onNew: async (message) => {
      const text = textFromAppend(message);
      if (!text || isRunning) return;
      setIsRunning(true);
      const userMessage: UiMessage = {
        id: nextId(),
        role: "user",
        content: text,
        createdAt: new Date(),
      };
      setMessages((previous) => [...previous, userMessage]);
      let streamingId: string | null = null;

      try {
        let conversationId = activeRef.current;
        if (!conversationId) {
          const title = text.split("\n")[0]?.slice(0, 40) || "New Chat";
          const created = await api.createConversation(title);
          conversationId = created.id;
          setActiveThreadId(conversationId);
          setConversations((previous) => [created, ...(previous || [])]);
        }
        await api.addMessage(conversationId, "user", text);
        streamingId = nextId();
        const activeStreamingId = streamingId;
        setMessages((previous) => [
          ...previous,
          {
            id: activeStreamingId,
            role: "assistant",
            content: "⏳ 正在提交工单…",
            createdAt: new Date(),
          },
        ]);
        const partialFields: Record<string, unknown> = {};
        let phaseMessage = "正在提交工单…";
        const onStreamEvent = (event: AnalysisStreamEvent) => {
          if (event.type === "phase") phaseMessage = event.message;
          if (event.type === "field") partialFields[event.field] = event.value;
          if (event.type === "phase" || event.type === "field") {
            const content = formatStreamingFields(partialFields, phaseMessage);
            setMessages((previous) => previous.map((item) =>
              item.id === activeStreamingId ? { ...item, content } : item,
            ));
          }
        };
        const result = await analyzeWorkOrderText(text, onStreamEvent);
        const markdown = formatAnalysis(result);
        const finalMessage: UiMessage = {
          id: nextId(),
          role: "assistant",
          content: markdown,
          createdAt: new Date(),
          business: {
            analysisId: result.analysis.id,
            workOrderId: result.workOrder.id,
          },
        };
        await api.addMessage(conversationId, "assistant", markdown);
        setMessages((previous) => previous.map((message) =>
          message.id === activeStreamingId ? finalMessage : message,
        ));
      } catch (error) {
        const failed: UiMessage = {
          id: nextId(),
          role: "assistant",
          content: errorText(error),
          createdAt: new Date(),
        };
        setMessages((previous) => streamingId
          ? previous.map((message) => message.id === streamingId ? failed : message)
          : [...previous, failed]);
      } finally {
        setIsRunning(false);
        void refreshConversations();
      }
    },
    adapters: {
      threadList: {
        threadId: activeThreadId ?? undefined,
        isLoading: conversations === null,
        threads: (conversations || [])
          .filter((conversation) => conversation.status !== "archived")
          .map((conversation) => ({
            id: conversation.id,
            status: "regular" as const,
            title: conversation.title,
          })),
        archivedThreads: (conversations || [])
          .filter((conversation) => conversation.status === "archived")
          .map((conversation) => ({
            id: conversation.id,
            status: "archived" as const,
            title: conversation.title,
          })),
        onSwitchToNewThread: async () => {
          setActiveThreadId(null);
          setMessages([]);
        },
        onSwitchToThread: async (threadId) => {
          setActiveThreadId(threadId);
          setMessages([]);
          const backendMessages = await api.getMessages(threadId);
          setMessages(mapBackendMessages(backendMessages));
        },
        onRename: async (threadId, newTitle) => {
          await api.updateConversation(threadId, { title: newTitle });
          patchConversation(threadId, { title: newTitle });
        },
        onArchive: async (threadId) => {
          await api.updateConversation(threadId, { status: "archived" });
          patchConversation(threadId, { status: "archived" });
        },
        onUnarchive: async (threadId) => {
          await api.updateConversation(threadId, { status: "active" });
          patchConversation(threadId, { status: "active" });
        },
        onDelete: async (threadId) => {
          await api.updateConversation(threadId, { status: "deleted" });
          patchConversation(threadId, { status: "deleted" });
        },
      },
    },
  };

  return useExternalStoreRuntime(store);
}
