"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  Building2,
  Briefcase,
  CircleDollarSign,
  Handshake,
  Loader2,
  Search,
  Sparkles,
  TrendingUp,
  Users,
  AlertTriangle,
  ArrowRight,
  ListTodo,
  type LucideIcon,
} from "lucide-react";
import toast from "react-hot-toast";
import { clientsApi, Client, salesDepartmentApi, SalesDeptAiBriefing, normalizeList } from "@/lib/api";
import { cn } from "@/lib/utils";
import { SimpleBarChart } from "@/components/analytics/SimpleBarChart";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PartialErrorsBanner,
} from "@/components/ui/PageStates";
import { useTranslation } from "@/lib/I18nProvider";

function fmtMoney(val: number | string | null | undefined): string {
  if (val == null || val === "") return "—";
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(n)) return String(val);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

function KpiCard({
  label,
  value,
  href,
  icon: Icon,
  color,
}: {
  label: string;
  value: string | number;
  href: string;
  icon: LucideIcon;
  color: string;
}) {
  return (
    <Link href={href} className="card p-4 hover:ring-1 hover:ring-brand-200 transition-shadow block">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-[10px] uppercase tracking-wide text-gray-400 font-medium">{label}</p>
          <p className="text-xl font-semibold text-gray-900 mt-1 tabular-nums">{value}</p>
        </div>
        <div className={cn("w-9 h-9 rounded-lg flex items-center justify-center", color)}>
          <Icon size={18} />
        </div>
      </div>
    </Link>
  );
}

const QUICK_LINKS = [
  { href: "/crm", labelKey: "salesDepartment.openCrm" },
  { href: "/crm/deals", labelKey: "salesDepartment.openDealRoom" },
  { href: "/buyer-finder", labelKey: "salesDepartment.openBuyerFinder" },
  { href: "/revenue", labelKey: "salesDepartment.openRevenue" },
  { href: "/partners", labelKey: "salesDepartment.openPartners" },
];

