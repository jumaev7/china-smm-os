"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  format,
  parseISO,
  startOfMonth,
  endOfMonth,
  eachDayOfInterval,
  getDay,
  isSameDay,
  addMonths,
  subMonths,
} from "date-fns";
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  LayoutGrid,
  Plus,
  Sparkles,
  Table2,
} from "lucide-react";
import toast from "react-hot-toast";
import { clientsApi, Client, contentPlannerApi, ContentPlan, ContentPlanItem, normalizeList } from "@/lib/api";
import { cn, PLATFORM_CONFIG } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

const FORMAT_LABEL: Record<string, string> = {
  image: "Image",
  video: "Video",
  carousel: "Carousel",
  story: "Story",
};

function PlanItemDraftAction({
  item,
  busyItemId,
  recentlyCreated,
  generateAi,
  onCreateDraft,
}: {
  item: ContentPlanItem;
  busyItemId: string | null;
  recentlyCreated?: string;
  generateAi: boolean;
  onCreateDraft: (id: string) => void;
}) {
  const contentId = item.linked_content_id ?? recentlyCreated;
  const isBusy = busyItemId === item.id;
  if (contentId) {
    return (
      <div className="flex flex-col items-end gap-1">
        {recentlyCreated && (
          <span className="text-[10px] font-medium text-emerald-700">Draft created ✅</span>
        )}
        <Link href={`/content/${contentId}`} className="btn-secondary text-xs py-1">
          {recentlyCreated ? "Open content" : "Open draft"}
        </Link>
      </div>
    );
  }
  return (
    <button
      type="button"
      className="btn-primary text-xs py-1"
      disabled={isBusy}
      onClick={() => onCreateDraft(item.id)}
    >
      {isBusy ? (
        <>
          <Sparkles size={12} className="animate-pulse" />
          {generateAi ? "Generating draft..." : "Creating draft..."}
        </>
      ) : (
        <>
          <Plus size={12} /> Create draft
        </>
      )}
    </button>
  );
}

