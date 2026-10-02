"use client";

import { useCallback, useEffect, useState } from "react";
import { ClipboardListIcon, XIcon } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { api, ApiError } from "@/lib/api/client";
import type { Analysis, WorkOrder } from "@/lib/api/types";

export function WorkOrderHistory({ variant = "sidebar" }: { variant?: "header" | "sidebar" }) {
  const [open, setOpen] = useState(false);
  const [orders, setOrders] = useState<WorkOrder[] | null>(null);
  const [selected, setSelected] = useState<WorkOrder | null>(null);
  const [analyses, setAnalyses] = useState<Analysis[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectOrder = useCallback(async (order: WorkOrder) => {
    setSelected(order);
    setAnalyses(null);
    setError(null);
    try {
      const page = await api.getAnalyses(order.id, 1, 100);
      setAnalyses(page.items);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "研判记录加载失败");
    }
  }, []);

  const load = useCallback(async () => {
    setError(null);
    try {
      const page = await api.getWorkOrders({ page: 1, page_size: 50 });
      setOrders(page.items);
      if (page.items.length > 0) {
        void selectOrder(page.items[0]);
      } else {
        setSelected(null);
        setAnalyses([]);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "工单加载失败");
    }
  }, [selectOrder]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const trigger =
    variant === "header" ? (
      <PopoverTrigger
        render={
          <button
            type="button"
            aria-label="Work order history"
            className="hover:bg-muted flex size-8 items-center justify-center rounded-full"
          >
            <ClipboardListIcon className="size-4" />
          </button>
        }
      />
    ) : (
      <PopoverTrigger
        render={
          <button
            type="button"
            aria-label="Work order history"
            className="hover:bg-muted flex h-8 w-fit items-center gap-2 rounded-md px-2.5 text-sm font-normal"
          >
            <ClipboardListIcon className="size-4 shrink-0" />
            <span>工单历史</span>
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
          <div className="text-base font-medium">工单历史</div>
          <button
            type="button"
            aria-label="Close work order history"
            onClick={() => setOpen(false)}
            className="text-muted-foreground hover:bg-muted rounded-md p-1.5"
          >
            <XIcon className="size-4" />
          </button>
        </div>
        {error && <div className="border-b px-4 py-1.5 text-sm text-destructive">{error}</div>}
        <div className="grid min-h-0 flex-1 grid-cols-[280px_minmax(0,1fr)]">
          <div className="min-h-0 overflow-y-auto border-r">
            {orders === null && <div className="px-3 py-4 text-sm text-muted-foreground">加载中…</div>}
            {orders?.length === 0 && <div className="px-3 py-4 text-sm text-muted-foreground">还没有工单</div>}
            <ul className="flex flex-col gap-0.5 p-2">
              {(orders || []).map((order) => {
                const active = selected?.id === order.id;
                return (
                  <li key={order.id}>
                    <button
                      type="button"
                      onClick={() => void selectOrder(order)}
                      className={
                        active
                          ? "bg-muted flex w-full flex-col gap-1 rounded-lg px-3 py-2.5 text-start"
                          : "hover:bg-muted flex w-full flex-col gap-1 rounded-lg px-3 py-2.5 text-start"
                      }
                    >
                      <span className="truncate text-sm font-medium">{order.title}</span>
                      <span className="truncate text-xs text-muted-foreground">
                        {order.created_at.slice(0, 10)} · {order.status}
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
                选择左侧工单查看详情
              </div>
            )}
            {selected && (
              <div className="mx-auto max-w-3xl">
                <h2 className="text-lg font-semibold leading-7">{selected.title}</h2>
                <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
                  <div className="text-muted-foreground">状态：{selected.status}</div>
                  <div className="text-muted-foreground">诉求类型：{selected.request_type || "未标注"}</div>
                  <div className="text-muted-foreground">创建时间：{selected.created_at.slice(0, 19).replace("T", " ")}</div>
                  <div className="text-muted-foreground">source_case_id：{selected.source_case_id || "无"}</div>
                </dl>
                <h3 className="mt-6 text-sm font-medium text-muted-foreground">工单内容</h3>
                <p className="mt-2 whitespace-pre-wrap text-[15px] leading-7">{selected.content}</p>
                <h3 className="mt-6 text-sm font-medium text-muted-foreground">历史研判</h3>
                {analyses === null && <p className="mt-2 text-sm text-muted-foreground">加载中…</p>}
                {analyses?.length === 0 && (
                  <p className="mt-2 text-sm text-muted-foreground">该工单暂无研判记录</p>
                )}
                <ol className="mt-3 flex flex-col gap-4">
                  {[...(analyses || [])].reverse().map((analysis, index) => (
                    <li key={analysis.id} className="rounded-xl border p-5">
                      <div className="mb-2 text-sm text-muted-foreground">
                        研判 #{index + 1} · {analysis.created_at.slice(0, 19).replace("T", " ")}
                      </div>
                      <div className="mb-2 text-[15px] font-medium">
                        {analysis.recommended_department_text || "未给出建议部门"}
                      </div>
                      <p className="text-[15px] leading-7 text-muted-foreground whitespace-pre-wrap">
                        {analysis.conclusion}
                      </p>
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