export default function SalesDepartmentPage() {
  const { t } = useTranslation();
  const [clientId, setClientId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [briefing, setBriefing] = useState<SalesDeptAiBriefing | null>(null);

  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list({ limit: 200 }).then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clients);

  const params = useMemo(
    () => ({
      client_id: clientId || undefined,
      date_from: dateFrom ? `${dateFrom}T00:00:00Z` : undefined,
      date_to: dateTo ? `${dateTo}T23:59:59Z` : undefined,
    }),
    [clientId, dateFrom, dateTo],
  );

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sales-department-dashboard", params],
    queryFn: () => salesDepartmentApi.dashboard(params).then((r) => r.data),
  });

  const briefingMutation = useMutation({
    mutationFn: () => salesDepartmentApi.aiBriefing(clientId || undefined).then((r) => r.data),
    onSuccess: (res) => {
      setBriefing(res);
      toast.success("AI briefing generated");
    },
    onError: (err: Error) => toast.error(err.message || "Briefing failed"),
  });

  if (isLoading) return <LoadingState message={t("salesDepartment.loading")} />;
  if (isError || !data) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : t("salesDepartment.loadError")}
        onRetry={() => refetch()}
      />
    );
  }

  const ov = data.overview;
  const funnel = data.sales_funnel;
  const leadIntel = data.lead_intelligence;
  const funnelChart = [
    { label: "Leads", value: funnel.leads },
    { label: "Contact", value: funnel.contacted },
    { label: "Qual.", value: funnel.qualified },
    { label: "Proposal", value: funnel.proposal_sent },
    { label: "Neg.", value: funnel.negotiation },
    { label: "Won", value: funnel.won },
  ];

  const aq = data.action_queue;
  const actionCount =
    aq.overdue_followups.length +
    aq.pending_proposals.length +
    aq.unpaid_invoices.length +
    aq.high_priority_sales_agent_recommendations.length +
    aq.risky_deals.length;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Building2 size={22} className="text-violet-600" />
            {t("salesDepartment.title")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t("salesDepartment.subtitle")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {QUICK_LINKS.map(({ href, labelKey }) => (
            <Link key={href} href={href} className="text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 hover:bg-gray-50">
              {t(labelKey)}
            </Link>
          ))}
        </div>
      </div>

      {(data.errors?.length ?? 0) > 0 && <PartialErrorsBanner errors={data.errors} />}

      <div className="card p-4 grid sm:grid-cols-3 gap-3">
        <div>
          <label className="label">{t("common.allClients")}</label>
          <select className="input" value={clientId} onChange={(e) => setClientId(e.target.value)}>
            <option value="">{t("common.allClients")}</option>
            {clientOptions.map((c) => (
              <option key={c.id} value={c.id}>{c.company_name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">From</label>
          <input type="date" className="input" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </div>
        <div>
          <label className="label">To</label>
          <input type="date" className="input" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
        <KpiCard label="Leads" value={ov.total_leads} href="/crm" icon={Users} color="bg-blue-50 text-blue-600" />
        <KpiCard label="Deals" value={ov.active_deals} href="/crm/deals" icon={Briefcase} color="bg-violet-50 text-violet-600" />
        <KpiCard label="Revenue" value={fmtMoney(ov.closed_revenue)} href="/revenue" icon={CircleDollarSign} color="bg-emerald-50 text-emerald-600" />
        <KpiCard label="Commission" value={fmtMoney(ov.commission_earned)} href="/revenue" icon={TrendingUp} color="bg-amber-50 text-amber-600" />
        <KpiCard label="Pipeline" value={fmtMoney(ov.pipeline_value)} href="/crm/deals" icon={Briefcase} color="bg-sky-50 text-sky-600" />
        <KpiCard label="Buyers" value={ov.buyer_recommendations_count} href="/buyer-finder" icon={Search} color="bg-indigo-50 text-indigo-600" />
        <KpiCard label="Partners" value={ov.partner_count} href="/partners" icon={Handshake} color="bg-purple-50 text-purple-600" />
      </div>

      {leadIntel && (
        <div className="card p-4 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Lead intelligence</p>
            <Link href="/crm" className="text-xs text-brand-700 hover:underline flex items-center gap-1">
              Open CRM <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid sm:grid-cols-4 gap-3 text-center">
            <div className="rounded-lg bg-orange-50 border border-orange-100 p-3">
              <p className="text-[10px] uppercase text-orange-700">Hot leads</p>
              <p className="text-xl font-semibold text-orange-950 tabular-nums">{leadIntel.hot_leads}</p>
            </div>
            <div className="rounded-lg bg-violet-50 border border-violet-100 p-3">
              <p className="text-[10px] uppercase text-violet-700">Qualified</p>
              <p className="text-xl font-semibold text-violet-950 tabular-nums">{leadIntel.qualified_leads}</p>
            </div>
            <div className="rounded-lg bg-amber-50 border border-amber-100 p-3">
              <p className="text-[10px] uppercase text-amber-700">Neglected</p>
              <p className="text-xl font-semibold text-amber-950 tabular-nums">{leadIntel.neglected_leads}</p>
            </div>
            <div className="rounded-lg bg-gray-50 border border-gray-200 p-3">
              <p className="text-[10px] uppercase text-gray-600">No activity</p>
              <p className="text-xl font-semibold text-gray-900 tabular-nums">{leadIntel.leads_without_activity}</p>
            </div>
          </div>

          {(leadIntel.top_hot_leads?.length ?? 0) > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-800 mb-2">Top hot leads</p>
              <ul className="space-y-2">
                {leadIntel.top_hot_leads.map((l) => (
                  <li key={l.lead_id} className="flex items-center justify-between gap-2 text-xs rounded-lg border border-orange-100 bg-orange-50/30 p-2">
                    <div>
                      <Link href={`/crm?lead=${l.lead_id}`} className="font-medium text-orange-950 hover:underline">
                        {l.name}
                      </Link>
                      {l.company && <p className="text-[10px] text-gray-500">{l.company}</p>}
                    </div>
                    <span className="text-sm font-bold tabular-nums text-orange-900">
                      {l.lead_score} 🔥
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {data.sales_manager && (
        <div className="card p-4 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Briefcase size={14} className="text-violet-600" />
              AI Executive Summary
            </p>
            <Link href="/sales-manager" className="text-xs text-brand-700 hover:underline flex items-center gap-1">
              Sales Manager <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid sm:grid-cols-3 lg:grid-cols-6 gap-3 text-center">
            <div className="rounded-lg bg-blue-50 border border-blue-100 p-2">
              <p className="text-lg font-semibold tabular-nums text-blue-900">{data.sales_manager.leads_count}</p>
              <p className="text-[10px] text-blue-700">Leads</p>
            </div>
            <div className="rounded-lg bg-orange-50 border border-orange-100 p-2">
              <p className="text-lg font-semibold tabular-nums text-orange-900">{data.sales_manager.hot_leads}</p>
              <p className="text-[10px] text-orange-700">Hot</p>
            </div>
            <div className="rounded-lg bg-emerald-50 border border-emerald-100 p-2">
              <p className="text-lg font-semibold tabular-nums text-emerald-900">{data.sales_manager.opportunities_count}</p>
              <p className="text-[10px] text-emerald-700">Opportunities</p>
            </div>
            <div className="rounded-lg bg-red-50 border border-red-100 p-2">
              <p className="text-lg font-semibold tabular-nums text-red-900">{data.sales_manager.risks_count}</p>
              <p className="text-[10px] text-red-700">Risks</p>
            </div>
            <div className="rounded-lg bg-amber-50 border border-amber-100 p-2">
              <p className="text-lg font-semibold tabular-nums text-amber-900">{data.sales_manager.overdue_tasks}</p>
              <p className="text-[10px] text-amber-700">Overdue tasks</p>
            </div>
            <div className="rounded-lg bg-violet-50 border border-violet-100 p-2">
              <p className="text-lg font-semibold tabular-nums text-violet-900">{data.sales_manager.active_proposals}</p>
              <p className="text-[10px] text-violet-700">Proposals</p>
            </div>
          </div>
          {(data.sales_manager.top_recommendations?.length ?? 0) > 0 && (
            <ul className="space-y-2 text-xs">
              {data.sales_manager.top_recommendations.slice(0, 5).map((r, i) => (
                <li key={i} className="flex items-start justify-between gap-2 border-b border-gray-50 pb-2">
                  <Link href="/sales-manager" className="font-medium text-brand-800 hover:underline truncate">
                    {r.title}
                  </Link>
                  <span className="text-[10px] text-gray-400 capitalize shrink-0">{r.priority}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {data.sales_assistant && (
        <div className="card p-4">
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Sparkles size={14} className="text-violet-600" />
              Sales Assistant
            </p>
            <Link href="/sales-assistant" className="text-xs text-brand-700 flex items-center gap-0.5">
              Open <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
            <div className="rounded-lg bg-sky-50 border border-sky-100 p-2 text-center">
              <p className="text-lg font-semibold tabular-nums text-sky-900">{data.sales_assistant.open_count}</p>
              <p className="text-[10px] text-sky-700">Open</p>
            </div>
            <div className="rounded-lg bg-red-50 border border-red-100 p-2 text-center">
              <p className="text-lg font-semibold tabular-nums text-red-900">{data.sales_assistant.urgent_count}</p>
              <p className="text-[10px] text-red-700">Urgent</p>
            </div>
          </div>
          {(data.sales_assistant.top_recommendations?.length ?? 0) === 0 ? (
            <p className="text-xs text-gray-400">No open recommendations — run a sales scan.</p>
          ) : (
            <ul className="space-y-2 text-xs">
              {data.sales_assistant.top_recommendations.slice(0, 5).map((r) => (
                <li key={r.id} className="flex items-start justify-between gap-2 border-b border-gray-50 pb-2">
                  <Link href="/sales-assistant" className="font-medium text-brand-800 hover:underline truncate">
                    {r.title}
                  </Link>
                  <span className="text-[10px] text-gray-400 capitalize shrink-0">{r.priority}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {data.operator_tasks && (
        <div className="card p-4">
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <ListTodo size={14} className="text-violet-600" />
              Operator Tasks
            </p>
            <Link href="/operator-tasks" className="text-xs text-brand-700 flex items-center gap-0.5">
              Open <ArrowRight size={12} />
            </Link>
          </div>
          <div className="grid grid-cols-3 gap-3 mb-3">
            <div className="rounded-lg bg-sky-50 border border-sky-100 p-2 text-center">
              <p className="text-lg font-semibold tabular-nums text-sky-900">
                {data.operator_tasks.open_count}
              </p>
              <p className="text-[10px] text-sky-700">Open</p>
            </div>
            <div className="rounded-lg bg-red-50 border border-red-100 p-2 text-center">
              <p className="text-lg font-semibold tabular-nums text-red-900">
                {data.operator_tasks.urgent_count}
              </p>
              <p className="text-[10px] text-red-700">Urgent</p>
            </div>
            <div className="rounded-lg bg-amber-50 border border-amber-100 p-2 text-center">
              <p className="text-lg font-semibold tabular-nums text-amber-900">
                {data.operator_tasks.overdue_count}
              </p>
              <p className="text-[10px] text-amber-700">Overdue</p>
            </div>
          </div>
          {(data.operator_tasks.top_tasks?.length ?? 0) === 0 ? (
            <p className="text-xs text-gray-400">No open operator tasks — generate from Operator Tasks page.</p>
          ) : (
            <ul className="space-y-2 text-xs">
              {data.operator_tasks.top_tasks.slice(0, 5).map((task) => (
                <li key={task.id} className="flex items-start justify-between gap-2 border-b border-gray-50 pb-2">
                  <Link href="/operator-tasks" className="font-medium text-brand-800 hover:underline truncate">
                    {task.title}
                  </Link>
                  <span className="text-[10px] text-gray-400 capitalize shrink-0">{task.priority}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-4">
        <div className="card p-4 lg:col-span-2">
          <p className="text-sm font-semibold text-gray-900 mb-3">Sales funnel</p>
          <SimpleBarChart data={funnelChart} barClassName="bg-violet-500" />
          <p className="text-[10px] text-gray-400 mt-2">
            Lead → Contacted → Qualified → Proposal → Negotiation → Won ({funnel.lost} lost)
          </p>
        </div>

        <div className="card p-4 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Sparkles size={14} className="text-violet-600" />
              AI Briefing
            </p>
            <button
              type="button"
              className="text-xs btn-primary py-1 px-2"
              disabled={briefingMutation.isPending}
              onClick={() => briefingMutation.mutate()}
            >
              {briefingMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : "Generate"}
            </button>
          </div>
          {briefing ? (
            <div className="space-y-3 text-xs">
              <p className="text-gray-700">{briefing.executive_summary}</p>
              {briefing.what_is_working.length > 0 && (
                <div>
                  <p className="font-semibold text-emerald-800 mb-1">Working</p>
                  <ul className="list-disc pl-4 text-gray-600 space-y-0.5">
                    {briefing.what_is_working.map((x) => <li key={x}>{x}</li>)}
                  </ul>
                </div>
              )}
              {briefing.risks.length > 0 && (
                <div>
                  <p className="font-semibold text-red-800 mb-1">Risks</p>
                  <ul className="list-disc pl-4 text-gray-600 space-y-0.5">
                    {briefing.risks.map((x) => <li key={x}>{x}</li>)}
                  </ul>
                </div>
              )}
              {briefing.opportunities.length > 0 && (
                <div>
                  <p className="font-semibold text-sky-800 mb-1">Opportunities</p>
                  <ul className="list-disc pl-4 text-gray-600 space-y-0.5">
                    {briefing.opportunities.map((x) => <li key={x}>{x}</li>)}
                  </ul>
                </div>
              )}
              {briefing.recommended_actions.length > 0 && (
                <div>
                  <p className="font-semibold text-violet-800 mb-1">Recommended actions</p>
                  <ul className="list-disc pl-4 text-gray-600 space-y-0.5">
                    {briefing.recommended_actions.map((x) => <li key={x}>{x}</li>)}
                  </ul>
                </div>
              )}
              <p className="text-[10px] text-gray-400">
                Priority score {Math.round(briefing.priority_score)} · {briefing.source}
              </p>
            </div>
          ) : (
            <p className="text-xs text-gray-400">Generate an executive briefing from current metrics.</p>
          )}
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card p-4">
          <p className="text-sm font-semibold text-gray-900 mb-3">Top products</p>
          {data.top_products.length === 0 ? (
            <EmptyState title="No product data" description="Add products and CRM activity to see rankings." />
          ) : (
            <ul className="space-y-2 text-sm">
              {data.top_products.map((p) => (
                <li key={p.product_id} className="flex justify-between gap-2 border-b border-gray-50 pb-2">
                  <Link href={`/products/${p.product_id}`} className="font-medium text-brand-800 hover:text-brand-950 truncate">
                    {p.product_name}
                  </Link>
                  <span className="text-xs text-gray-500 tabular-nums shrink-0">
                    {p.leads_count} leads · {fmtMoney(p.revenue)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card p-4">
          <p className="text-sm font-semibold text-gray-900 mb-3">Top countries</p>
          {data.top_countries.length === 0 ? (
            <p className="text-xs text-gray-400">No country signals yet.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {data.top_countries.map((c) => (
                <li key={c.country} className="flex justify-between gap-2 border-b border-gray-50 pb-2">
                  <span className="font-medium text-gray-900">{c.country}</span>
                  <span className="text-xs text-gray-500 tabular-nums">
                    {c.leads_count} leads · score {Math.round(c.opportunity_score)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card p-4">
          <p className="text-sm font-semibold text-gray-900 mb-3">Attribution sources</p>
          {data.top_attribution_sources.length === 0 ? (
            <p className="text-xs text-gray-400">No attribution data yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-gray-400 text-left">
                    <th className="pb-2">Source</th>
                    <th className="pb-2">Clicks</th>
                    <th className="pb-2">Leads</th>
                    <th className="pb-2">Deals</th>
                    <th className="pb-2">Rev.</th>
                    <th className="pb-2">Conv.</th>
                  </tr>
                </thead>
                <tbody>
                  {data.top_attribution_sources.map((s) => (
                    <tr key={s.source} className="border-t border-gray-50">
                      <td className="py-1.5 capitalize">{s.source}</td>
                      <td className="py-1.5 tabular-nums">{s.clicks}</td>
                      <td className="py-1.5 tabular-nums">{s.leads}</td>
                      <td className="py-1.5 tabular-nums">{s.deals}</td>
                      <td className="py-1.5 tabular-nums">{fmtMoney(s.revenue)}</td>
                      <td className="py-1.5 tabular-nums">{s.conversion_rate}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card p-4">
          <p className="text-sm font-semibold text-gray-900 mb-3">Partner performance</p>
          {data.partner_performance.length === 0 ? (
            <p className="text-xs text-gray-400">No partner-attributed activity yet.</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {data.partner_performance.map((p) => (
                <li key={p.partner_id} className="flex justify-between gap-2 border-b border-gray-50 pb-2">
                  <Link href={`/partners/${p.partner_id}`} className="font-medium text-brand-800 truncate">
                    {p.partner_name}
                  </Link>
                  <span className="text-xs text-gray-500 tabular-nums shrink-0">
                    {p.leads} leads · {fmtMoney(p.revenue)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="card p-4">
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <AlertTriangle size={14} className="text-amber-600" />
            Action queue
            {actionCount > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-800 tabular-nums">
                {actionCount}
              </span>
            )}
          </p>
          <Link href="/sales-agent" className="text-xs text-brand-700 flex items-center gap-0.5">
            Sales Agent <ArrowRight size={12} />
          </Link>
        </div>
        {actionCount === 0 ? (
          <p className="text-xs text-gray-400">No urgent sales actions detected.</p>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 text-xs">
            {aq.overdue_followups.length > 0 && (
              <div>
                <p className="font-semibold text-gray-800 mb-1">Overdue follow-ups</p>
                <ul className="space-y-1">
                  {aq.overdue_followups.slice(0, 5).map((x) => (
                    <li key={x.lead_id}>
                      <Link href={`/crm?lead=${x.lead_id}`} className="text-brand-700 hover:text-brand-900">{x.name}</Link>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {aq.pending_proposals.length > 0 && (
              <div>
                <p className="font-semibold text-gray-800 mb-1">Pending proposals</p>
                <ul className="space-y-1">
                  {aq.pending_proposals.slice(0, 5).map((x) => (
                    <li key={x.proposal_id}>{x.title} <span className="text-gray-400">({x.status})</span></li>
                  ))}
                </ul>
              </div>
            )}
            {aq.unpaid_invoices.length > 0 && (
              <div>
                <p className="font-semibold text-gray-800 mb-1">Unpaid invoices</p>
                <ul className="space-y-1">
                  {aq.unpaid_invoices.slice(0, 5).map((x) => (
                    <li key={x.document_id}>
                      <Link href={`/crm?lead=${x.lead_id}`} className="text-brand-700">{x.title}</Link>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {aq.high_priority_sales_agent_recommendations.length > 0 && (
              <div>
                <p className="font-semibold text-gray-800 mb-1">High-priority recommendations</p>
                <ul className="space-y-1">
                  {aq.high_priority_sales_agent_recommendations.slice(0, 5).map((x) => (
                    <li key={x.id}>{x.title}</li>
                  ))}
                </ul>
              </div>
            )}
            {aq.risky_deals.length > 0 && (
              <div>
                <p className="font-semibold text-gray-800 mb-1">Risky deals</p>
                <ul className="space-y-1">
                  {aq.risky_deals.slice(0, 5).map((x) => (
                    <li key={x.deal_id}>
                      <Link href={`/crm/deals/${x.deal_id}`} className="text-brand-700">{x.title}</Link>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center text-xs">
        <div className="card p-2"><p className="font-semibold tabular-nums">{ov.new_leads}</p><p className="text-gray-400">New leads</p></div>
        <div className="card p-2"><p className="font-semibold tabular-nums">{ov.qualified_leads}</p><p className="text-gray-400">Qualified</p></div>
        <div className="card p-2"><p className="font-semibold tabular-nums">{ov.landing_page_leads}</p><p className="text-gray-400">Landing leads</p></div>
        <div className="card p-2"><p className="font-semibold tabular-nums">{ov.attribution_clicks}</p><p className="text-gray-400">Attr. clicks</p></div>
      </div>
    </div>
  );
}
