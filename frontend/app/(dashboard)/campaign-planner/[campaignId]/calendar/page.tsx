"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addDays,
  addMonths,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameMonth,
  startOfMonth,
  startOfWeek,
  subMonths,
} from "date-fns";
import { ArrowLeft, CalendarRange, ChevronLeft, ChevronRight, Plus, Wand2 } from "lucide-react";
import toast from "react-hot-toast";
import {
  CAMPAIGN_LOCALES,
  CAMPAIGN_PLANNER_QUERY_KEY,
  CAMPAIGN_PLATFORMS,
  campaignPlannerApi,
  normalizeList,
  type CalendarSlot,
  type CampaignInventoryItem,
  type MarketingCampaign,
  type PlanVersion,
} from "@/lib/api";
import { cn, PLATFORM_CONFIG } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  PageHeader,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import {
  generationMethodLabel,
  isPlanReadOnly,
  planStatusVariant,
  slotStatusVariant,
  titleCase,
  toastCampaignError,
} from "@/lib/campaign-planner-ui";

type ViewMode = "month" | "week";

export default function CampaignCalendarPage() {
  const params = useParams();
  const search = useSearchParams();
  const campaignId = String(params.campaignId || "");
  const planFromQuery = search.get("plan");
  const qc = useQueryClient();

  const [view, setView] = useState<ViewMode>("month");
  const [cursor, setCursor] = useState(() => new Date());
  const [platformFilter, setPlatformFilter] = useState("");
  const [localeFilter, setLocaleFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [selectedPlanId, setSelectedPlanId] = useState(planFromQuery || "");
  const [assignSlotId, setAssignSlotId] = useState<string | null>(null);
  const [showCreateSlot, setShowCreateSlot] = useState(false);
  const [newSlot, setNewSlot] = useState({
    platform: "telegram",
    locale: "en",
    scheduled_date: format(new Date(), "yyyy-MM-dd"),
    scheduled_time: "09:00",
  });

  const campaignQ = useQuery({
    queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, campaignId, "detail"],
    queryFn: () => campaignPlannerApi.getCampaign(campaignId).then((r) => r.data),
    enabled: Boolean(campaignId),
  });
  const plansQ = useQuery({
    queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, campaignId, "plans"],
    queryFn: () => campaignPlannerApi.listPlans(campaignId).then((r) => r.data),
    enabled: Boolean(campaignId),
  });

  const campaign = campaignQ.data as MarketingCampaign | undefined;
  const plans = normalizeList<PlanVersion>(plansQ.data);
  const planId =
    selectedPlanId ||
    planFromQuery ||
    campaign?.current_plan_version_id ||
    campaign?.published_plan_version_id ||
    plans[0]?.id ||
    "";
  const plan = plans.find((p) => p.id === planId) || null;
  const readOnly = isPlanReadOnly(plan?.status);

  const slotsQ = useQuery({
    queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, campaignId, "slots", planId],
    queryFn: () => campaignPlannerApi.listSlots(campaignId, planId).then((r) => r.data),
    enabled: Boolean(campaignId && planId),
  });
  const inventoryQ = useQuery({
    queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, campaignId, "inventory"],
    queryFn: () =>
      campaignPlannerApi.contentInventory(campaignId, { limit: 50 }).then((r) => r.data),
    enabled: Boolean(campaignId && assignSlotId),
  });

  const slots = useMemo(() => {
    let items = normalizeList<CalendarSlot>(slotsQ.data);
    if (platformFilter) items = items.filter((s) => s.platform === platformFilter);
    if (localeFilter) items = items.filter((s) => s.locale === localeFilter);
    if (statusFilter) items = items.filter((s) => s.status === statusFilter);
    return items;
  }, [slotsQ.data, platformFilter, localeFilter, statusFilter]);

  const inventory = normalizeList<CampaignInventoryItem>(inventoryQ.data);

  const rangeStart =
    view === "month"
      ? startOfWeek(startOfMonth(cursor), { weekStartsOn: 1 })
      : startOfWeek(cursor, { weekStartsOn: 1 });
  const rangeEnd =
    view === "month"
      ? endOfWeek(endOfMonth(cursor), { weekStartsOn: 1 })
      : endOfWeek(cursor, { weekStartsOn: 1 });
  const days = eachDayOfInterval({ start: rangeStart, end: rangeEnd });

  const slotsByDate = useMemo(() => {
    const map = new Map<string, CalendarSlot[]>();
    for (const s of slots) {
      const key = s.scheduled_date?.slice(0, 10);
      if (!key) continue;
      const list = map.get(key) || [];
      list.push(s);
      map.set(key, list);
    }
    return map;
  }, [slots]);

  const invalidateSlots = () =>
    qc.invalidateQueries({ queryKey: [...CAMPAIGN_PLANNER_QUERY_KEY, campaignId, "slots", planId] });

  const createSlotMut = useMutation({
    mutationFn: () => campaignPlannerApi.createSlot(campaignId, planId, newSlot),
    onSuccess: () => {
      toast.success("Slot created");
      setShowCreateSlot(false);
      invalidateSlots();
    },
    onError: (err) => toastCampaignError(err, "Could not create slot"),
  });
  const deleteSlotMut = useMutation({
    mutationFn: (slotId: string) => campaignPlannerApi.deleteSlot(campaignId, planId, slotId),
    onSuccess: () => {
      toast.success("Slot deleted");
      invalidateSlots();
    },
    onError: (err) => toastCampaignError(err),
  });
  const assignMut = useMutation({
    mutationFn: ({ slotId, contentId }: { slotId: string; contentId: string }) =>
      campaignPlannerApi.assignSlot(campaignId, planId, slotId, {
        content_id: contentId,
        allow_warnings: true,
      }),
    onSuccess: () => {
      toast.success("Content assigned (not scheduled or published)");
      setAssignSlotId(null);
      invalidateSlots();
    },
    onError: (err) => toastCampaignError(err, "Assignment failed"),
  });
  const unassignMut = useMutation({
    mutationFn: (slotId: string) => campaignPlannerApi.unassignSlot(campaignId, planId, slotId),
    onSuccess: () => {
      toast.success("Assignment removed");
      invalidateSlots();
    },
    onError: (err) => toastCampaignError(err),
  });
  const autoAssignMut = useMutation({
    mutationFn: () =>
      campaignPlannerApi.autoAssign(campaignId, planId, {
        allow_warnings: true,
        run_publish_safety: false,
      }),
    onSuccess: (res) => {
      toast.success(`Auto-assigned ${res.data.assigned} slot(s)`);
      invalidateSlots();
    },
    onError: (err) => toastCampaignError(err, "Auto-assign failed"),
  });

  if (campaignQ.isLoading || plansQ.isLoading) {
    return <LoadingState message="Loading calendar…" />;
  }
  if (campaignQ.isError || !campaign) {
    return <ErrorState error={campaignQ.error} onRetry={() => campaignQ.refetch()} />;
  }

  return (
    <PageShell wide>
      <PageHeader
        title={`${campaign.name} calendar`}
        subtitle={`Timezone ${campaign.timezone} · times are rule-based suggestions, not optimal posting times`}
        icon={CalendarRange}
        actions={
          <>
            <Link href={`/campaign-planner/${campaignId}`} className="btn-secondary text-sm">
              <ArrowLeft size={15} /> Campaign
            </Link>
            {!readOnly && (
              <>
                <button className="btn-secondary text-sm" onClick={() => setShowCreateSlot(true)}>
                  <Plus size={15} /> Add slot
                </button>
                <button
                  className="btn-primary text-sm"
                  disabled={!planId || autoAssignMut.isPending}
                  onClick={() => autoAssignMut.mutate()}
                >
                  <Wand2 size={15} /> Auto-assign
                </button>
              </>
            )}
          </>
        }
      />

      <div className="flex flex-wrap gap-3 mb-4 text-sm items-center">
        <label className="flex items-center gap-2">
          <span className="text-gray-500">Plan</span>
          <select
            className="rounded-md border border-gray-300 px-2 py-1.5"
            value={planId}
            onChange={(e) => setSelectedPlanId(e.target.value)}
          >
            {plans.map((p) => (
              <option key={p.id} value={p.id}>
                v{p.version} · {p.status}
              </option>
            ))}
          </select>
        </label>
        {plan && (
          <StatusBadge variant={planStatusVariant(plan.status)}>{titleCase(plan.status)}</StatusBadge>
        )}
        {readOnly && (
          <span className="text-xs text-amber-700 bg-amber-50 border border-amber-100 px-2 py-1 rounded">
            Published plan is read-only
          </span>
        )}
        <select
          className="rounded-md border border-gray-300 px-2 py-1.5"
          value={platformFilter}
          onChange={(e) => setPlatformFilter(e.target.value)}
        >
          <option value="">All platforms</option>
          {CAMPAIGN_PLATFORMS.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
        <select
          className="rounded-md border border-gray-300 px-2 py-1.5"
          value={localeFilter}
          onChange={(e) => setLocaleFilter(e.target.value)}
        >
          <option value="">All locales</option>
          {CAMPAIGN_LOCALES.map((l) => (
            <option key={l} value={l}>{l}</option>
          ))}
        </select>
        <select
          className="rounded-md border border-gray-300 px-2 py-1.5"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All readiness</option>
          <option value="unassigned">Unassigned</option>
          <option value="assigned">Assigned</option>
          <option value="ready">Ready</option>
          <option value="ready_with_warnings">Warnings</option>
          <option value="blocked">Blocked</option>
        </select>
        <div className="ml-auto flex items-center gap-1">
          <button
            className={cn("btn-secondary text-xs py-1", view === "month" && "ring-1 ring-brand-300")}
            onClick={() => setView("month")}
          >
            Month
          </button>
          <button
            className={cn("btn-secondary text-xs py-1", view === "week" && "ring-1 ring-brand-300")}
            onClick={() => setView("week")}
          >
            Week
          </button>
          <button
            className="btn-secondary text-xs py-1"
            onClick={() => setCursor(view === "month" ? subMonths(cursor, 1) : addDays(cursor, -7))}
          >
            <ChevronLeft size={14} />
          </button>
          <span className="text-sm font-medium w-36 text-center">
            {view === "month" ? format(cursor, "MMM yyyy") : `Week of ${format(rangeStart, "MMM d")}`}
          </span>
          <button
            className="btn-secondary text-xs py-1"
            onClick={() => setCursor(view === "month" ? addMonths(cursor, 1) : addDays(cursor, 7))}
          >
            <ChevronRight size={14} />
          </button>
        </div>
      </div>

      {!planId ? (
        <EmptyState
          title="No plan version"
          description="Generate a plan from the campaign overview first."
          action={
            <Link href={`/campaign-planner/${campaignId}`} className="btn-primary text-sm mt-2">
              Back to campaign
            </Link>
          }
        />
      ) : slotsQ.isLoading ? (
        <LoadingState message="Loading slots…" />
      ) : slotsQ.isError ? (
        <ErrorState error={slotsQ.error} onRetry={() => slotsQ.refetch()} />
      ) : (
        <div className="grid grid-cols-7 gap-px bg-gray-200 border border-gray-200 rounded-lg overflow-hidden">
          {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
            <div key={d} className="bg-gray-50 px-2 py-1.5 text-[11px] font-medium text-gray-500">
              {d}
            </div>
          ))}
          {days.map((day) => {
            const key = format(day, "yyyy-MM-dd");
            const daySlots = slotsByDate.get(key) || [];
            const inMonth = view === "week" || isSameMonth(day, cursor);
            return (
              <div
                key={key}
                className={cn(
                  "bg-white min-h-[7.5rem] p-1.5",
                  !inMonth && "bg-gray-50/80 text-gray-400",
                )}
              >
                <p className="text-[11px] font-medium text-gray-600 mb-1">{format(day, "d")}</p>
                <div className="space-y-1">
                  {daySlots.map((s) => (
                    <div
                      key={s.id}
                      className="rounded border border-gray-100 bg-gray-50 px-1.5 py-1 text-[10px] leading-snug"
                    >
                      <div className="flex items-center justify-between gap-1">
                        <span className="font-medium truncate">
                          {PLATFORM_CONFIG[s.platform as keyof typeof PLATFORM_CONFIG]?.label || s.platform}
                        </span>
                        <StatusBadge variant={slotStatusVariant(s.status)}>
                          {titleCase(s.status)}
                        </StatusBadge>
                      </div>
                      <p className="text-gray-500 mt-0.5">
                        {String(s.scheduled_time).slice(0, 5)} · {s.locale}
                      </p>
                      {!readOnly && (
                        <div className="flex flex-wrap gap-1 mt-1">
                          {s.status === "unassigned" ? (
                            <button
                              className="text-brand-700 underline"
                              onClick={() => setAssignSlotId(s.id)}
                            >
                              Assign
                            </button>
                          ) : (
                            <button
                              className="text-gray-600 underline"
                              onClick={() => unassignMut.mutate(s.id)}
                            >
                              Unassign
                            </button>
                          )}
                          <button
                            className="text-red-600 underline"
                            onClick={() => deleteSlotMut.mutate(s.id)}
                          >
                            Delete
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <p className="mt-3 text-xs text-gray-500">
        Showing {slots.length} slot(s). Assignment links inventory content to the plan only —
        it does not schedule or publish.
      </p>

      {assignSlotId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="card w-full max-w-lg max-h-[80vh] overflow-auto p-5 space-y-3">
            <h2 className="text-lg font-semibold">Assign content</h2>
            <p className="text-xs text-gray-500">
              Source, deterministic, and AI variants are shown when available. Lower scores are not hidden.
            </p>
            {inventoryQ.isLoading ? (
              <LoadingState message="Loading inventory…" />
            ) : inventory.length === 0 ? (
              <EmptyState title="No assignable content" description="Create or approve content first." />
            ) : (
              <ul className="space-y-2">
                {inventory.map((item) => (
                  <li
                    key={item.content_id}
                    className="flex items-center justify-between gap-2 border border-gray-100 rounded-md px-3 py-2 text-sm"
                  >
                    <div>
                      <p className="font-medium text-gray-900">
                        {item.content_id.slice(0, 8)}… · {item.status}
                      </p>
                      <p className="text-xs text-gray-500">
                        {(item.platforms || []).join(", ")} · locales {(item.available_locales || []).join(", ") || "—"}
                        {item.is_assigned_in_campaign ? " · already assigned" : ""}
                        {generationMethodLabel(item.generation_method)
                          ? ` · ${generationMethodLabel(item.generation_method)}`
                          : ""}
                      </p>
                    </div>
                    <button
                      className="btn-primary text-xs py-1"
                      disabled={assignMut.isPending}
                      onClick={() =>
                        assignMut.mutate({
                          slotId: assignSlotId,
                          contentId: item.content_id,
                        })
                      }
                    >
                      Assign
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex justify-end">
              <button className="btn-secondary text-sm" onClick={() => setAssignSlotId(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {showCreateSlot && !readOnly && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="card w-full max-w-md p-5 space-y-3">
            <h2 className="text-lg font-semibold">Create slot</h2>
            <label className="block text-sm">
              Platform
              <select
                className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"
                value={newSlot.platform}
                onChange={(e) => setNewSlot((s) => ({ ...s, platform: e.target.value }))}
              >
                {CAMPAIGN_PLATFORMS.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              Locale
              <select
                className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"
                value={newSlot.locale}
                onChange={(e) => setNewSlot((s) => ({ ...s, locale: e.target.value }))}
              >
                {CAMPAIGN_LOCALES.map((l) => (
                  <option key={l} value={l}>{l}</option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              Date ({campaign.timezone})
              <input
                type="date"
                className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"
                value={newSlot.scheduled_date}
                onChange={(e) => setNewSlot((s) => ({ ...s, scheduled_date: e.target.value }))}
              />
            </label>
            <label className="block text-sm">
              Suggested time
              <input
                type="time"
                className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"
                value={newSlot.scheduled_time}
                onChange={(e) => setNewSlot((s) => ({ ...s, scheduled_time: e.target.value }))}
              />
            </label>
            <div className="flex justify-end gap-2">
              <button className="btn-secondary text-sm" onClick={() => setShowCreateSlot(false)}>
                Cancel
              </button>
              <button
                className="btn-primary text-sm"
                disabled={createSlotMut.isPending}
                onClick={() => createSlotMut.mutate()}
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </PageShell>
  );
}
