"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Briefcase,
  CircleDollarSign,
  Lightbulb,
  MessageSquare,
  Target,
  TrendingUp,
  Users,
} from "lucide-react";
import { commercialDemoApi } from "@/lib/commercial-demo-api";
import { DemoModeBanner } from "@/components/demo/DemoModeToggle";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import { KpiCard, PageHeader, PageShell } from "@/components/ui/design-system";
import { cn } from "@/lib/utils";

function fmtMoney(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

const PRIORITY_STYLES = {
  high: "border-red-200 bg-red-50 text-red-800",
  medium: "border-amber-200 bg-amber-50 text-amber-800",
  low: "border-gray-200 bg-gray-50 text-gray-600",
};

export default function ValueDemoPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["commercial-demo", "value-demo"],
    queryFn: () => commercialDemoApi.getValueDemo().then((r) => r.data),
  });

  if (isLoading) {
    return (
      <PageShell>
        <LoadingState message="Loading value demonstration…" />
      </PageShell>
    );
  }

  if (isError || !data) {
    return (
      <PageShell>
        <ErrorState error={error} onRetry={() => refetch()} />
      </PageShell>
    );
  }

  return (
    <PageShell>
      <PageHeader
        title="Value Demonstration"
        subtitle={
          data.company_name
            ? `Executive outcomes for ${data.company_name} — what the platform delivers today.`
            : "Executive outcomes — what the platform delivers today."
        }
        actions={
          <Link href="/demo-tour" className="btn-secondary text-xs">
            Demo Tour
          </Link>
        }
      />

      <DemoModeBanner />

      {!data.demo_data_loaded && (
        <div className="mt-4 rounded-xl border border-brand-200 bg-brand-50 px-4 py-3 text-sm text-brand-900">
          No demo data loaded yet.{" "}
          <Link href="/demo-tour" className="font-semibold underline">
            Load a demo factory package
          </Link>{" "}
          to see full value metrics.
        </div>
      )}

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          label="Buyers Found"
          value={String(data.buyers_found)}
          icon={Users}
          trend={data.buyers_found > 0 ? { value: "Growing", positive: true } : undefined}
        />
        <KpiCard
          label="Opportunities Generated"
          value={String(data.opportunities_generated)}
          icon={Target}
          trend={data.opportunities_generated > 0 ? { value: "Active pipeline", positive: true } : undefined}
        />
        <KpiCard
          label="Pipeline Value"
          value={fmtMoney(data.pipeline_value_usd)}
          icon={Briefcase}
          trend={data.pipeline_value_usd > 0 ? { value: "Export deals", positive: true } : undefined}
        />
        <KpiCard
          label="Revenue Influenced"
          value={fmtMoney(data.estimated_revenue_influenced_usd)}
          icon={CircleDollarSign}
          trend={data.estimated_revenue_influenced_usd > 0 ? { value: "Estimated impact", positive: true } : undefined}
        />
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label="Active Deals" value={String(data.active_deals)} icon={TrendingUp} />
        <KpiCard label="Proposals Sent" value={String(data.proposals_sent)} icon={Briefcase} />
        <KpiCard
          label="Active Conversations"
          value={String(data.communications_active)}
          icon={MessageSquare}
        />
        <KpiCard
          label="AI Recommendations"
          value={String(data.ai_recommendations)}
          icon={Lightbulb}
        />
      </div>

      <section className="mt-8">
        <h2 className="text-base font-semibold text-navy-900 mb-1">Actions for Today</h2>
        <p className="text-sm text-gray-500 mb-4">
          Priority actions to maximize export growth this week.
        </p>
        <div className="grid gap-3 md:grid-cols-2">
          {data.actions_today.map((action) => (
            <Link
              key={action.id}
              href={action.route}
              className={cn(
                "rounded-xl border p-4 hover:shadow-sm transition-shadow flex items-start gap-3",
                PRIORITY_STYLES[action.priority],
              )}
            >
              <ArrowRight size={16} className="shrink-0 mt-0.5" />
              <div>
                <div className="flex items-center gap-2">
                  <p className="font-semibold text-sm">{action.title}</p>
                  <span className="text-[10px] uppercase font-bold opacity-70">
                    {action.priority}
                  </span>
                </div>
                <p className="text-xs mt-1 opacity-80">{action.description}</p>
              </div>
            </Link>
          ))}
        </div>
      </section>

      <div className="mt-8 flex flex-wrap gap-3">
        <Link href="/executive-demo" className="btn-primary text-sm">
          Executive Presentation
        </Link>
        <Link href="/growth-center" className="btn-secondary text-sm">
          Growth Center
        </Link>
        <Link href="/customer-success/roi" className="btn-secondary text-sm">
          ROI Center
        </Link>
      </div>
    </PageShell>
  );
}
