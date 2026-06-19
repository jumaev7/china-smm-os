"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bot,
  Crown,
  Inbox,
  Lightbulb,
  ListTodo,
  Loader2,
  MessagesSquare,
  Sparkles,
  Target,
  Users,
  Layers,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  multiAgentTeamApi,
  revenueForecastApi,
  buyerIntelligenceApi,
  buyerAcquisitionApi,
  buyerDiscoveryApi,
  buyerNetworkApi,
  marketplaceApi,
  dealRiskApi,
  MultiAgentAgentOutput,
  MultiAgentBriefing,
  MultiAgentConflict,
  MultiAgentRecommendation,
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

const AGENT_ICONS: Record<string, typeof Crown> = {
  "Sales Director Agent": Crown,
  "Sales Manager Agent": Target,
  "Lead Analyst Agent": Users,
  "Communication Agent": MessagesSquare,
  "Operations Agent": ListTodo,
};

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

function AgentSection({ agent }: { agent: MultiAgentAgentOutput }) {
  const Icon = AGENT_ICONS[agent.agent_name] ?? Bot;
  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
          <Icon size={16} className="text-brand-600" />
          {agent.agent_name}
        </p>
        <span
          className={cn(
            "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize shrink-0",
            PRIORITY_STYLES[agent.priority] ?? PRIORITY_STYLES.medium,
          )}
        >
          {agent.priority}
        </span>
      </div>
      <p className="text-sm text-gray-700">{agent.summary}</p>
      {agent.recommendations.length === 0 ? (
        <p className="text-xs text-gray-400">No recommendations from this agent.</p>
      ) : (
        <ul className="text-xs text-gray-600 space-y-1.5">
          {agent.recommendations.map((rec, i) => (
            <li key={i} className="flex gap-1.5">
              <Lightbulb size={12} className="text-amber-500 shrink-0 mt-0.5" />
              <span>{rec}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function MultiAgentPage() {
  const [briefing, setBriefing] = useState<MultiAgentBriefing | null>(null);

  const { data: overview, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["multi-agent-overview"],
    queryFn: () => multiAgentTeamApi.overview().then((r) => r.data),
  });

  const { data: revenueForecastWidget } = useQuery({
    queryKey: ["revenue-forecast-multi-agent"],
    queryFn: () => revenueForecastApi.summaryWidget().then((r) => r.data),
    enabled: !!overview,
    retry: 1,
  });

  const { data: buyerIntelWidget } = useQuery({
    queryKey: ["buyer-intelligence-multi-agent"],
    queryFn: () => buyerIntelligenceApi.summaryWidget().then((r) => r.data),
    enabled: !!overview,
    retry: 1,
  });

  const { data: buyerAcquisitionWidget } = useQuery({
    queryKey: ["buyer-acquisition-multi-agent"],
    queryFn: () => buyerAcquisitionApi.summaryWidget().then((r) => r.data),
    enabled: !!overview,
    retry: 1,
  });

  const { data: buyerDiscoveryWidget } = useQuery({
    queryKey: ["buyer-discovery-multi-agent"],
    queryFn: () => buyerDiscoveryApi.summaryWidget().then((r) => r.data),
    enabled: !!overview,
    retry: 1,
  });

  const { data: marketplaceWidget } = useQuery({
    queryKey: ["marketplace-multi-agent"],
    queryFn: () => marketplaceApi.overview().then((r) => r.data),
    enabled: !!overview,
    retry: 1,
  });

  const { data: buyerNetworkWidget } = useQuery({
    queryKey: ["buyer-network-multi-agent"],
    queryFn: () => buyerNetworkApi.summaryWidget().then((r) => r.data),
    enabled: !!overview,
    retry: 1,
  });

  const { data: dealRiskWidget } = useQuery({
    queryKey: ["deal-risk-multi-agent"],
    queryFn: () => dealRiskApi.summaryWidget().then((r) => r.data),
    enabled: !!overview,
    retry: 1,
  });

  const briefingMutation = useMutation({
    mutationFn: () => multiAgentTeamApi.generateBriefing().then((r) => r.data),
    onSuccess: (data) => {
      setBriefing(data);
      toast.success("Multi-agent briefing generated");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (isLoading) return <LoadingState message="Loading Multi-Agent Sales Team…" />;
  if (isError || !overview) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load multi-agent team"}
        onRetry={() => refetch()}
      />
    );
  }

  const coord = overview.coordinator;
  const agentsByName = Object.fromEntries(overview.agents.map((a) => [a.agent_name, a]));

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Bot size={22} className="text-brand-600" />
            Multi-Agent Sales Team
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Five coordinated advisory agents on Sales Department v3 — recommendations only, no automatic actions.
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
          Generate briefing
        </button>
      </div>

      <PartialErrorsBanner errors={overview.errors} />
      <p className="text-[10px] text-gray-400">{overview.safety_notice}</p>

      {buyerIntelWidget && (
        <section className="card p-4 space-y-3 border-violet-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Buyer recommendations</p>
            <Link href="/buyer-intelligence" className="text-xs text-brand-700 hover:underline">
              Buyer Intelligence →
            </Link>
          </div>
          <p className="text-sm text-gray-700">
            {buyerIntelWidget.hot_buyers} hot · {buyerIntelWidget.at_risk_buyers} at risk · top:{" "}
            {buyerIntelWidget.top_buyer_name ?? "—"} (score {buyerIntelWidget.top_buyer_score})
          </p>
          <p className="text-[10px] text-gray-400">
            Fed into Sales Director agent — intelligence only, no CRM or messaging automation.
          </p>
        </section>
      )}

      {buyerAcquisitionWidget && (
        <section className="card p-4 space-y-3 border-brand-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Buyer Acquisition Recommendations</p>
            <Link href="/buyer-acquisition" className="text-xs text-brand-700 hover:underline">
              Buyer Acquisition →
            </Link>
          </div>
          <p className="text-sm text-gray-700">
            {buyerAcquisitionWidget.total_buyers} unified buyers ·{" "}
            {buyerAcquisitionWidget.high_potential_buyers} high potential ·{" "}
            {buyerAcquisitionWidget.marketplace_opportunities} marketplace · top:{" "}
            {buyerAcquisitionWidget.top_buyer_name ?? "—"} (score {buyerAcquisitionWidget.top_buyer_score})
          </p>
          <p className="text-[10px] text-gray-400">
            Fed into Sales Director agent — unified read-only aggregation, no outreach automation.
          </p>
        </section>
      )}

      {buyerDiscoveryWidget && (
        <section className="card p-4 space-y-3 border-sky-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Buyer discovery recommendations</p>
            <Link href="/buyer-discovery" className="text-xs text-brand-700 hover:underline">
              Buyer Discovery →
            </Link>
          </div>
          <p className="text-sm text-gray-700">
            {buyerDiscoveryWidget.total_buyers} discovered · {buyerDiscoveryWidget.high_potential} high
            potential · top: {buyerDiscoveryWidget.top_buyer_name ?? "—"} (score{" "}
            {buyerDiscoveryWidget.top_buyer_score})
          </p>
          <p className="text-[10px] text-gray-400">
            Fed into Sales Director agent — export buyer intelligence only, no outreach automation.
          </p>
        </section>
      )}

      {buyerNetworkWidget && (
        <section className="card p-4 space-y-3 border-violet-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Network recommendations</p>
            <Link href="/buyer-network" className="text-xs text-brand-700 hover:underline">
              Buyer Network →
            </Link>
          </div>
          <p className="text-sm text-gray-700">
            {buyerNetworkWidget.total_profiles} profiles · {buyerNetworkWidget.strategic_buyers}{" "}
            strategic · top: {buyerNetworkWidget.top_buyer_name ?? "—"} (strength{" "}
            {buyerNetworkWidget.top_buyer_score})
          </p>
          <p className="text-[10px] text-gray-400">
            Fed into Sales Director agent — relationship mapping only, no automatic outreach.
          </p>
        </section>
      )}

      {marketplaceWidget && (
        <section className="card p-4 space-y-3 border-teal-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Opportunity recommendations</p>
            <Link href="/marketplace" className="text-xs text-brand-700 hover:underline">
              Marketplace →
            </Link>
          </div>
          <p className="text-sm text-gray-700">
            {marketplaceWidget.open_opportunities} open · {marketplaceWidget.total_interests} interests ·{" "}
            {marketplaceWidget.total_claims} manual claims
          </p>
          <p className="text-[10px] text-gray-400">
            Fed into Sales Director agent — exchange only, no automatic messaging or deal creation.
          </p>
        </section>
      )}

      {dealRiskWidget && (
        <section className="card p-4 space-y-3 border-orange-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Deal intervention recommendations</p>
            <Link href="/deal-risk" className="text-xs text-brand-700 hover:underline">
              Deal Risk →
            </Link>
          </div>
          <p className="text-sm text-gray-700">
            {dealRiskWidget.at_risk_deals} at risk · {dealRiskWidget.critical_deals} critical · avg health{" "}
            {dealRiskWidget.average_health_score}/100
          </p>
          {dealRiskWidget.top_risk_deal_title && (
            <p className="text-xs text-gray-500">Top risk: {dealRiskWidget.top_risk_deal_title}</p>
          )}
          <p className="text-[10px] text-gray-400">
            Fed into Sales Manager agent — recommendations only, no automatic actions.
          </p>
        </section>
      )}

      {revenueForecastWidget && (
        <section className="card p-4 space-y-3 border-emerald-100">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold text-gray-900">Revenue Forecast recommendations</p>
            <Link href="/revenue-forecast" className="text-xs text-brand-700 hover:underline">
              Revenue Forecast →
            </Link>
          </div>
          <p className="text-sm text-gray-700">
            30-day expected:{" "}
            <span className="font-semibold tabular-nums">
              {new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(
                Number(revenueForecastWidget.expected_30d) || 0,
              )}{" "}
              UZS
            </span>{" "}
            ({revenueForecastWidget.confidence} confidence)
          </p>
          <ul className="text-xs text-gray-600 space-y-1">
            {(revenueForecastWidget.top_growth ?? []).slice(0, 2).map((g, i) => (
              <li key={i}>↑ {g.title}</li>
            ))}
            {(revenueForecastWidget.top_risks ?? []).slice(0, 2).map((r, i) => (
              <li key={`r-${i}`}>↓ {r.title}</li>
            ))}
          </ul>
          <p className="text-[10px] text-gray-400">
            Fed into Sales Director agent — forecasting only, no automatic actions.
          </p>
        </section>
      )}

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900">1. Team Overview</p>
        <div className="card p-4 space-y-3">
          <p className="text-sm text-gray-700">{overview.team_summary}</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <KpiCard label="Active agents" value={overview.active_agent_count} />
            <KpiCard label="Dept. health" value={coord.department_health} />
            <KpiCard label="Health status" value={coord.department_health_label} />
            <KpiCard label="Conflicts" value={coord.conflicts.length} />
          </div>
          <p className="text-[10px] text-gray-400">
            Built on{" "}
            <Link href="/sales-department-v3" className="text-brand-700 hover:underline">
              AI Sales Department v3
            </Link>{" "}
            — unified inbox, WeChat, WhatsApp, CRM, deal room, operator tasks.
          </p>
        </div>
      </section>

      {agentsByName["Sales Director Agent"] && (
        <section className="space-y-3">
          <p className="text-sm font-semibold text-gray-900">2. Sales Director</p>
          <AgentSection agent={agentsByName["Sales Director Agent"]} />
        </section>
      )}

      {agentsByName["Sales Manager Agent"] && (
        <section className="space-y-3">
          <p className="text-sm font-semibold text-gray-900">3. Sales Manager</p>
          <AgentSection agent={agentsByName["Sales Manager Agent"]} />
        </section>
      )}

      {agentsByName["Lead Analyst Agent"] && (
        <section className="space-y-3">
          <p className="text-sm font-semibold text-gray-900">4. Lead Analyst</p>
          <AgentSection agent={agentsByName["Lead Analyst Agent"]} />
        </section>
      )}

      {agentsByName["Communication Agent"] && (
        <section className="space-y-3">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <Inbox size={16} className="text-sky-600" />
            5. Communication Agent
          </p>
          <AgentSection agent={agentsByName["Communication Agent"]} />
          <p className="text-[10px] text-gray-400">
            Monitors{" "}
            <Link href="/unified-inbox" className="text-brand-700 hover:underline">
              Unified Inbox
            </Link>
            ,{" "}
            <Link href="/wechat" className="text-brand-700 hover:underline">
              WeChat
            </Link>
            ,{" "}
            <Link href="/whatsapp" className="text-brand-700 hover:underline">
              WhatsApp
            </Link>{" "}
            — no automatic messaging.
          </p>
        </section>
      )}

      {agentsByName["Operations Agent"] && (
        <section className="space-y-3">
          <p className="text-sm font-semibold text-gray-900">6. Operations Agent</p>
          <AgentSection agent={agentsByName["Operations Agent"]} />
          <p className="text-[10px] text-gray-400">
            <Link href="/operator-tasks" className="text-brand-700 hover:underline">
              Operator Tasks
            </Link>{" "}
            and workflow monitoring — no automatic task execution.
          </p>
        </section>
      )}

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900">7. Combined Recommendations</p>
        <div className="card p-4 space-y-2">
          {coord.top_recommendations.length === 0 ? (
            <EmptyState title="No recommendations" description="All agents report stable operations." />
          ) : (
            coord.top_recommendations.map((rec: MultiAgentRecommendation, i) => (
              <div
                key={i}
                className="flex items-start justify-between gap-3 border-b border-gray-50 pb-2 last:border-0"
              >
                <div>
                  <p className="text-sm font-medium text-gray-900">{rec.title}</p>
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
              </div>
            ))
          )}
        </div>
        {coord.conflicts.length > 0 && (
          <div className="card p-4 space-y-2 border-amber-100">
            <p className="text-xs font-semibold text-amber-800 flex items-center gap-1">
              <AlertTriangle size={14} />
              Cross-agent conflicts
            </p>
            {coord.conflicts.map((c: MultiAgentConflict, i) => (
              <div key={i} className="text-xs text-gray-600">
                <p className="font-medium text-gray-800">{c.topic}</p>
                <p className="text-[10px] text-gray-500">{c.agents.join(" · ")}</p>
                <p className="mt-0.5">{c.description}</p>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <p className="text-sm font-semibold text-gray-900">8. Department Health</p>
        <div className="card p-4">
          <p className={cn("text-4xl font-semibold tabular-nums", healthColor(coord.department_health))}>
            {coord.department_health}
            <span className="text-sm font-normal text-gray-500 ml-2 capitalize">
              {coord.department_health_label}
            </span>
          </p>
          <p className="text-sm text-gray-600 mt-2">{coord.combined_summary}</p>
        </div>
      </section>

      {briefing && (
        <section className="card p-4 space-y-3 border-brand-100">
          <p className="text-sm font-semibold text-gray-900">{briefing.briefing_title}</p>
          <p className="text-sm text-gray-700">{briefing.combined_summary}</p>
          <ul className="text-xs text-gray-600 space-y-1">
            {briefing.top_recommendations.map((item, i) => (
              <li key={i}>→ {item}</li>
            ))}
          </ul>
          {briefing.conflicts.length > 0 && (
            <div className="text-xs text-amber-800">
              <p className="font-medium">Conflicts</p>
              {briefing.conflicts.map((c, i) => (
                <p key={i}>• {c}</p>
              ))}
            </div>
          )}
          <p className="text-[10px] text-gray-400">{briefing.safety_notice}</p>
        </section>
      )}
    </div>
  );
}
