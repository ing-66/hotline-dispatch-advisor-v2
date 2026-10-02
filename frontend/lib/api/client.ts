import type {
  Analysis,
  AnalysisResultBundle,
  Citation,
  Conversation,
  Feedback,
  Message,
  PaginatedResponse,
  SavedCase,
  WorkOrder,
} from "./types";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly body?: unknown,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
  } catch {
    throw new ApiError("Business API 不可用，请检查服务是否已启动。", 0);
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!response.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    throw new ApiError(detail ? String(detail) : `HTTP ${response.status}`, response.status, body);
  }
  return body as T;
}

const json = (method: string) => <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const api = {
  getWorkOrders: (params: Record<string, string | number | undefined> = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== "") query.set(key, String(value));
    });
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<PaginatedResponse<WorkOrder>>(`/api/work-orders${suffix}`);
  },
  getWorkOrder: (id: string) => request<WorkOrder>(`/api/work-orders/${id}`),
  createWorkOrder: (payload: { title: string; content: string; request_type?: string }) =>
    json("POST")<WorkOrder>("/api/work-orders", payload),
  createAnalysis: (workOrderId: string) =>
    json("POST")<Analysis>(`/api/work-orders/${workOrderId}/analyses`, {}),
  getAnalyses: (workOrderId: string, page = 1, pageSize = 20) =>
    request<PaginatedResponse<Analysis>>(
      `/api/work-orders/${workOrderId}/analyses?page=${page}&page_size=${pageSize}`,
    ),
  getAnalysis: (analysisId: string) => request<Analysis>(`/api/analyses/${analysisId}`),
  getCitations: (analysisId: string) =>
    request<Citation[]>(`/api/analyses/${analysisId}/citations`),
  createFeedback: (analysisId: string, payload: {
    feedback_type: string;
    adopted?: boolean | null;
    comment?: string | null;
  }) => json("POST")<Feedback>(`/api/analyses/${analysisId}/feedback`, payload),
  getFeedback: (analysisId: string) =>
    request<Feedback[]>(`/api/analyses/${analysisId}/feedback`),
  getSavedCases: (page = 1, pageSize = 50) =>
    request<PaginatedResponse<SavedCase>>(`/api/saved-cases?page=${page}&page_size=${pageSize}`),
  createSavedCase: (payload: { work_order_id: string; analysis_id?: string | null; note?: string | null }) =>
    json("POST")<SavedCase>("/api/saved-cases", payload),
  deleteSavedCase: (id: string) => json("DELETE")<void>(`/api/saved-cases/${id}`),
  getConversations: (page = 1, pageSize = 20) =>
    request<PaginatedResponse<Conversation>>(`/api/conversations?page=${page}&page_size=${pageSize}`),
  createConversation: (title: string) => json("POST")<Conversation>("/api/conversations", { title }),
  updateConversation: (conversationId: string, payload: { title?: string; status?: string }) =>
    json("PATCH")<Conversation>(`/api/conversations/${conversationId}`, payload),
  getMessages: (conversationId: string) =>
    request<Message[]>(`/api/conversations/${conversationId}/messages`),
  addMessage: (conversationId: string, role: string, content: string) =>
    json("POST")<Message>(`/api/conversations/${conversationId}/messages`, { role, content }),
};

export type AnalysisStreamEvent =
  | { type: "phase"; phase: string; message: string }
  | { type: "field"; field: string; value: unknown }
  | { type: "done"; analysis: Analysis; citations: Citation[] }
  | { type: "error"; message: string };

async function streamAnalysis(
  workOrderId: string,
  onEvent: (event: AnalysisStreamEvent) => void,
): Promise<{ analysis: Analysis; citations: Citation[] }> {
  const response = await fetch(`${API_BASE}/api/work-orders/${workOrderId}/analyses/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({}),
  });
  if (!response.ok || !response.body) throw new ApiError(`HTTP ${response.status}`, response.status);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed: { analysis: Analysis; citations: Citation[] } | null = null;
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";
    for (const frame of frames) {
      const data = frame.split("\n").filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim()).join("\n");
      if (!data) continue;
      const event = JSON.parse(data) as AnalysisStreamEvent;
      onEvent(event);
      if (event.type === "error") throw new ApiError(event.message, 503);
      if (event.type === "done") completed = { analysis: event.analysis, citations: event.citations };
    }
    if (done) break;
  }
  if (!completed) throw new ApiError("流式响应未正常完成", 503);
  return completed;
}

export async function analyzeWorkOrderText(
  text: string,
  onEvent?: (event: AnalysisStreamEvent) => void,
): Promise<AnalysisResultBundle> {
  const title = text.trim().split("\n")[0]?.slice(0, 40) || "新工单";
  const workOrder = await api.createWorkOrder({ title, content: text.trim(), request_type: "求助" });
  let analysis: Analysis;
  let citations: Citation[];
  if (onEvent) {
    ({ analysis, citations } = await streamAnalysis(workOrder.id, onEvent));
  } else {
    analysis = await api.createAnalysis(workOrder.id);
    citations = await api.getCitations(analysis.id);
  }
  return { workOrder, analysis, citations };
}
