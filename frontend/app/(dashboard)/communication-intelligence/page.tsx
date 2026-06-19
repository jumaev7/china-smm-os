"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  Activity,
  Flame,
  Loader2,
  MessageCircle,
  MessagesSquare,
  RefreshCw,
  Scale,
  Timer,
  UserX,
  type LucideIcon,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  communicationIntelligenceApi,
  CommunicationClassification,
  CommunicationIntelligenceDetail,
  CommunicationIntelligenceListItem,
  CommunicationUrgency,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PartialErrorsBanner,
} from "@/components/ui/PageStates";

const CLASSIFICATION_STYLES: Record<CommunicationClassification, string> = {
  inquiry: "bg-sky-100 text-sky-900 border-sky-200",
  qualification: "bg-emerald-100 text-emerald-900 border-emerald-200",
  negotiation: "bg-amber-100 text-amber-900 border-amber-200",
  proposal: "bg-violet-100 text-violet-900 border-violet-200",
  closing: "bg-red-100 text-red-900 border-red-200",
  inactive: "bg-gray-100 text-gray-700 border-gray-200",
};

const URGENCY_STYLES: Record<CommunicationUrgency, string> = {
  urgent: "bg-red-50 text-red-800 border-red-200",
  high: "bg-orange-50 text-orange-800 border-orange-200",
  medium: "bg-yellow-50 text-yellow-800 border-yellow-200",
  low: "bg-gray-50 text-gray-600 border-gray-200",
};

function KpiCard({
  label,
  value,
  icon: Icon,
  tone,
}: {
  label: string;
  value: number;
  icon: LucideIcon;
  tone: string;
}) {
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-gray-400 font-medium">{label}</p>
          <p className="text-2xl font-semibold text-gray-900 mt-1 tabular-nums">{value}</p>
        </div>
        <div className={cn("w-9 h-9 rounded-lg flex items-center justify-center border", tone)}>
          <Icon size={18} />
        </div>
      </div>
    </div>
  );
}

function ClassificationBadge({ classification }: { classification: CommunicationClassification }) {
  return (
    <span
      className={cn(
        "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
        CLASSIFICATION_STYLES[classification],
      )}
    >
      {classification}
    </span>
  );
}

