"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Globe, ArrowRight, TrendingUp, Search } from "lucide-react";
import { exportApi, BuyerRecommendationType } from "@/lib/api";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { ScoreBadge, actionLink } from "@/components/buyer-finder/BuyerFinderPanel";

const TYPE_LABELS: Record<BuyerRecommendationType, string> = {
  partner: "Partner",
  crm_lead: "CRM Lead",
  contact: "Contact",
  industry_segment: "Segment",
};

export default function ExportDashboardPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["export-dashboard"],
    queryFn: () => exportApi.dashboard(10).then((r) => r.data),
  });

  if (isLoading) return <LoadingState message="Loading export dashboard…" />;
  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load export dashboard"}
        onRetry={() => refetch()}
      />
    );
  }

  const dashboard = data!;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Globe size={22} className="text-sky-600" />
            Export Agent
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Advisory export opportunities — no automatic outreach
          </p>
        </div>
        <Link href="/export/opportunities" className="btn-secondary text-sm flex items-center gap-1">
          All opportunities
          <ArrowRight size={14} />
        </Link>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Opportunities", value: dashboard.total_opportunities },
          { label: "Avg score", value: dashboard.avg_score || "—" },
          { label: "Products analyzed", value: dashboard.products_analyzed },
          { label: "Markets tracked", value: dashboard.country_rankings.length },
        ].map(({ label, value }) => (
          <div key={label} className="card p-3 text-center">
            <p className="text-lg font-semibold text-gray-900 tabular-nums">{value}</p>
            <p className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</p>
          </div>
        ))}
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card p-4">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5 mb-3">
            <TrendingUp size={14} className="text-sky-600" />
            Top export opportunities
          </p>
          {dashboard.top_opportunities.length === 0 ? (
            <EmptyState
              title="No opportunities yet"
              description="Analyze a product from the Products page to generate export recommendations."
            />
          ) : (
            <ul className="space-y-2">
              {dashboard.top_opportunities.map((o) => (
                <li key={o.id}>
                  <Link
                    href={`/export/opportunities/${o.id}`}
                    className="flex items-center justify-between gap-2 rounded-lg border border-gray-100 p-2.5 hover:bg-sky-50/50 transition-colors"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-900 truncate">
                        {o.product_name ?? "Product"} · {o.country}
                      </p>
                      <p className="text-[11px] text-gray-500 truncate">
                        {o.company_name ?? "—"}
                        {o.demand_level ? ` · ${o.demand_level} demand` : ""}
                      </p>
                    </div>
                    <ScoreBadge score={o.score} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card p-4">
          <p className="text-sm font-semibold text-gray-900 mb-3">Country ranking</p>
          {dashboard.country_rankings.length === 0 ? (
            <p className="text-xs text-gray-400">Run product analysis to rank export markets.</p>
          ) : (
            <ul className="space-y-2">
              {dashboard.country_rankings.map((c, i) => (
                <li
                  key={c.country}
                  className="flex items-center justify-between text-sm border-b border-gray-50 pb-2"
                >
                  <span className="text-gray-800">
                    <span className="text-gray-400 mr-2">{i + 1}.</span>
                    {c.country}
                  </span>
                  <span className="text-xs text-gray-500 tabular-nums">
                    max {Math.round(c.max_score)} · {c.opportunity_count} opp.
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="card p-4">
        <div className="flex items-center justify-between gap-2 mb-3">
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <Search size={14} className="text-indigo-600" />
            Top buyer opportunities
          </p>
          <Link href="/buyer-finder" className="text-xs text-brand-700 hover:text-brand-900">
            Buyer Finder →
          </Link>
        </div>
        {(dashboard.top_buyer_opportunities ?? []).length === 0 ? (
          <p className="text-xs text-gray-400">
            Run buyer analysis on a product to surface recommended buyers.
          </p>
        ) : (
          <ul className="space-y-2">
            {(dashboard.top_buyer_opportunities ?? []).map((b) => {
              const action = actionLink(b);
              return (
                <li
                  key={b.id}
                  className="flex items-start justify-between gap-2 rounded-lg border border-gray-100 p-2.5"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {b.name}
                      {b.product_name ? ` · ${b.product_name}` : ""}
                    </p>
                    <p className="text-[11px] text-gray-500 truncate">
                      {TYPE_LABELS[b.recommendation_type]}
                      {b.country ? ` · ${b.country}` : ""}
                    </p>
                    <p className="text-[11px] text-gray-600 mt-0.5 line-clamp-2">{b.reason}</p>
                    {action && (
                      <Link href={action.href} className="text-[11px] text-brand-700 hover:text-brand-900 mt-1 inline-block">
                        {action.label}
                      </Link>
                    )}
                  </div>
                  <ScoreBadge score={b.score} />
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
