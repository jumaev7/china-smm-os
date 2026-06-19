"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bot,
  Building2,
  CircleDollarSign,
  Inbox,
  Lightbulb,
  ListTodo,
  Loader2,
  MessagesSquare,
  Sparkles,
  Target,
  TrendingUp,
  Users,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  multiAgentTeamApi,
  MultiAgentRecommendation,
  revenueForecastApi,
  salesDepartmentV3Api,
  SalesDeptV3Briefing,
  SalesDeptV3Opportunity,
  SalesDeptV3PriorityConversation,
  SalesDeptV3PriorityLead,
  SalesDeptV3RecommendedAction,
  SalesDeptV3Risk,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PartialErrorsBanner,
} from "@/components/ui/PageStates";

const PRIORITY_STYLES: Record<string, string> = {
  urgent: "bg-red-100 text-red-800 border-red-200",
  high: "bg-orange-100 text-orange-800 border-orange-200",
  medium: "bg-amber-100 text-amber-800 border-amber-200",
  low: "bg-gray-100 text-gray-700 border-gray-200",
};

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-red-100 text-red-900 border-red-300",
  high: "bg-orange-100 text-orange-900 border-orange-200",
  medium: "bg-amber-100 text-amber-900 border-amber-200",
  low: "bg-gray-100 text-gray-700 border-gray-200",
};

function fmtMoney(val: number | string | null | undefined): string {
  if (val == null || val === "") return "—";
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(n)) return String(val);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

function KpiCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="card p-4">
      <p className="text-[10px] uppercase tracking-wide text-gray-400 font-medium">{label}</p>
      <p className="text-2xl font-semibold text-gray-900 mt-1 tabular-nums">{value}</p>
    </div>
  );
}

function healthColor(score: number): string {
  if (score >= 75) return "text-emerald-600";
  if (score >= 50) return "text-amber-600";
  return "text-red-600";
}

