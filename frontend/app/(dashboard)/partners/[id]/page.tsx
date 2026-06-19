"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  ArrowLeft,
  Handshake,
  Sparkles,
  Loader2,
  Clock,
  Package,
  Users,
} from "lucide-react";
import toast from "react-hot-toast";
import { partnersApi, PartnerAiInsights, PartnerType, PARTNER_TYPE_LABELS } from "@/lib/api";

function formatMoney(val: number | string | null | undefined): string {
  if (val == null || val === "") return "—";
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(n)) return String(val);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

export default function PartnerDetailPage() {
  const params = useParams();
  const partnerId = params.id as string;
  const [insights, setInsights] = useState<PartnerAiInsights | null>(null);
  const [activityType, setActivityType] = useState("note");
  const [activityText, setActivityText] = useState("");

  const { data: hub, isLoading: loadingHub, refetch: refetchHub } = useQuery({
    queryKey: ["partner-hub", partnerId],
    queryFn: () => partnersApi.hub(partnerId).then((r) => r.data),
  });

  const insightsMutation = useMutation({
    mutationFn: () => partnersApi.aiInsights(partnerId).then((r) => r.data),
    onSuccess: (d) => {
      setInsights(d);
      toast.success("Partner insights generated");
    },
    onError: (err: Error) => toast.error(err.message || "Insights failed"),
  });

  const activityMutation = useMutation({
    mutationFn: () =>
      partnersApi.addActivity(partnerId, {
        activity_type: activityType,
        description: activityText.trim(),
      }),
    onSuccess: () => {
      setActivityText("");
      refetchHub();
      toast.success("Activity logged");
    },
    onError: (err: Error) => toast.error(err.message || "Failed to log activity"),
  });

  if (loadingHub || !hub) {
    return (
      <div className="p-6 flex items-center justify-center gap-2 text-sm text-gray-400">
        <Loader2 size={16} className="animate-spin" />
        Loading partner…
      </div>
    );
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <Link href="/partners" className="text-xs text-gray-500 hover:text-gray-800 flex items-center gap-1 mb-2">
          <ArrowLeft size={12} />
          Partner directory
        </Link>
        <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
          <Handshake size={20} className="text-violet-600" />
          {hub.name}
        </h1>
        {hub.company_name && <p className="text-sm text-gray-500">{hub.company_name}</p>}
        <div className="flex flex-wrap gap-2 mt-2 text-xs text-gray-600">
          {hub.partner_type && (
            <span className="px-2 py-0.5 rounded-full bg-violet-50 text-violet-800 capitalize">
              {PARTNER_TYPE_LABELS[hub.partner_type as PartnerType] ?? hub.partner_type}
            </span>
          )}
          {hub.country && <span>{hub.country}{hub.city ? `, ${hub.city}` : ""}</span>}
          {(hub.industries_json ?? []).map((ind) => (
            <span key={ind} className="px-2 py-0.5 rounded-full bg-gray-100">{ind}</span>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Leads", value: hub.leads_count },
          { label: "Won deals", value: hub.won_deals },
          { label: "Revenue", value: formatMoney(hub.revenue) },
          { label: "Commission", value: formatMoney(hub.commission) },
        ].map(({ label, value }) => (
          <div key={label} className="card p-3 text-center">
            <p className="text-lg font-semibold text-gray-900 tabular-nums">{value}</p>
            <p className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</p>
          </div>
        ))}
      </div>

      <div className="card p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Clock size={14} />
          Activity history
        </p>
        <div className="flex flex-wrap gap-2">
          <select className="input text-xs" value={activityType} onChange={(e) => setActivityType(e.target.value)}>
            <option value="note">Note</option>
            <option value="call">Call</option>
            <option value="email">Email</option>
            <option value="meeting">Meeting</option>
            <option value="match">Match</option>
          </select>
          <input
            className="input text-xs flex-1 min-w-[200px]"
            placeholder="Log activity…"
            value={activityText}
            onChange={(e) => setActivityText(e.target.value)}
          />
          <button
            type="button"
            disabled={!activityText.trim() || activityMutation.isPending}
            onClick={() => activityMutation.mutate()}
            className="text-xs px-3 py-1.5 rounded-lg bg-brand-600 text-white disabled:opacity-50"
          >
            Add
          </button>
        </div>
        {hub.activities.length === 0 ? (
          <p className="text-xs text-gray-400">No activities yet.</p>
        ) : (
          <ul className="space-y-2 max-h-48 overflow-y-auto">
            {hub.activities.map((a) => (
              <li key={a.id} className="text-xs border-b border-gray-50 pb-2">
                <p className="font-medium text-gray-800 capitalize">
                  {a.activity_type.replace("_", " ")}
                  <span className="font-normal text-gray-400 ml-2">
                    {format(parseISO(a.created_at), "MMM d, HH:mm")}
                  </span>
                </p>
                <p className="text-gray-600 mt-0.5">{a.description}</p>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card p-4">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5 mb-3">
            <Package size={14} />
            Related products ({hub.related_products.length})
          </p>
          {hub.related_products.length === 0 ? (
            <p className="text-xs text-gray-400">No product interests yet. Use Match partners on a product.</p>
          ) : (
            <ul className="space-y-2 max-h-64 overflow-y-auto">
              {hub.related_products.map((p) => (
                <li key={p.interest_id} className="text-xs border-b border-gray-50 pb-2">
                  <Link href={`/products/${p.product_id}`} className="font-medium text-brand-700 hover:underline">
                    {p.name}
                  </Link>
                  <p className="text-gray-500">
                    {p.category ?? "—"}
                    {p.interest_score != null ? ` · ${Math.round(p.interest_score * 100)}% match` : ""}
                  </p>
                  {p.notes && <p className="text-gray-600 mt-0.5">{p.notes}</p>}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card p-4">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5 mb-3">
            <Users size={14} />
            Related leads ({hub.related_leads.length + hub.matched_leads.length})
          </p>
          {hub.related_leads.length === 0 && hub.matched_leads.length === 0 ? (
            <p className="text-xs text-gray-400">No leads linked yet.</p>
          ) : (
            <ul className="space-y-2 max-h-64 overflow-y-auto">
              {hub.related_leads.map((lead) => (
                <li key={lead.id} className="text-xs border-b border-gray-50 pb-2">
                  <Link href="/crm" className="font-medium text-gray-900 hover:text-brand-700">
                    {lead.name}
                  </Link>
                  <p className="text-gray-500 capitalize">{lead.status.replace("_", " ")} · referred</p>
                </li>
              ))}
              {hub.matched_leads.map((lead) => (
                <li key={`m-${lead.id}`} className="text-xs border-b border-gray-50 pb-2">
                  <Link href="/crm" className="font-medium text-gray-900 hover:text-brand-700">
                    {lead.name}
                  </Link>
                  <p className="text-gray-500 capitalize">
                    {lead.status.replace("_", " ")} · suggested match
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="card p-4 space-y-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <Sparkles size={14} className="text-violet-600" />
            Referral AI insights
          </p>
          <button
            type="button"
            disabled={insightsMutation.isPending}
            onClick={() => insightsMutation.mutate()}
            className="text-xs px-3 py-1.5 rounded-lg border border-violet-200 bg-violet-50 text-violet-800 disabled:opacity-50"
          >
            {insightsMutation.isPending ? "Analyzing…" : "Generate insights"}
          </button>
        </div>
        {insights && (
          <div className="space-y-3 text-sm">
            <p className="text-gray-800">{insights.revenue_forecast}</p>
            {insights.recommended_actions.length > 0 && (
              <ul className="text-xs text-gray-600 space-y-0.5">
                {insights.recommended_actions.map((a, i) => (
                  <li key={i}>→ {a}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
