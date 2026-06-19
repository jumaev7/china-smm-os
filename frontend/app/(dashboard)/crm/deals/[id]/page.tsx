"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  ArrowLeft,
  Briefcase,
  Calendar,
  FileText,
  Loader2,
  Phone,
  Mail,
  MessageCircle,
  Sparkles,
  Activity,
  Clock,
  AlertTriangle,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  crmApi,
  proposalsApi,
  CrmDealEvent,
  CrmDealHealth,
  DealStatus,
  ProposalStatus,
  DocumentStatus,
  normalizeList,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const DEAL_STATUS_STYLE: Record<DealStatus, string> = {
  new: "bg-gray-100 text-gray-700 border-gray-200",
  proposal: "bg-sky-100 text-sky-800 border-sky-200",
  contract: "bg-violet-100 text-violet-800 border-violet-200",
  invoice: "bg-amber-100 text-amber-800 border-amber-200",
  waiting_payment: "bg-orange-100 text-orange-800 border-orange-200",
  won: "bg-emerald-100 text-emerald-800 border-emerald-200",
  lost: "bg-red-100 text-red-800 border-red-200",
};

const RISK_STYLE = {
  low: "bg-emerald-50 border-emerald-200 text-emerald-900",
  medium: "bg-amber-50 border-amber-200 text-amber-900",
  high: "bg-red-50 border-red-200 text-red-900",
};

const EVENT_DOT: Record<string, string> = {
  activity: "bg-sky-400",
  proposal: "bg-indigo-400",
  contract: "bg-violet-400",
  invoice: "bg-amber-400",
  note: "bg-gray-400",
  status_change: "bg-orange-400",
};

function formatValue(val: number | string | null | undefined): string {
  if (val == null || val === "") return "—";
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(n)) return String(val);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

function groupEventsByDay(events: CrmDealEvent[]) {
  const sorted = [...events].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );
  const groups: { date: string; label: string; items: CrmDealEvent[] }[] = [];
  for (const event of sorted) {
    const dateKey = format(parseISO(event.created_at), "yyyy-MM-dd");
    const label = format(parseISO(event.created_at), "MMM d");
    const existing = groups.find((g) => g.date === dateKey);
    if (existing) {
      existing.items.push(event);
    } else {
      groups.push({ date: dateKey, label, items: [event] });
    }
  }
  return groups;
}

function HealthCard({
  health,
  loading,
  onRefresh,
}: {
  health: CrmDealHealth | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-gray-900 flex items-center gap-1.5">
          <Sparkles size={14} className="text-violet-600" />
          Deal health
        </p>
        <button
          type="button"
          disabled={loading}
          onClick={onRefresh}
          className="text-[10px] px-2 py-1 rounded border border-violet-200 bg-violet-50 text-violet-800 disabled:opacity-50 flex items-center gap-1"
        >
          {loading ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />}
          Analyze
        </button>
      </div>

      {!health && !loading && (
        <p className="text-[11px] text-gray-500">Run AI analysis for deal score and next action.</p>
      )}

      {health && (
        <>
          <div className="flex items-center gap-4">
            <div>
              <p className="text-3xl font-bold text-gray-900 tabular-nums">{health.deal_score}</p>
              <p className="text-[10px] text-gray-500">Deal score</p>
            </div>
            <span
              className={cn(
                "text-[10px] px-2 py-1 rounded-full border font-medium capitalize",
                RISK_STYLE[health.risk_level],
              )}
            >
              {health.risk_level} risk
            </span>
          </div>
          <div className="rounded-lg bg-violet-50/80 border border-violet-100 p-2.5 space-y-1">
            <p className="text-[11px] font-medium text-violet-950">Recommended action</p>
            <p className="text-[11px] text-violet-900">{health.recommended_action}</p>
          </div>
          <p className="text-[10px] text-gray-600 leading-relaxed">{health.reasoning}</p>
          <p className="text-[9px] text-gray-400">Review manually — no auto actions.</p>
        </>
      )}
    </div>
  );
}