export default function SalesDepartmentV3Page() {
  const [briefing, setBriefing] = useState<SalesDeptV3Briefing | null>(null);

  const { data: overview, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sales-department-v3-overview"],
    queryFn: () => salesDepartmentV3Api.overview().then((r) => r.data),
  });

  const { data: agentRecs } = useQuery({
    queryKey: ["multi-agent-dept-panel"],
    queryFn: () => multiAgentTeamApi.recommendations({ limit: 8 }).then((r) => r.data),
    enabled: !!overview,
    retry: 1,
  });

  const { data: forecastWidget } = useQuery({
    queryKey: ["revenue-forecast-dept-panel"],
    queryFn: () => revenueForecastApi.summaryWidget().then((r) => r.data),
    enabled: !!overview,
    retry: 1,
  });

  const briefingMutation = useMutation({
    mutationFn: () => salesDepartmentV3Api.generateBriefing().then((r) => r.data),
    onSuccess: (data) => {
      setBriefing(data);
      toast.success("Weekly briefing generated");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (isLoading) return <LoadingState message="Loading AI Sales Department v3…" />;
  if (isError || !overview) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load sales department v3"}
        onRetry={() => refetch()}
      />
    );
  }

  const exec = overview.executive_summary;
  const forecast = overview.revenue_forecast;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Building2 size={22} className="text-brand-600" />
            AI Sales Department v3
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Unified sales operating system — coordinates CRM, inbox, intelligence, and tasks. Manual actions only.
          </p>
        </div>
        <button
          type="button"
          className="btn-primary flex items-center gap-1.5"
          disabled={briefingMutation.isPending}
          onClick={() => briefingMutation.mutate()}
        >
          {briefingMutation.isPending ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Sparkles size={14} />
          )}
          Generate weekly briefing
        </button>
      </div>

      <PartialErrorsBanner errors={overview.errors} />

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900">1. Executive Summary</p>
        <div className="card p-4 space-y-3">
          <p className="text-sm text-gray-700">{exec.summary}</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
            <KpiCard label="Health score" value={exec.business_health_score} />
            <KpiCard label="Hot leads" value={exec.hot_leads} />
            <KpiCard label="Priority leads" value={exec.priority_leads} />
            <KpiCard label="Opportunities" value={exec.active_opportunities} />
            <KpiCard label="Risks" value={exec.open_risks} />
            <KpiCard label="Overdue actions" value={exec.overdue_actions} />
            <KpiCard label="Comm. health" value={Math.round(exec.communication_health)} />
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900">2. Top Opportunities</p>
        <div className="card p-4">
          {overview.top_opportunities.length === 0 ? (
            <EmptyState title="No opportunities" description="Pipeline looks stable." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-gray-100 text-[10px] uppercase tracking-wide text-gray-400">
                    <th className="py-2 px-2 font-medium">Title</th>
                    <th className="py-2 px-2 font-medium">Source</th>
                    <th className="py-2 px-2 font-medium">Health</th>
                    <th className="py-2 px-2 font-medium">Close %</th>
                    <th className="py-2 px-2 font-medium">Risk</th>
                    <th className="py-2 px-2 font-medium">Priority</th>
                  </tr>
                </thead>
                <tbody>
                  {overview.top_opportunities.map((o: SalesDeptV3Opportunity) => (
                    <tr key={o.opportunity_id} className="border-b border-gray-50">
                      <td className="py-2 px-2 text-xs text-gray-800">{o.title}</td>
                      <td className="py-2 px-2 text-xs text-gray-500 capitalize">{o.source}</td>
                      <td className="py-2 px-2 text-xs tabular-nums">{o.opportunity_health}</td>
                      <td className="py-2 px-2 text-xs tabular-nums">{Math.round(o.closing_probability)}%</td>
                      <td className="py-2 px-2 text-xs capitalize">{o.deal_risk}</td>
                      <td className="py-2 px-2">
                        <span
                          className={cn(
                            "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
                            PRIORITY_STYLES[o.priority] ?? PRIORITY_STYLES.medium,
                          )}
                        >
                          {o.priority}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      {overview.buyer_intelligence?.overview && (
        <section className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Buyer opportunities</p>
            <Link href="/buyer-intelligence" className="text-xs text-brand-700 hover:underline">
              Buyer Intelligence →
            </Link>
          </div>
          <div className="card p-4 grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
            <div>
              <p className="text-[10px] text-gray-500">Hot buyers</p>
              <p className="text-lg font-semibold">{overview.buyer_intelligence.overview.hot_buyers}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500">Strategic</p>
              <p className="text-lg font-semibold">{overview.buyer_intelligence.overview.strategic_buyers}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500">At risk</p>
              <p className="text-lg font-semibold">{overview.buyer_intelligence.overview.at_risk_buyers}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500">Avg score</p>
              <p className="text-lg font-semibold">{overview.buyer_intelligence.overview.average_buyer_score}</p>
            </div>
          </div>
        </section>
      )}

      {overview.buyer_discovery?.overview && (
        <section className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Buyer opportunity panel</p>
            <Link href="/buyer-discovery" className="text-xs text-brand-700 hover:underline">
              Buyer Discovery →
            </Link>
          </div>
          <div className="card p-4 grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
            <div>
              <p className="text-[10px] text-gray-500">Discovered</p>
              <p className="text-lg font-semibold">{overview.buyer_discovery.overview.total_buyers}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500">High potential</p>
              <p className="text-lg font-semibold">{overview.buyer_discovery.overview.high_potential}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500">Strategic</p>
              <p className="text-lg font-semibold">{overview.buyer_discovery.overview.strategic}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500">Avg score</p>
              <p className="text-lg font-semibold">
                {overview.buyer_discovery.overview.average_opportunity_score}
              </p>
            </div>
          </div>
          {(overview.buyer_discovery.highest_potential_buyers?.length ?? 0) > 0 && (
            <ul className="text-xs text-gray-600 space-y-1">
              {overview.buyer_discovery.highest_potential_buyers!.slice(0, 3).map((b) => (
                <li key={b.buyer_id}>
                  → {b.company_name} (score {b.opportunity_score})
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {overview.marketplace?.overview && (
        <section className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Marketplace exchange</p>
            <Link href="/marketplace" className="text-xs text-brand-700 hover:underline">
              Marketplace →
            </Link>
          </div>
          <div className="card p-4 grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
            <div>
              <p className="text-[10px] text-gray-500">Listed</p>
              <p className="text-lg font-semibold">{overview.marketplace.overview.total_opportunities}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500">Open</p>
              <p className="text-lg font-semibold">{overview.marketplace.overview.open_opportunities}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500">Interests</p>
              <p className="text-lg font-semibold">{overview.marketplace.overview.total_interests}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500">Claims</p>
              <p className="text-lg font-semibold">{overview.marketplace.overview.total_claims}</p>
            </div>
          </div>
          {(overview.marketplace.best_opportunities?.length ?? 0) > 0 && (
            <ul className="text-xs text-gray-600 space-y-1">
              {overview.marketplace.best_opportunities!.slice(0, 3).map((o) => (
                <li key={o.opportunity_id}>
                  → {o.title} (score {o.rank_score})
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {overview.deal_risk?.overview && (
        <section className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Risk dashboard</p>
            <Link href="/deal-risk" className="text-xs text-brand-700 hover:underline">
              Deal Risk →
            </Link>
          </div>
          <div className="card p-4 grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
            <div>
              <p className="text-[10px] text-gray-500">Healthy</p>
              <p className="text-lg font-semibold">{overview.deal_risk.overview.healthy_deals}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500">At risk</p>
              <p className="text-lg font-semibold">
                {overview.deal_risk.overview.at_risk_deals + overview.deal_risk.overview.critical_deals}
              </p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500">Critical</p>
              <p className="text-lg font-semibold">{overview.deal_risk.overview.critical_deals}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500">Avg health</p>
              <p className="text-lg font-semibold">{overview.deal_risk.overview.average_health_score}</p>
            </div>
          </div>
        </section>
      )}

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900">3. Top Risks</p>
        <div className="card p-4 space-y-2">
          {overview.top_risks.length === 0 ? (
            <EmptyState title="No risks flagged" description="No critical department risks detected." />
          ) : (
            overview.top_risks.map((r: SalesDeptV3Risk) => (
              <div
                key={r.risk_id}
                className="flex items-start justify-between gap-3 border-b border-gray-50 pb-2 last:border-0"
              >
                <div>
                  <p className="text-sm font-medium text-gray-900">{r.title}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{r.issue}</p>
                  <p className="text-[10px] text-gray-400 mt-0.5 capitalize">{r.source}</p>
                </div>
                <span
                  className={cn(
                    "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize shrink-0",
                    SEVERITY_STYLES[r.severity] ?? SEVERITY_STYLES.medium,
                  )}
                >
                  {r.severity}
                </span>
              </div>
            ))
          )}
        </div>
      </section>

      <div className="grid lg:grid-cols-2 gap-4">
        <section className="space-y-3">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <Target size={16} className="text-red-600" />
            4. Priority Leads
          </p>
          <div className="card p-4 space-y-2">
            {overview.priority_leads.length === 0 ? (
              <EmptyState title="No priority leads" description="Run lead intelligence scan." />
            ) : (
              overview.priority_leads.map((l: SalesDeptV3PriorityLead) => (
                <div key={l.lead_id} className="border-b border-gray-50 pb-2 last:border-0">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <Link href={`/crm/leads/${l.lead_id}`} className="text-sm font-medium text-brand-800 hover:underline">
                        {l.name}
                      </Link>
                      {l.company && <p className="text-[10px] text-gray-500">{l.company}</p>}
                    </div>
                    <span
                      className={cn(
                        "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
                        PRIORITY_STYLES[l.urgency] ?? PRIORITY_STYLES.medium,
                      )}
                    >
                      {l.urgency}
                    </span>
                  </div>
                  <p className="text-[10px] text-gray-500 mt-1">
                    Score {l.priority_score} · Revenue potential {l.revenue_potential} · {l.recommended_action}
                  </p>
                </div>
              ))
            )}
          </div>
        </section>

        <section className="space-y-3">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <MessagesSquare size={16} className="text-sky-600" />
            5. Priority Conversations
          </p>
          <div className="card p-4 space-y-2">
            {overview.priority_conversations.length === 0 ? (
              <EmptyState title="No priority conversations" description="Inbox channels look quiet." />
            ) : (
              overview.priority_conversations.map((c: SalesDeptV3PriorityConversation) => (
                <div key={c.conversation_id} className="border-b border-gray-50 pb-2 last:border-0">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <Link
                        href="/unified-inbox"
                        className="text-sm font-medium text-brand-800 hover:underline"
                      >
                        {c.contact_name || c.conversation_id.slice(0, 12)}
                      </Link>
                      <p className="text-[10px] text-gray-500 capitalize">{c.channel} · {c.classification || "—"}</p>
                    </div>
                    <span
                      className={cn(
                        "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
                        PRIORITY_STYLES[c.response_urgency] ?? PRIORITY_STYLES.medium,
                      )}
                    >
                      {c.response_urgency}
                    </span>
                  </div>
                  <p className="text-[10px] text-gray-500 mt-1">
                    Health {c.communication_health} · Follow-up {c.follow_up_priority} · {c.recommended_action}
                  </p>
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <ListTodo size={16} className="text-violet-600" />
          6. Recommended Actions
        </p>
        <div className="card p-4 space-y-2">
          {overview.recommended_actions.length === 0 ? (
            <EmptyState title="No actions" description="Operator task queue is clear." />
          ) : (
            overview.recommended_actions.map((a: SalesDeptV3RecommendedAction) => (
              <div key={a.action_id} className="flex items-start justify-between gap-3 border-b border-gray-50 pb-2">
                <div>
                  <Link href="/operator-tasks" className="text-sm font-medium text-gray-900 hover:underline">
                    {a.title}
                  </Link>
                  <p className="text-xs text-gray-500 mt-0.5">{a.description}</p>
                  <p className="text-[10px] text-gray-400 capitalize">{a.source} · {a.category}</p>
                </div>
                <div className="text-right shrink-0">
                  <span
                    className={cn(
                      "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
                      PRIORITY_STYLES[a.priority] ?? PRIORITY_STYLES.medium,
                    )}
                  >
                    {a.priority}
                  </span>
                  {a.is_overdue && (
                    <p className="text-[10px] text-red-600 mt-1">Overdue</p>
                  )}
                </div>
              </div>
            ))
          )}
          <p className="text-[10px] text-gray-400 pt-1">No automatic task execution — manual approval required.</p>
        </div>
      </section>

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <TrendingUp size={16} className="text-emerald-600" />
          7. Revenue Forecast
        </p>
        <div className="card p-4">
          <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3">
            <KpiCard label="Pipeline" value={`${fmtMoney(forecast.pipeline_value)} ${forecast.currency}`} />
            <KpiCard label="Weighted pipeline" value={`${fmtMoney(forecast.weighted_pipeline)} ${forecast.currency}`} />
            <KpiCard label="Closed revenue" value={`${fmtMoney(forecast.closed_revenue)} ${forecast.currency}`} />
            <KpiCard label="30-day forecast" value={`${fmtMoney(forecast.forecast_30d)} ${forecast.currency}`} />
            <KpiCard label="90-day forecast" value={`${fmtMoney(forecast.forecast_90d)} ${forecast.currency}`} />
          </div>
          <p className="text-[10px] text-gray-400 mt-3">
            Confidence: {forecast.confidence} — read-only analytics from CRM, deal room, and revenue attribution.
          </p>
        </div>
      </section>

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Lightbulb size={16} className="text-amber-600" />
          8. Weekly Briefing
        </p>
        <div className="card p-4 space-y-3">
          {overview.weekly_priorities.length > 0 && !briefing && (
            <ul className="space-y-1">
              {overview.weekly_priorities.map((item, i) => (
                <li key={i} className="text-sm text-gray-700">
                  • {item}
                </li>
              ))}
            </ul>
          )}
          {briefing && (
            <>
              <p className="text-sm text-gray-800">{briefing.executive_summary}</p>
              {briefing.weekly_priorities.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-gray-900 mb-1">Weekly priorities</p>
                  <ul className="space-y-1">
                    {briefing.weekly_priorities.map((item, i) => (
                      <li key={i} className="text-sm text-gray-700">
                        • {item}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {briefing.revenue_forecast_note && (
                <p className="text-xs text-gray-600">{briefing.revenue_forecast_note}</p>
              )}
              <p className="text-[10px] text-gray-400">Source: {briefing.source}</p>
            </>
          )}
          {!briefing && overview.weekly_priorities.length === 0 && (
            <EmptyState
              title="No briefing yet"
              description="Click Generate weekly briefing for a department summary."
            />
          )}
        </div>
      </section>

      {forecastWidget && (
        <section className="card p-4 space-y-3 border-emerald-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <CircleDollarSign size={16} className="text-emerald-600" />
              Forecast Overview
            </p>
            <Link href="/revenue-forecast" className="text-xs text-brand-700 hover:underline">
              Revenue Forecast →
            </Link>
          </div>
          <div className="grid sm:grid-cols-3 gap-3">
            <KpiCard label="Expected 30d" value={fmtMoney(forecastWidget.expected_30d)} />
            <KpiCard label="Best case" value={fmtMoney(forecastWidget.best_case_30d)} />
            <KpiCard label="Pipeline forecast" value={fmtMoney(forecastWidget.pipeline_forecast)} />
          </div>
          {(forecastWidget.top_risks?.length ?? 0) > 0 && (
            <ul className="text-xs text-gray-600 space-y-1">
              {forecastWidget.top_risks.slice(0, 2).map((r, i) => (
                <li key={i}>⚠ {r.title}</li>
              ))}
            </ul>
          )}
          <p className="text-[10px] text-gray-400">
            Heuristic forecast ({forecastWidget.confidence}) — read-only, no deal or CRM writes.
          </p>
        </section>
      )}

      {(agentRecs?.top_recommendations?.length ?? 0) > 0 && (
        <section className="card p-4 space-y-3 border-indigo-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Bot size={16} className="text-indigo-600" />
              Agent Recommendations
            </p>
            <Link href="/multi-agent" className="text-xs text-brand-700 hover:underline">
              Multi-Agent Team →
            </Link>
          </div>
          <ul className="space-y-2 text-xs">
            {agentRecs!.top_recommendations.map((rec: MultiAgentRecommendation, i) => (
              <li key={i} className="flex items-start justify-between gap-2 border-b border-gray-50 pb-2">
                <div>
                  <p className="font-medium text-gray-900">{rec.title}</p>
                  <p className="text-[10px] text-gray-500 mt-0.5">{rec.source_agent}</p>
                </div>
                <span
                  className={cn(
                    "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize shrink-0",
                    PRIORITY_STYLES[rec.priority] ?? PRIORITY_STYLES.medium,
                  )}
                >
                  {rec.priority}
                </span>
              </li>
            ))}
          </ul>
          <p className="text-[10px] text-gray-400">
            Coordinated multi-agent output — no automatic messaging, CRM, deal, or task execution.
          </p>
        </section>
      )}

      <div className="card p-4">
        <p className="text-xs font-semibold text-gray-900 mb-2">Quick links</p>
        <div className="flex flex-wrap gap-2">
          {[
            { href: "/crm", label: "CRM", icon: Users },
            { href: "/unified-inbox", label: "Unified Inbox", icon: Inbox },
            { href: "/wechat", label: "WeChat", icon: MessagesSquare },
            { href: "/whatsapp", label: "WhatsApp", icon: MessagesSquare },
            { href: "/deal-room", label: "Deal Room", icon: Target },
            { href: "/operator-tasks", label: "Operator Tasks", icon: ListTodo },
            { href: "/sales-manager", label: "Sales Manager", icon: TrendingUp },
            { href: "/executive-copilot", label: "Executive Copilot", icon: Sparkles },
            { href: "/multi-agent", label: "Multi-Agent Team", icon: Bot },
            { href: "/revenue-attribution", label: "Revenue Attribution", icon: CircleDollarSign },
          ].map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className="inline-flex items-center gap-1.5 text-xs text-gray-700 hover:text-brand-800 px-2 py-1.5 rounded-lg border border-gray-100 hover:bg-gray-50"
            >
              <Icon size={12} />
              {label}
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
