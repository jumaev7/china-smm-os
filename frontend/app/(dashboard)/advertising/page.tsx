"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  BadgeDollarSign,
  Building2,
  Calculator,
  Compass,
  FlaskConical,
  Layers,
  Link2,
  Megaphone,
  Radio,
} from "lucide-react";

import { AdvertisingSubNav } from "@/components/advertising/AdvertisingSubNav";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  KpiCard,
  PageHeader,
  PageSection,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import { ADVERTISING_QUERY_KEY, advertisingApi, getApiErrorMessage } from "@/lib/api";
import {
  formatMoneyMinor,
  formatNumber,
  formatRatioPct,
  freshnessVariant,
  pacingLabel,
  pacingVariant,
  titleCaseKey,
} from "@/lib/advertising-ui";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

export default function AdvertisingOverviewPage() {
  const overviewQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "overview"],
    queryFn: () => advertisingApi.overview().then((r) => r.data),
    ...QUERY_OPTS,
  });

  const data = overviewQuery.data;

  return (
    <PageShell wide>
      <PageHeader
        title="Advertising Intelligence"
        subtitle="Read-only mirror of provider ad reporting. This platform never edits, pauses, or deletes provider campaigns, budgets, or creatives."
        icon={Megaphone}
        badge={<StatusBadge variant="neutral">Read-only</StatusBadge>}
        actions={
          <div className="flex flex-wrap gap-2">
            <Link href="/advertising/decision-support" className="btn-secondary text-sm">
              Decision Support
            </Link>
            <Link href="/advertising/simulator" className="btn-secondary text-sm">
              Simulator
            </Link>
            <Link href="/advertising/experiments" className="btn-secondary text-sm">
              Experiments
            </Link>
          </div>
        }
      />
      <AdvertisingSubNav />

      {overviewQuery.isLoading ? <LoadingState message="Loading advertising overview…" /> : null}

      {overviewQuery.isError && !overviewQuery.isLoading ? (
        <ErrorState
          title="Unable to load advertising overview"
          message={getApiErrorMessage(overviewQuery.error)}
          onRetry={() => overviewQuery.refetch()}
        />
      ) : null}

      {!overviewQuery.isLoading && !overviewQuery.isError && data ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              label="Advertising accounts"
              value={data.account_count}
              href="/advertising/accounts"
              sub={`${data.connected_account_count} connected · ${data.mock_account_count} mock`}
              icon={Building2}
            />
            <KpiCard
              label="Active campaigns"
              value={data.active_campaign_count}
              href="/advertising/campaigns?status=active"
              sub={`${data.campaign_count} total`}
              icon={Megaphone}
              iconClassName="bg-emerald-100 text-emerald-600 dark-tenant:bg-emerald-500/15 dark-tenant:text-emerald-400"
            />
            <KpiCard
              label="Open anomalies"
              value={data.open_anomaly_count}
              href="/advertising/anomalies"
              icon={AlertTriangle}
              iconClassName="bg-amber-100 text-amber-600 dark-tenant:bg-amber-500/15 dark-tenant:text-amber-400"
            />
            <KpiCard
              label="Creative fatigue warnings"
              value={data.fatigue_warning_count}
              href="/advertising/creatives?fatigue_status=fatigued"
              icon={Layers}
              iconClassName="bg-rose-100 text-rose-600 dark-tenant:bg-rose-500/15 dark-tenant:text-rose-400"
            />
          </div>

          <PageSection
            title="Spend by currency"
            description="Amounts are reported per currency and are never converted or summed across currencies."
          >
            {data.spend_by_currency.length === 0 ? (
              <EmptyState
                title="No spend recorded yet"
                description="Import an account and refresh metrics to populate provider-reported spend."
              />
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {data.spend_by_currency.map((row) => (
                  <div key={row.currency} className="card-premium p-5">
                    <div className="flex items-center justify-between">
                      <p className="kpi-label">{row.currency}</p>
                      <BadgeDollarSign size={16} className="text-slate-400" />
                    </div>
                    <p className="kpi-value mt-1.5">
                      {formatMoneyMinor(row.spend_minor, row.currency)}
                    </p>
                    <p className="text-[11px] text-gray-500 mt-1 dark-tenant:text-slate-500">
                      {row.campaign_count} campaign{row.campaign_count === 1 ? "" : "s"}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </PageSection>

          <div className="grid gap-6 xl:grid-cols-2">
            <PageSection title="Pacing warnings">
              {data.pacing_warnings.length === 0 ? (
                <p className="text-sm text-slate-500 dark-tenant:text-slate-400">
                  No campaigns flagged for pacing issues.
                </p>
              ) : (
                <div className="space-y-2">
                  {data.pacing_warnings.slice(0, 8).map((row) => (
                    <Link
                      key={row.campaign_id}
                      href={`/advertising/campaigns/${row.campaign_id}`}
                      className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm hover:border-brand-200 dark-tenant:border-slate-800"
                    >
                      <span className="min-w-0 truncate font-medium">
                        {row.campaign_name ?? row.campaign_id}
                      </span>
                      <div className="flex items-center gap-2 shrink-0">
                        <span className="tabular-nums text-slate-500">
                          {formatMoneyMinor(row.spend_minor, row.currency)}
                        </span>
                        <StatusBadge variant={pacingVariant(row.pacing_status)}>
                          {pacingLabel(row.pacing_status)}
                        </StatusBadge>
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </PageSection>

            <PageSection
              title="Attribution coverage"
              description="Provider-reported conversions are shown separately from CRM-confirmed conversions."
              action={
                <Link href="/advertising/attribution" className="btn-secondary text-xs">
                  Details
                </Link>
              }
            >
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-slate-200 px-3 py-2.5 dark-tenant:border-slate-800">
                  <p className="kpi-label">Linked campaigns</p>
                  <p className="mt-1 text-lg font-semibold tabular-nums">
                    {data.attribution_coverage.linked_campaign_count}
                    <span className="text-sm font-normal text-slate-500">
                      {" "}
                      / {data.attribution_coverage.linked_campaign_count +
                        data.attribution_coverage.unlinked_campaign_count}
                    </span>
                  </p>
                  <p className="text-[11px] text-slate-500 mt-1">
                    {formatRatioPct(data.attribution_coverage.coverage_ratio)} coverage
                  </p>
                </div>
                <div className="rounded-lg border border-slate-200 px-3 py-2.5 dark-tenant:border-slate-800">
                  <p className="kpi-label">Conversions</p>
                  <p className="mt-1 text-lg font-semibold tabular-nums">
                    {formatNumber(data.attribution_coverage.reported_conversions)}
                  </p>
                  <p className="text-[11px] text-slate-500 mt-1">
                    provider-reported ·{" "}
                    {data.attribution_coverage.crm_confirmed_conversions == null
                      ? "CRM n/a"
                      : `${formatNumber(data.attribution_coverage.crm_confirmed_conversions)} CRM-confirmed`}
                  </p>
                </div>
              </div>
            </PageSection>
          </div>

          <div className="grid gap-6 xl:grid-cols-2">
            <PageSection title="Metric freshness">
              <div className="flex flex-wrap gap-2">
                {(["fresh", "aging", "stale", "unavailable", "unsupported"] as const).map((key) => (
                  <div
                    key={key}
                    className="rounded-lg border border-slate-200 px-3 py-2 text-sm dark-tenant:border-slate-800"
                  >
                    <StatusBadge variant={freshnessVariant(key)}>{titleCaseKey(key)}</StatusBadge>
                    <span className="ml-2 tabular-nums font-medium">{data.freshness[key]}</span>
                  </div>
                ))}
              </div>
            </PageSection>

            <PageSection title="Providers">
              {data.providers.length === 0 ? (
                <p className="text-sm text-slate-500 dark-tenant:text-slate-400">
                  No providers connected yet.
                </p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {data.providers.map((provider) => (
                    <span
                      key={provider}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-sm dark-tenant:border-slate-800"
                    >
                      <Radio size={14} className="text-slate-400" />
                      {titleCaseKey(provider)}
                    </span>
                  ))}
                </div>
              )}
              <p className="mt-3 text-xs text-slate-500">
                Connect or reconnect providers via{" "}
                <Link href="/integrations" className="font-medium underline underline-offset-2">
                  Integrations
                </Link>
                .
              </p>
            </PageSection>
          </div>

          {data.notes && data.notes.length > 0 ? (
            <ul className="space-y-1 text-xs text-slate-500">
              {data.notes.map((note) => (
                <li key={note}>• {note}</li>
              ))}
            </ul>
          ) : null}

          <div className="flex flex-wrap gap-3">
            <Link
              href="/advertising/decision-support"
              className="inline-flex items-center gap-1 text-sm font-medium text-slate-900 underline-offset-2 hover:underline dark-tenant:text-slate-100"
            >
              <Compass className="h-3.5 w-3.5" /> Decision support <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            <Link
              href="/advertising/simulator"
              className="inline-flex items-center gap-1 text-sm font-medium text-slate-900 underline-offset-2 hover:underline dark-tenant:text-slate-100"
            >
              <Calculator className="h-3.5 w-3.5" /> Budget simulator <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            <Link
              href="/advertising/experiments"
              className="inline-flex items-center gap-1 text-sm font-medium text-slate-900 underline-offset-2 hover:underline dark-tenant:text-slate-100"
            >
              <FlaskConical className="h-3.5 w-3.5" /> Experiments <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            <Link
              href="/advertising/attribution"
              className="inline-flex items-center gap-1 text-sm font-medium text-slate-900 underline-offset-2 hover:underline dark-tenant:text-slate-100"
            >
              <Link2 className="h-3.5 w-3.5" /> Attribution coverage <ArrowRight className="h-3.5 w-3.5" />
            </Link>
            <Link
              href="/advertising/anomalies"
              className="inline-flex items-center gap-1 text-sm font-medium text-slate-900 underline-offset-2 hover:underline dark-tenant:text-slate-100"
            >
              <AlertTriangle className="h-3.5 w-3.5" /> Delivery anomalies <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </>
      ) : null}
    </PageShell>
  );
}