function DetailPanel({ detail }: { detail: CommunicationIntelligenceDetail }) {
  const intel = detail.intelligence;
  return (
    <div className="card p-4 space-y-4 sticky top-4">
      <div>
        <p className="text-[10px] uppercase tracking-wide text-gray-400">Conversation detail</p>
        <h2 className="text-lg font-semibold text-gray-900 mt-1">{detail.contact_name}</h2>
        <p className="text-sm text-gray-500 capitalize">{detail.channel}</p>
        <div className="flex flex-wrap gap-2 mt-2">
          <ClassificationBadge classification={intel.classification} />
          <span className="text-[10px] px-2 py-0.5 rounded-full border bg-orange-50 text-orange-900 border-orange-200 font-semibold tabular-nums">
            {intel.health_score}/100
          </span>
          <span
            className={cn(
              "text-[10px] px-2 py-0.5 rounded-full border capitalize",
              URGENCY_STYLES[intel.urgency],
            )}
          >
            {intel.urgency}
          </span>
        </div>
      </div>

      {intel.insights.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-900 mb-1">Insights</p>
          <ul className="space-y-1">
            {intel.insights.map((item) => (
              <li key={item} className="text-xs text-gray-600 flex items-start gap-1.5 capitalize">
                <span className="text-brand-600 mt-0.5">•</span>
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <p className="text-xs font-semibold text-gray-900 mb-1">Recommendations</p>
        <ul className="space-y-1">
          {intel.recommended_actions.map((action) => (
            <li key={action} className="text-xs text-gray-700">
              {action}
            </li>
          ))}
        </ul>
      </div>

      {detail.linked_crm.lead_id && (
        <div>
          <p className="text-xs font-semibold text-gray-900 mb-1">Linked CRM</p>
          <Link href={`/crm?lead=${detail.linked_crm.lead_id}`} className="text-xs text-brand-700 hover:underline">
            {detail.linked_crm.lead_name || "Open in CRM"} →
          </Link>
        </div>
      )}

      {detail.linked_deal_room && (
        <div>
          <p className="text-xs font-semibold text-gray-900 mb-1">Deal Room</p>
          <Link
            href={`/deal-room?id=${detail.linked_deal_room.deal_room_id}`}
            className="text-xs text-brand-700 hover:underline"
          >
            {detail.linked_deal_room.deal_name} →
          </Link>
        </div>
      )}

      {detail.linked_proposals.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-900 mb-1">Linked proposals</p>
          <ul className="space-y-1">
            {detail.linked_proposals.map((p) => (
              <li key={p.proposal_id} className="text-xs text-gray-600">
                {p.title} · {p.status}
              </li>
            ))}
          </ul>
        </div>
      )}

      <Link
        href={`/unified-inbox?id=${encodeURIComponent(detail.conversation_id)}`}
        className="text-xs text-brand-700 hover:underline inline-flex items-center gap-1"
      >
        <MessageCircle size={12} />
        Open in Unified Inbox
      </Link>
    </div>
  );
}

export default function CommunicationIntelligencePage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [channelFilter, setChannelFilter] = useState("");
  const [classificationFilter, setClassificationFilter] = useState<CommunicationClassification | "">("");
  const [urgencyFilter, setUrgencyFilter] = useState<CommunicationUrgency | "">("");

  const listParams = useMemo(
    () => ({
      channel: channelFilter || undefined,
      classification: classificationFilter || undefined,
      urgency: urgencyFilter || undefined,
      limit: 100,
    }),
    [channelFilter, classificationFilter, urgencyFilter],
  );

  const { data: overview, isLoading: overviewLoading, error: overviewError } = useQuery({
    queryKey: ["communication-intelligence-overview"],
    queryFn: () => communicationIntelligenceApi.overview().then((r) => r.data),
  });

  const { data: listData, isLoading: listLoading } = useQuery({
    queryKey: ["communication-intelligence-conversations", listParams],
    queryFn: () => communicationIntelligenceApi.conversations(listParams).then((r) => r.data),
  });

  const { data: detail, isLoading: detailLoading } = useQuery({
    queryKey: ["communication-intelligence-detail", selectedId],
    queryFn: () => communicationIntelligenceApi.detail(selectedId!).then((r) => r.data),
    enabled: !!selectedId,
  });

  const recalcMutation = useMutation({
    mutationFn: () => communicationIntelligenceApi.recalculate().then((r) => r.data),
    onSuccess: (data) => {
      toast.success(data.message);
      queryClient.invalidateQueries({ queryKey: ["communication-intelligence-overview"] });
      queryClient.invalidateQueries({ queryKey: ["communication-intelligence-conversations"] });
    },
    onError: () => toast.error("Recalculate failed"),
  });

  if (overviewError) {
    return <ErrorState message="Failed to load communication intelligence" />;
  }

  const items = listData?.items ?? [];

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <MessagesSquare size={22} className="text-brand-600" />
            Communication Intelligence
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Read-only conversation analysis — no automatic messaging or CRM updates.
          </p>
        </div>
        <button
          type="button"
          className="btn-secondary text-xs inline-flex items-center gap-1.5"
          disabled={recalcMutation.isPending}
          onClick={() => recalcMutation.mutate()}
        >
          {recalcMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          Recalculate
        </button>
      </div>

      {overview?.errors && overview.errors.length > 0 && (
        <PartialErrorsBanner errors={overview.errors} />
      )}

      {overviewLoading ? (
        <LoadingState message="Loading overview…" />
      ) : overview ? (
        <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3">
          <KpiCard
            label="Active Buyers"
            value={overview.active_buyers}
            icon={Activity}
            tone="bg-emerald-50 text-emerald-800 border-emerald-200"
          />
          <KpiCard
            label="Hot Buyers"
            value={overview.hot_buyers}
            icon={Flame}
            tone="bg-red-50 text-red-800 border-red-200"
          />
          <KpiCard
            label="Negotiations"
            value={overview.negotiations}
            icon={Scale}
            tone="bg-amber-50 text-amber-800 border-amber-200"
          />
          <KpiCard
            label="Follow-ups Required"
            value={overview.follow_ups_required}
            icon={Timer}
            tone="bg-orange-50 text-orange-800 border-orange-200"
          />
          <KpiCard
            label="Inactive Conversations"
            value={overview.inactive_conversations}
            icon={UserX}
            tone="bg-gray-50 text-gray-700 border-gray-200"
          />
        </div>
      ) : null}

      <div className="card p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-900">Filters</p>
        <div className="flex flex-wrap gap-3">
          <select
            value={channelFilter}
            onChange={(e) => setChannelFilter(e.target.value)}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white"
          >
            <option value="">All channels</option>
            <option value="wechat">WeChat</option>
            <option value="wecom">WeCom</option>
            <option value="whatsapp">WhatsApp</option>
            <option value="email">Email</option>
            <option value="manual">Manual</option>
          </select>
          <select
            value={classificationFilter}
            onChange={(e) => setClassificationFilter(e.target.value as CommunicationClassification | "")}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white"
          >
            <option value="">All classifications</option>
            <option value="inquiry">Inquiry</option>
            <option value="qualification">Qualification</option>
            <option value="negotiation">Negotiation</option>
            <option value="proposal">Proposal</option>
            <option value="closing">Closing</option>
            <option value="inactive">Inactive</option>
          </select>
          <select
            value={urgencyFilter}
            onChange={(e) => setUrgencyFilter(e.target.value as CommunicationUrgency | "")}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 bg-white"
          >
            <option value="">All urgency</option>
            <option value="urgent">Urgent</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 card p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-900">
            Conversations ({listData?.total ?? 0})
          </p>
          {listLoading ? (
            <LoadingState message="Loading conversations…" />
          ) : items.length === 0 ? (
            <EmptyState
              title="No conversations match filters"
              description="Start customer conversations in Unified Inbox or Communications."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-gray-100 text-[10px] uppercase tracking-wide text-gray-400">
                    <th className="py-2 px-2 font-medium">Contact</th>
                    <th className="py-2 px-2 font-medium">Channel</th>
                    <th className="py-2 px-2 font-medium">Health</th>
                    <th className="py-2 px-2 font-medium">Classification</th>
                    <th className="py-2 px-2 font-medium">Urgency</th>
                    <th className="py-2 px-2 font-medium">Recommended Action</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((row: CommunicationIntelligenceListItem) => (
                    <tr
                      key={row.conversation_id}
                      onClick={() => setSelectedId(row.conversation_id)}
                      className={cn(
                        "border-b border-gray-50 cursor-pointer hover:bg-brand-50/30",
                        selectedId === row.conversation_id && "bg-brand-50/50",
                      )}
                    >
                      <td className="py-2 px-2 text-xs font-medium text-gray-900">{row.contact_name}</td>
                      <td className="py-2 px-2 text-xs text-gray-500 capitalize">{row.channel}</td>
                      <td className="py-2 px-2 text-xs tabular-nums font-semibold text-orange-800">
                        {row.health_score}
                      </td>
                      <td className="py-2 px-2">
                        <ClassificationBadge classification={row.classification} />
                      </td>
                      <td className="py-2 px-2">
                        <span
                          className={cn(
                            "text-[10px] px-2 py-0.5 rounded-full border capitalize",
                            URGENCY_STYLES[row.urgency],
                          )}
                        >
                          {row.urgency}
                        </span>
                      </td>
                      <td className="py-2 px-2 text-xs text-gray-600 max-w-[200px] truncate">
                        {row.recommended_action}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div>
          {selectedId && detailLoading && <LoadingState message="Loading detail…" />}
          {detail && <DetailPanel detail={detail} />}
          {!selectedId && (
            <div className="card p-4 text-xs text-gray-500">Select a conversation to view intelligence detail.</div>
          )}
        </div>
      </div>
    </div>
  );
}
