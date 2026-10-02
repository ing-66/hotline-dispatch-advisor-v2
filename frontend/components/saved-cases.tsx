"use client";

import { useCallback, useEffect, useState } from "react";
import { BookmarkIcon, XIcon } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { api, ApiError } from "@/lib/api/client";
import type { Analysis, SavedCase, WorkOrder } from "@/lib/api/types";

export function SavedCases({ variant = "sidebar" }: { variant?: "header" | "sidebar" }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<SavedCase[] | null>(null);
  const [titles, setTitles] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<SavedCase | null>(null);
  const [order, setOrder] = useState<WorkOrder | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectSaved = useCallback(async (item: SavedCase) => {
    setSelected(item);
    setOrder(null);
    setAnalysis(null);
    setError(null);
    try {
      const workOrder = await api.getWorkOrder(item.work_order_id);
      setOrder(workOrder);
      setTitles((previous) => ({ ...previous, [workOrder.id]: workOrder.title }));
      if (item.analysis_id) {
        setAnalysis(await api.getAnalysis(item.analysis_id));
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "收藏详情加载失败");
    }
  }, []);

  const load = useCallback(async () => {
    setError(null);
    try {
      const page = await api.getSavedCases(1, 50);
      setItems(page.items);
      if (page.items.length > 0) {
        void selectSaved(page.items[0]);
      } else {
        setSelected(null);
        setOrder(null);
        setAnalysis(null);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "收藏加载失败");
    }
  }, [selectSaved]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const remove = async (id: string) => {
    setError(null);
    try {
      await api.deleteSavedCase(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "取消收藏失败");
    }
  };

  const trigger =
    variant === "header" ? (
      <PopoverTrigger
        render={
          <button
            type="button"
            aria-label="Saved cases"
            className="hover:bg-muted flex size-8 items-center justify-center rounded-full"
          >
            <BookmarkIcon className="size-4" />
          </button>
        }
      />
    ) : (
      <PopoverTrigger
        render={
          <button
            type="button"
            aria-label="Saved cases"
            className="hover:bg-muted flex h-8 w-fit items-center gap-2 rounded-md px-2.5 text-sm font-normal"
          >
            <BookmarkIcon className="size-4 shrink-0" />
            <span>收藏案例</span>
          </button>
        }
      />
    );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      {trigger}
      <PopoverContent
        side="right"
        align="start"
        sideOffset={10}
        className="h-[540px] w-[min(960px,calc(100vw-320px))] max-w-none overflow-hidden rounded-2xl p-0"
        style={{ padding: 0, gap: 0 }}
      >
        <div className="flex h-12 shrink-0 items-center justify-between border-b px-4">
          <div className="text-base font-medium">收藏案例</div>
          <button
            type="button"
            aria-label="Close saved cases"
            onClick={() => setOpen(false)}
            className="text-muted-foreground hover:bg-muted rounded-md p-1.5"
          >
            <XIcon className="size-4" />
          </button>
        </div>
        {error && <div className="border-b px-4 py-1.5 text-sm text-destructive">{error}</div>}
        <div className="grid min-h-0 flex-1 grid-cols-[280px_minmax(0,1fr)]">
          <div className="min-h-0 overflow-y-auto border-r">
            {items === null && <div className="px-3 py-4 text-sm text-muted-foreground">加载中…</div>}
            {items?.length === 0 && <div className="px-3 py-4 text-sm text-muted-foreground">还没有收藏案例</div>}
            <ul className="flex flex-col gap-0.5 p-2">
              {(items || []).map((item) => {
                const active = selected?.id === item.id;
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => void selectSaved(item)}
                      className={
                        active
                          ? "bg-muted flex w-full flex-col gap-1 rounded-lg px-3 py-2.5 text-start"
                          : "hover:bg-muted flex w-full flex-col gap-1 rounded-lg px-3 py-2.5 text-start"
                      }
                    >
                      <span className="truncate text-sm font-medium">
                        {titles[item.work_order_id] || item.work_order_id.slice(0, 8)}
                      </span>
                      <span className="truncate text-xs text-muted-foreground">
                        {item.created_at.slice(0, 10)} · {item.case_type}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
          <div className="min-h-0 overflow-y-auto px-6 py-5">
            {!selected && (
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                选择左侧收藏查看详情
              </div>
            )}
            {selected && order && (
              <div className="mx-auto max-w-3xl">
                <div className="flex items-start justify-between gap-3">
                  <h2 className="text-lg font-semibold leading-7">{order.title}</h2>
                  <button
                    type="button"
                    onClick={() => void remove(selected.id)}
                    className="text-muted-foreground hover:bg-muted shrink-0 rounded-md px-2 py-1 text-sm"
                  >
                    取消收藏
                  </button>
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
                  <div className="text-muted-foreground">状态：{order.status}</div>
                  <div className="text-muted-foreground">诉求类型：{order.request_type || "未标注"}</div>
                  <div className="text-muted-foreground">创建时间：{order.created_at.slice(0, 19).replace("T", " ")}</div>
                  <div className="text-muted-foreground">source_case_id：{order.source_case_id || "无"}</div>
                </dl>
                <h3 className="mt-6 text-sm font-medium text-muted-foreground">工单内容</h3>
                <p className="mt-2 whitespace-pre-wrap text-[15px] leading-7">{order.content}</p>
                {analysis && (
                  <>
                    <h3 className="mt-6 text-sm font-medium text-muted-foreground">关联研判</h3>
                    <div className="mt-2 rounded-xl border p-5">
                      <div className="mb-2 text-sm text-muted-foreground">
                        {analysis.created_at.slice(0, 19).replace("T", " ")}
                      </div>
                      <div className="mb-2 text-[15px] font-medium">
                        {analysis.recommended_department_text || "未给出建议部门"}
                      </div>
                      <p className="text-[15px] leading-7 text-muted-foreground whitespace-pre-wrap">
                        {analysis.conclusion}
                      </p>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
