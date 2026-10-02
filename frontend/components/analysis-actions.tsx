"use client";

import { useState } from "react";
import { useAssistantDataUI } from "@assistant-ui/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api/client";

type AnalysisActionData = {
  analysisId: string;
  workOrderId: string;
};

function AnalysisActionBar({ data }: { data: AnalysisActionData }) {
  const [comment, setComment] = useState("");
  const [savedId, setSavedId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const feedback = async (adopted: boolean) => {
    setError(null);
    setMessage(null);
    try {
      await api.createFeedback(data.analysisId, {
        feedback_type: adopted ? "adopt" : "reject",
        adopted,
        comment: comment.trim() || null,
      });
      setMessage(adopted ? "已记录：采纳" : "已记录：不采纳");
      setComment("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "反馈提交失败");
    }
  };

  const favorite = async () => {
    setError(null);
    setMessage(null);
    try {
      if (savedId) {
        await api.deleteSavedCase(savedId);
        setSavedId(null);
        setMessage("已取消收藏");
      } else {
        const saved = await api.createSavedCase({
          work_order_id: data.workOrderId,
          analysis_id: data.analysisId,
          note: "AI 研判收藏",
        });
        setSavedId(saved.id);
        setMessage("已收藏");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "收藏操作失败");
    }
  };

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
      <Button variant="secondary" size="sm" onClick={() => void feedback(true)}>
        采纳
      </Button>
      <Button variant="secondary" size="sm" onClick={() => void feedback(false)}>
        不采纳
      </Button>
      <Input
        value={comment}
        onChange={(event) => setComment(event.target.value)}
        placeholder="备注（可选）"
        className="h-8 w-56"
      />
      <Button variant="ghost" size="sm" onClick={() => void favorite()}>
        {savedId ? "★ 已收藏" : "☆ 收藏"}
      </Button>
      {message && <span className="text-muted-foreground">{message}</span>}
      {error && <span className="text-destructive">{error}</span>}
    </div>
  );
}

export function AnalysisActionsRegistry() {
  useAssistantDataUI({
    name: "analysis_actions",
    render: ({ data }) => <AnalysisActionBar data={data as AnalysisActionData} />,
  });
  return null;
}