export default function DealRoomPage() {
  const params = useParams();
  const dealId = params.id as string;
  const queryClient = useQueryClient();
  const [health, setHealth] = useState<CrmDealHealth | null>(null);
  const [noteTitle, setNoteTitle] = useState("");
  const [wonAmount, setWonAmount] = useState("");
  const [wonCommission, setWonCommission] = useState("10");

  const { data: deal, isLoading } = useQuery({
    queryKey: ["crm-deal", dealId],
    queryFn: () => crmApi.getDeal(dealId).then((r) => r.data),
  });

  const { data: v2Proposals } = useQuery({
    queryKey: ["proposal-documents-deal", dealId],
    queryFn: () => proposalsApi.list({ deal_id: dealId, limit: 20 }).then((r) => r.data),
    enabled: !!dealId,
  });

  const updateMutation = useMutation({
    mutationFn: (data: Parameters<typeof crmApi.updateDeal>[1]) =>
      crmApi.updateDeal(dealId, data).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["crm-deal", dealId] });
      queryClient.invalidateQueries({ queryKey: ["crm-deals"] });
      toast.success("Deal updated");
    },
    onError: (err: Error) => toast.error(err.message || "Update failed"),
  });

  const noteMutation = useMutation({
    mutationFn: (title: string) =>
      crmApi.addDealEvent(dealId, { event_type: "note", title }).then((r) => r.data),
    onSuccess: () => {
      setNoteTitle("");
      queryClient.invalidateQueries({ queryKey: ["crm-deal", dealId] });
      toast.success("Note added to timeline");
    },
    onError: (err: Error) => toast.error(err.message || "Failed to add note"),
  });

  const healthMutation = useMutation({
    mutationFn: () => crmApi.assessDealHealth(dealId).then((r) => r.data),
    onSuccess: (data) => {
      setHealth(data);
      toast.success("Deal health analyzed");
    },
    onError: (err: Error) => toast.error(err.message || "Analysis failed"),
  });

  const markWonMutation = useMutation({
    mutationFn: () =>
      crmApi
        .markDealWon(dealId, {
          deal_amount: parseFloat(wonAmount),
          commission_percent: parseFloat(wonCommission),
        })
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["crm-deal", dealId] });
      queryClient.invalidateQueries({ queryKey: ["crm-deals"] });
      queryClient.invalidateQueries({ queryKey: ["revenue-overview"] });
      toast.success("Deal marked won — commission tracked on Revenue page");
    },
    onError: (err: Error) => toast.error(err.message || "Mark won failed"),
  });

  const timelineGroups = useMemo(
    () => groupEventsByDay(deal?.events ?? []),
    [deal?.events],
  );

  if (isLoading || !deal) {
    return (
      <div className="p-6 flex items-center justify-center gap-2 text-sm text-gray-400">
        <Loader2 size={16} className="animate-spin" />
        Loading deal room…
      </div>
    );
  }

  const lead = deal.lead;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
        <div>
          <Link
            href="/crm/deals"
            className="text-xs text-gray-500 hover:text-gray-800 flex items-center gap-1 mb-2"
          >
            <ArrowLeft size={12} />
            All deals
          </Link>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Briefcase size={20} className="text-violet-600" />
            {deal.title}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {deal.lead_name} · {deal.client_name}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="input text-xs"
            value={deal.status}
            onChange={(e) =>
              updateMutation.mutate({ status: e.target.value as DealStatus })
            }
          >
            {(Object.keys(DEAL_STATUS_STYLE) as DealStatus[]).map((s) => (
              <option key={s} value={s}>
                {s.replace("_", " ")}
              </option>
            ))}
          </select>
          <span
            className={cn(
              "text-[10px] px-2 py-1 rounded-full border font-medium capitalize",
              DEAL_STATUS_STYLE[deal.status],
            )}
          >
            {deal.status.replace("_", " ")}
          </span>
          <Link
            href="/crm"
            className="text-xs text-brand-700 hover:text-brand-900"
          >
            CRM pipeline
          </Link>
        </div>
      </div>

      {deal.status !== "won" && !deal.deal_amount && (
        <div className="card p-4 border-emerald-200 bg-emerald-50/40 space-y-3">
          <p className="text-xs font-semibold text-emerald-950">Mark deal won (revenue tracking)</p>
          <div className="flex flex-wrap gap-2 items-end">
            <label className="text-xs space-y-1">
              <span className="text-gray-600">Deal amount (UZS)</span>
              <input
                className="input text-sm w-36"
                type="number"
                min="0"
                value={wonAmount}
                onChange={(e) => setWonAmount(e.target.value)}
              />
            </label>
            <label className="text-xs space-y-1">
              <span className="text-gray-600">Commission %</span>
              <input
                className="input text-sm w-24"
                type="number"
                min="0"
                max="100"
                value={wonCommission}
                onChange={(e) => setWonCommission(e.target.value)}
              />
            </label>
            <button
              type="button"
              disabled={markWonMutation.isPending || !wonAmount || !wonCommission}
              onClick={() => markWonMutation.mutate()}
              className="text-xs px-3 py-2 rounded-lg border border-emerald-300 bg-white text-emerald-900 disabled:opacity-50"
            >
              Mark won
            </button>
          </div>
          <p className="text-[10px] text-emerald-800">Tracking only — no payment processed.</p>
        </div>
      )}

      {deal.status === "won" && deal.commission_amount != null && (
        <div className="card p-3 flex flex-wrap items-center justify-between gap-2 text-sm">
          <span className="text-gray-700">
            Revenue {Number(deal.deal_amount ?? 0).toLocaleString()} {deal.currency ?? "UZS"} ·
            Commission {Number(deal.commission_amount).toLocaleString()} ({deal.commission_percent}%)
            {deal.commission_status && ` · ${deal.commission_status}`}
          </span>
          <Link href="/revenue" className="text-xs text-brand-700 hover:text-brand-900">
            Manage on Revenue →
          </Link>
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-4">
        <div className="card p-4 space-y-2">
          <p className="text-xs font-semibold text-gray-900">Deal metrics</p>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="rounded-lg bg-gray-50 p-2">
              <p className="text-lg font-bold text-gray-900 tabular-nums">{deal.probability}%</p>
              <p className="text-[9px] text-gray-500">Probability</p>
            </div>
            <div className="rounded-lg bg-gray-50 p-2">
              <p className="text-lg font-bold text-gray-900 tabular-nums">
                {formatValue(deal.expected_value)}
              </p>
              <p className="text-[9px] text-gray-500">Expected value</p>
            </div>
            <div className="rounded-lg bg-gray-50 p-2">
              <p className="text-lg font-bold text-gray-900 tabular-nums">{deal.days_in_pipeline}</p>
              <p className="text-[9px] text-gray-500">Days in pipeline</p>
            </div>
          </div>
          {deal.expected_close_date && (
            <p className="text-[10px] text-gray-500 flex items-center gap-1">
              <Calendar size={10} />
              Expected close: {format(parseISO(deal.expected_close_date), "MMM d, yyyy")}
            </p>
          )}
        </div>

        <div className="lg:col-span-2">
          <HealthCard
            health={health}
            loading={healthMutation.isPending}
            onRefresh={() => healthMutation.mutate()}
          />
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card p-4 space-y-3">
          <p className="text-xs font-semibold text-gray-900">Lead info</p>
          <div className="text-xs space-y-1.5 text-gray-700">
            <p className="font-medium text-gray-900">{lead.name}</p>
            {lead.company && <p>{lead.company}</p>}
            {lead.interest && (
              <p className="text-gray-600 line-clamp-3">{lead.interest}</p>
            )}
            {lead.phone && (
              <p className="flex items-center gap-1.5">
                <Phone size={11} className="text-gray-400" /> {lead.phone}
              </p>
            )}
            {lead.email && (
              <p className="flex items-center gap-1.5">
                <Mail size={11} className="text-gray-400" /> {lead.email}
              </p>
            )}
            {lead.telegram && (
              <p className="flex items-center gap-1.5">
                <MessageCircle size={11} className="text-gray-400" /> {lead.telegram}
              </p>
            )}
            <p className="text-gray-500 capitalize">Pipeline: {lead.status.replace("_", " ")}</p>
          </div>
        </div>

        <div className="card p-4 space-y-3">
          <p className="text-xs font-semibold text-gray-900 flex items-center gap-1.5">
            <Activity size={14} />
            Activities
          </p>
          {deal.activities.length === 0 && (
            <p className="text-[11px] text-gray-400">No activities logged.</p>
          )}
          <ul className="space-y-2 max-h-48 overflow-y-auto">
            {deal.activities.slice(0, 8).map((act) => (
              <li key={act.id} className="text-[11px] border-l-2 border-gray-200 pl-2">
                <span className="text-gray-400 capitalize">{act.type}</span>
                <p className="text-gray-700 line-clamp-2">{act.content}</p>
                <p className="text-[9px] text-gray-400">
                  {format(parseISO(act.created_at), "MMM d, HH:mm")}
                </p>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        <div className="card p-4 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-semibold text-gray-900 flex items-center gap-1.5">
              <FileText size={14} />
              Proposals ({deal.proposals.length + normalizeList(v2Proposals).length})
            </p>
            <Link
              href={`/proposals/new?client_id=${deal.client_id}&lead_id=${deal.lead_id}&deal_id=${deal.id}`}
              className="text-[10px] px-2 py-1 rounded border border-indigo-200 bg-indigo-50 text-indigo-900 hover:bg-indigo-100"
            >
              Generate proposal
            </Link>
          </div>
          {deal.proposals.length === 0 && normalizeList(v2Proposals).length === 0 && (
            <p className="text-[11px] text-gray-400">No proposals yet.</p>
          )}
          <ul className="space-y-2">
            {deal.proposals.map((p) => (
              <li key={p.id} className="rounded border border-gray-100 p-2 text-[11px]">
                <p className="font-medium text-gray-900 truncate">{p.title}</p>
                <p className="text-gray-500 capitalize">{p.status as ProposalStatus}</p>
                <p className="text-[9px] text-gray-400">
                  {format(parseISO(p.created_at), "MMM d, yyyy")} · CRM v1
                </p>
              </li>
            ))}
            {normalizeList(v2Proposals).map((p) => (
              <li key={p.id} className="rounded border border-indigo-100 p-2 text-[11px] space-y-1">
                <Link href={`/proposals/${p.id}`} className="font-medium text-indigo-900 truncate block hover:underline">
                  {p.title}
                </Link>
                <p className="text-gray-500 capitalize">{p.status}</p>
                <div className="text-[9px] text-gray-500 space-y-0.5">
                  <p>Created {format(parseISO(p.created_at), "MMM d, yyyy")}</p>
                  {p.sent_at && <p>Sent {format(parseISO(p.sent_at), "MMM d, HH:mm")}</p>}
                  {p.follow_up_at && <p>Follow-up {format(parseISO(p.follow_up_at), "MMM d, HH:mm")}</p>}
                  {p.accepted_at && <p className="text-emerald-700">Accepted {format(parseISO(p.accepted_at), "MMM d, HH:mm")}</p>}
                  {p.rejected_at && <p className="text-red-700">Rejected {format(parseISO(p.rejected_at), "MMM d, HH:mm")}</p>}
                  {p.buyer_feedback && (
                    <p className="text-red-600 line-clamp-2">Feedback: {p.buyer_feedback}</p>
                  )}
                </div>
                <p className="text-[9px] text-gray-400">Proposal v2</p>
              </li>
            ))}
          </ul>
        </div>

        <div className="card p-4 space-y-2">
          <p className="text-xs font-semibold text-gray-900">Contracts ({deal.contracts.length})</p>
          {deal.contracts.length === 0 && (
            <p className="text-[11px] text-gray-400">No contract drafts.</p>
          )}
          <ul className="space-y-2">
            {deal.contracts.map((d) => (
              <li key={d.id} className="rounded border border-violet-100 p-2 text-[11px]">
                <p className="font-medium text-gray-900 truncate">{d.title}</p>
                <p className="text-gray-500 capitalize">{d.status as DocumentStatus}</p>
              </li>
            ))}
          </ul>
        </div>

        <div className="card p-4 space-y-2">
          <p className="text-xs font-semibold text-gray-900">Invoices ({deal.invoices.length})</p>
          {deal.invoices.length === 0 && (
            <p className="text-[11px] text-gray-400">No invoice drafts.</p>
          )}
          <ul className="space-y-2">
            {deal.invoices.map((d) => (
              <li key={d.id} className="rounded border border-amber-100 p-2 text-[11px]">
                <p className="font-medium text-gray-900 truncate">{d.title}</p>
                <p className="text-gray-500">
                  {formatValue(d.amount)} {d.currency} · {d.status}
                </p>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="card p-4 space-y-4">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs font-semibold text-gray-900 flex items-center gap-1.5">
            <Clock size={14} />
            Timeline
          </p>
        </div>

        <div className="flex gap-2">
          <input
            className="input flex-1 text-xs"
            placeholder="Add timeline note…"
            value={noteTitle}
            onChange={(e) => setNoteTitle(e.target.value)}
          />
          <button
            type="button"
            disabled={!noteTitle.trim() || noteMutation.isPending}
            onClick={() => noteMutation.mutate(noteTitle.trim())}
            className="text-xs px-3 py-1.5 rounded border border-gray-200 disabled:opacity-50"
          >
            Add note
          </button>
        </div>

        {timelineGroups.length === 0 && (
          <p className="text-[11px] text-gray-400">No timeline events yet.</p>
        )}

        <div className="space-y-4">
          {timelineGroups.map((group) => (
            <div key={group.date}>
              <p className="text-[11px] font-semibold text-gray-500 mb-2">{group.label}</p>
              <ul className="space-y-2 pl-3 border-l border-gray-200">
                {group.items.map((event) => (
                  <li key={event.id} className="relative pl-4">
                    <span
                      className={cn(
                        "absolute left-[-5px] top-1.5 w-2 h-2 rounded-full",
                        EVENT_DOT[event.event_type] ?? "bg-gray-400",
                      )}
                    />
                    <p className="text-[11px] text-gray-900">{event.title}</p>
                    <p className="text-[9px] text-gray-400 capitalize">{event.event_type.replace("_", " ")}</p>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <p className="text-[9px] text-gray-400 flex items-center gap-1">
          <AlertTriangle size={10} />
          Timeline updates automatically from proposals, contracts, and invoices. Status changes are manual only.
        </p>
      </div>
    </div>
  );
}
