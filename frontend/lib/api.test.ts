import { afterEach, describe, expect, it, vi } from "vitest";

import { analyzeWorkOrderText, ApiError } from "./api/client";
import type { Analysis, Citation, WorkOrder } from "./api/types";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const workOrder: WorkOrder = {
  id: "wo-1",
  source_case_id: null,
  title: "物业投诉",
  content: "物业不作为",
  request_type: null,
  address: null,
  source: null,
  event_time: null,
  actual_department_id: null,
  status: "new",
  metadata_json: {},
  created_at: "2026-09-07T00:00:00Z",
  updated_at: "2026-09-07T00:00:00Z",
};

const analysis: Analysis = {
  id: "a-1",
  work_order_id: "wo-1",
  conversation_id: null,
  model_provider: "mock",
  model_name: "mock-model",
  prompt_version: "v1",
  recommended_department_text: "住建部门",
  conclusion: "有依据结论",
  responsibility_boundary: null,
  confidence: 0.9,
  risk_warning: null,
  evidence_summary: null,
  created_at: "2026-09-07T00:00:01Z",
};

const citation: Citation = {
  id: "c-1",
  analysis_id: "a-1",
  knowledge_base_id: "historical_cases",
  evidence_id: "hc:e1",
  document_id: null,
  document_title: "历史案例标题",
  external_id: "HC-x",
  point_id: "p1",
  content_snapshot: "某历史工单内容",
  citation_type: "historical_cases",
  score: 0.8,
  metadata: { work_order_id: "wo-hist", source_case_id: "HC-x" },
  created_at: "2026-09-07T00:00:01Z",
};

afterEach(() => vi.unstubAllGlobals());

describe("analyzeWorkOrderText", () => {
  it("creates work order, analysis and fetches citations", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(workOrder, 201))
      .mockResolvedValueOnce(jsonResponse(analysis, 201))
      .mockResolvedValueOnce(jsonResponse([citation]));
    vi.stubGlobal("fetch", fetchMock);

    const result = await analyzeWorkOrderText("物业不作为");
    expect(result.workOrder.id).toBe("wo-1");
    expect(result.analysis.id).toBe("a-1");
    expect(result.citations[0].metadata.work_order_id).toBe("wo-hist");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(String(fetchMock.mock.calls[1][0])).toContain("/api/work-orders/wo-1/analyses");
  });

  it("wraps 503 as ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse({ detail: "LLM down" }, 503)));
    await expect(analyzeWorkOrderText("x")).rejects.toBeInstanceOf(ApiError);
  });
});