function PlanTable({
  items,
  busyItemId,
  recentlyCreated,
  generateAi,
  onCreateDraft,
}: {
  items: ContentPlanItem[];
  busyItemId: string | null;
  recentlyCreated: Record<string, string>;
  generateAi: boolean;
  onCreateDraft: (id: string) => void;
}) {
  return (
    <div className="card overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100 bg-gray-50">
            <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Date</th>
            <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Theme</th>
            <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Goal</th>
            <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Format</th>
            <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500">Platform</th>
            <th className="px-4 py-2.5" />
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {items.map((item) => (
            <tr key={item.id} className="hover:bg-gray-50 align-top">
              <td className="px-4 py-3 text-xs text-gray-600 whitespace-nowrap">
                {format(parseISO(item.planned_date), "MMM d, yyyy")}
              </td>
              <td className="px-4 py-3 text-sm font-medium text-gray-900 max-w-[180px]">
                {item.theme}
              </td>
              <td className="px-4 py-3 text-xs text-gray-600 max-w-xs">
                {item.goal}
              </td>
              <td className="px-4 py-3 text-xs capitalize text-gray-700">
                {FORMAT_LABEL[item.content_type] ?? item.content_type}
              </td>
              <td className="px-4 py-3">
                <div className="flex flex-wrap gap-1">
                  {item.platform_suggestions.map((p) => (
                    <span
                      key={p}
                      className={cn(
                        "text-[10px] px-1.5 py-0.5 rounded font-medium",
                        PLATFORM_CONFIG[p]?.color,
                      )}
                    >
                      {PLATFORM_CONFIG[p]?.label ?? p}
                    </span>
                  ))}
                </div>
              </td>
              <td className="px-4 py-3 text-right whitespace-nowrap">
                <PlanItemDraftAction
                  item={item}
                  busyItemId={busyItemId}
                  recentlyCreated={recentlyCreated[item.id]}
                  generateAi={generateAi}
                  onCreateDraft={onCreateDraft}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PlanCalendar({
  plan,
  monthDate,
}: {
  plan: ContentPlan;
  monthDate: Date;
}) {
  const days = eachDayOfInterval({
    start: startOfMonth(monthDate),
    end: endOfMonth(monthDate),
  });
  const startPad = getDay(startOfMonth(monthDate));

  const itemsForDay = (d: Date) =>
    plan.items.filter((i) => isSameDay(parseISO(i.planned_date), d));

  return (
    <div className="card p-4">
      <div className="grid grid-cols-7 gap-1 mb-2">
        {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => (
          <div key={d} className="text-[10px] font-medium text-gray-400 text-center py-1">
            {d}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {Array.from({ length: startPad }).map((_, i) => (
          <div key={`pad-${i}`} className="min-h-[88px]" />
        ))}
        {days.map((day) => {
          const dayItems = itemsForDay(day);
          return (
            <div
              key={day.toISOString()}
              className="min-h-[88px] rounded-lg border border-gray-100 bg-white p-1.5"
            >
              <p className="text-[10px] font-medium text-gray-500 mb-1">{format(day, "d")}</p>
              <div className="space-y-1">
                {dayItems.map((item) => (
                  <div
                    key={item.id}
                    className="text-[10px] rounded px-1 py-0.5 bg-brand-50 text-brand-900 border border-brand-100 line-clamp-2"
                    title={item.theme}
                  >
                    {item.theme}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function ContentPlannerPage() {
  const qc = useQueryClient();
  const [clientId, setClientId] = useState("");
  const [postsPerMonth, setPostsPerMonth] = useState(8);
  const [monthDate, setMonthDate] = useState(() => new Date());
  const [view, setView] = useState<"calendar" | "table">("calendar");
  const [busyItemId, setBusyItemId] = useState<string | null>(null);
  const [recentlyCreated, setRecentlyCreated] = useState<Record<string, string>>({});
  const [generateAi, setGenerateAi] = useState(true);

  const month = monthDate.getMonth() + 1;
  const year = monthDate.getFullYear();

  const { data: clientsData } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list().then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clientsData);

  const { data: plan, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["content-plan", clientId, month, year],
    queryFn: async () => {
      if (!clientId) return null;
      const res = await contentPlannerApi.findPlan({ client_id: clientId, month, year });
      return res.data;
    },
    enabled: !!clientId,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["content-plan"] });
    qc.invalidateQueries({ queryKey: ["content"] });
  };

  const generateMutation = useMutation({
    mutationFn: () =>
      contentPlannerApi.generate({
        client_id: clientId,
        month,
        year,
        posts_per_month: postsPerMonth,
      }),
    onSuccess: () => {
      toast.success("Content plan generated");
      invalidate();
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      toast.error(
        typeof err.response?.data?.detail === "string"
          ? err.response.data.detail
          : "Generate failed",
      );
    },
  });

  const approveMutation = useMutation({
    mutationFn: (planId: string) => contentPlannerApi.approvePlan(planId),
    onSuccess: () => {
      toast.success("Plan approved");
      invalidate();
    },
    onError: () => toast.error("Approve failed"),
  });

  const draftMutation = useMutation({
    mutationFn: (itemId: string) =>
      contentPlannerApi.createDraftFromItem(itemId, { generate_ai: generateAi }),
    onMutate: (id) => setBusyItemId(id),
    onSettled: () => setBusyItemId(null),
    onSuccess: (res, itemId) => {
      setRecentlyCreated((prev) => ({ ...prev, [itemId]: res.data.content_id }));
      if (res.data.created) {
        if (res.data.ai_generated) {
          toast.success("Draft created with AI captions ✅");
        } else if (res.data.ai_error) {
          toast.error("Draft created — AI generation failed");
        } else {
          toast.success("Draft created ✅");
        }
      } else {
        toast.success("Opening existing draft");
      }
      invalidate();
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      toast.error(
        typeof err.response?.data?.detail === "string"
          ? err.response.data.detail
          : "Create draft failed",
      );
    },
  });

  const sortedItems = useMemo(
    () => [...normalizeList<ContentPlanItem>(plan)].sort((a, b) => a.planned_date.localeCompare(b.planned_date)),
    [plan],
  );

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <ClipboardList size={20} className="text-brand-600" />
            Content Planner
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            AI monthly content plan — themes, dates, and draft preparation.
          </p>
        </div>
        {plan && (
          <span
            className={cn(
              "text-xs px-2.5 py-1 rounded-full border font-medium capitalize",
              plan.status === "approved"
                ? "bg-emerald-100 text-emerald-800 border-emerald-200"
                : "bg-amber-100 text-amber-800 border-amber-200",
            )}
          >
            {plan.status}
          </span>
        )}
      </div>

      <div className="card p-4 mb-6 space-y-4">
        <h2 className="text-sm font-semibold text-gray-800">Generate plan</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="label text-xs">Client</label>
            <select
              className="input text-sm"
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
            >
              <option value="">Select client</option>
              {clientOptions.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.company_name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label text-xs">Month</label>
            <div className="flex items-center gap-1">
              <button
                type="button"
                className="btn-secondary px-2 py-1"
                onClick={() => setMonthDate((d) => subMonths(d, 1))}
              >
                <ChevronLeft size={14} />
              </button>
              <span className="flex-1 text-center text-sm font-medium">
                {format(monthDate, "MMMM yyyy")}
              </span>
              <button
                type="button"
                className="btn-secondary px-2 py-1"
                onClick={() => setMonthDate((d) => addMonths(d, 1))}
              >
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
          <div>
            <label className="label text-xs">Posts per month</label>
            <input
              type="number"
              min={1}
              max={60}
              className="input text-sm"
              value={postsPerMonth}
              onChange={(e) => setPostsPerMonth(parseInt(e.target.value, 10) || 8)}
            />
          </div>
          <div className="flex items-end">
            <button
              type="button"
              className="btn-primary w-full text-sm"
              disabled={!clientId || generateMutation.isPending}
              onClick={() => generateMutation.mutate()}
            >
              <Sparkles size={14} />
              {generateMutation.isPending ? "Generating…" : "Generate plan"}
            </button>
          </div>
        </div>
      </div>

      {!clientId ? (
        <EmptyState
          title="Select a client"
          description="Choose a client to view or generate a content plan."
        />
      ) : isLoading ? (
        <LoadingState message="Loading plan…" />
      ) : isError ? (
        <ErrorState
          message={error instanceof Error ? error.message : "Failed to load plan"}
          onRetry={() => refetch()}
        />
      ) : !plan ? (
        <EmptyState
          title={`No plan for ${format(monthDate, "MMMM yyyy")}`}
          description="Click Generate plan to create one."
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <div>
              <h2 className="text-sm font-semibold text-gray-900">{plan.title}</h2>
              <p className="text-xs text-gray-500 mt-0.5">
                {plan.items.length} posts · {plan.company_name ?? "Client"}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <div className="flex rounded-lg border border-gray-200 overflow-hidden">
                <button
                  type="button"
                  className={cn(
                    "text-xs px-3 py-1.5 flex items-center gap-1",
                    view === "calendar" ? "bg-brand-600 text-white" : "bg-white text-gray-600",
                  )}
                  onClick={() => setView("calendar")}
                >
                  <LayoutGrid size={12} /> Calendar
                </button>
                <button
                  type="button"
                  className={cn(
                    "text-xs px-3 py-1.5 flex items-center gap-1",
                    view === "table" ? "bg-brand-600 text-white" : "bg-white text-gray-600",
                  )}
                  onClick={() => setView("table")}
                >
                  <Table2 size={12} /> Table
                </button>
              </div>
              {plan.status === "draft" && (
                <button
                  type="button"
                  className="btn-secondary text-xs"
                  disabled={approveMutation.isPending}
                  onClick={() => approveMutation.mutate(plan.id)}
                >
                  <CalendarDays size={12} /> Approve plan
                </button>
              )}
              <button type="button" className="btn-secondary text-xs" onClick={() => refetch()}>
                Refresh
              </button>
            </div>
          </div>

          <label className="flex items-center gap-2 mb-4 text-sm text-gray-600 cursor-pointer w-fit">
            <input
              type="checkbox"
              className="rounded border-gray-300 text-brand-600 focus:ring-brand-500"
              checked={generateAi}
              onChange={(e) => setGenerateAi(e.target.checked)}
            />
            <Sparkles size={14} className="text-brand-600" />
            Create draft with AI captions
          </label>

          {view === "calendar" ? (
            <PlanCalendar plan={plan} monthDate={monthDate} />
          ) : (
            <PlanTable
              items={sortedItems}
              busyItemId={busyItemId}
              recentlyCreated={recentlyCreated}
              generateAi={generateAi}
              onCreateDraft={(id) => draftMutation.mutate(id)}
            />
          )}
        </>
      )}
    </div>
  );
}
