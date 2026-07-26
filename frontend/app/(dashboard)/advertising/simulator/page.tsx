"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Calculator } from "lucide-react";

import { AdvertisingSubNav } from "@/components/advertising/AdvertisingSubNav";
import { KindBadge } from "@/components/advertising/KindBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  PageHeader,
  PageSection,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import {
  ADVERTISING_QUERY_KEY,
  type AdCampaign,
  type AdSimulation,
  advertisingApi,
  getApiErrorMessage,
} from "@/lib/api";
import {
  formatMoneyMinor,
  formatNumber,
  formatRatioPct,
  majorToMinor,
  parseShareFraction,
  titleCaseKey,
} from "@/lib/advertising-ui";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;
const SIM_DISCLAIMER =
  "Simulation does not predict future advertising performance and does not modify provider budgets.";

function equalPct(n: number): number {
  if (n <= 0) return 0;
  return Math.floor((100 / n) * 100) / 100;
}

export default function AdvertisingSimulatorPage() {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [currency, setCurrency] = useState("USD");
  const [budgetMajor, setBudgetMajor] = useState("1000");
  /** Display percentages 0–100 that should sum to 100. */
  const [pctById, setPctById] = useState<Record<string, number>>({});
  const [result, setResult] = useState<AdSimulation | null>(null);

  const campaignsQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "campaigns", "simulator"],
    queryFn: () => advertisingApi.listCampaigns({ limit: 100 }).then((r) => r.data),
    ...QUERY_OPTS,
  });

  const campaigns = useMemo(
    () => campaignsQuery.data?.items ?? [],
    [campaignsQuery.data?.items],
  );
  const selectedCampaigns = useMemo(
    () => campaigns.filter((c) => selectedIds.includes(c.id)),
    [campaigns, selectedIds],
  );

  const pctSum = useMemo(
    () => selectedIds.reduce((sum, id) => sum + (pctById[id] ?? 0), 0),
    [selectedIds, pctById],
  );

  const toggleCampaign = (campaign: AdCampaign) => {
    setResult(null);
    setSelectedIds((prev) => {
      const next = prev.includes(campaign.id)
        ? prev.filter((id) => id !== campaign.id)
        : [...prev, campaign.id];
      const base = equalPct(next.length);
      const nextPct: Record<string, number> = {};
      next.forEach((id, i) => {
        // Last item absorbs remainder so sum is exactly 100
        if (i === next.length - 1) {
          const used = base * (next.length - 1);
          nextPct[id] = Math.round((100 - used) * 100) / 100;
        } else {
          nextPct[id] = base;
        }
      });
      setPctById(nextPct);
      if (!prev.includes(campaign.id) && campaign.currency) {
        setCurrency(campaign.currency.toUpperCase());
      }
      return next;
    });
  };

  const setPct = (id: string, value: number) => {
    setResult(null);
    setPctById((prev) => ({ ...prev, [id]: value }));
  };

  const simulateMutation = useMutation({
    mutationFn: () => {
      const total = Number(budgetMajor);
      if (!Number.isFinite(total) || total < 0) {
        throw new Error("Enter a valid non-negative budget amount.");
      }
      if (selectedIds.length === 0) {
        throw new Error("Select at least one campaign.");
      }
      if (Math.abs(pctSum - 100) > 0.05) {
        throw new Error("Allocation percentages must sum to 100%.");
      }
      return advertisingApi
        .createSimulation({
          currency: currency.toUpperCase(),
          total_budget_minor: majorToMinor(total, currency),
          allocations: selectedIds.map((id) => ({
            campaign_id: id,
            allocation_pct: (pctById[id] ?? 0) / 100,
          })),
        })
        .then((r) => r.data);
    },
    onSuccess: (data) => setResult(data),
  });

  return (
    <PageShell wide>
      <PageHeader
        title="Budget Simulator"
        subtitle="Hypothetical budget allocation using observed reference metrics. Never modifies provider budgets."
        icon={Calculator}
        badge={<StatusBadge variant="info">Simulated</StatusBadge>}
      />
      <AdvertisingSubNav />

      <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700 dark-tenant:border-slate-800 dark-tenant:bg-slate-900/40 dark-tenant:text-slate-300">
        {SIM_DISCLAIMER}
      </p>

      {campaignsQuery.isLoading ? <LoadingState message="Loading campaigns…" /> : null}
      {campaignsQuery.isError && !campaignsQuery.isLoading ? (
        <ErrorState
          title="Unable to load campaigns"
          message={getApiErrorMessage(campaignsQuery.error)}
          onRetry={() => campaignsQuery.refetch()}
        />
      ) : null}

      {!campaignsQuery.isLoading && !campaignsQuery.isError ? (
        <>
          <PageSection title="Campaigns" description="Select campaigns to include in the hypothetical allocation.">
            {campaigns.length === 0 ? (
              <EmptyState
                title="No campaigns"
                description="Import an advertising account before running a simulation."
              />
            ) : (
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {campaigns.map((campaign) => {
                  const checked = selectedIds.includes(campaign.id);
                  return (
                    <label
                      key={campaign.id}
                      className="flex items-center gap-3 rounded-lg border border-slate-200 px-3 py-2 text-sm cursor-pointer hover:border-slate-300 dark-tenant:border-slate-800"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleCampaign(campaign)}
                      />
                      <span className="min-w-0 flex-1 truncate font-medium">{campaign.name}</span>
                      <span className="text-[11px] text-slate-500 shrink-0">
                        {titleCaseKey(campaign.provider)}
                        {campaign.currency ? ` · ${campaign.currency}` : ""}
                      </span>
                      <span className="tabular-nums text-slate-500 shrink-0">
                        {formatMoneyMinor(campaign.spend_minor, campaign.currency)}
                      </span>
                      <KindBadge kind="OBSERVED" />
                    </label>
                  );
                })}
              </div>
            )}
          </PageSection>

          <PageSection title="Hypothetical budget">
            <div className="flex flex-wrap gap-4 items-end">
              <label className="block text-sm">
                <span className="kpi-label">Currency</span>
                <input
                  className="mt-1 block w-28 rounded-lg border border-slate-200 px-3 py-2 text-sm dark-tenant:border-slate-800 dark-tenant:bg-slate-950"
                  value={currency}
                  maxLength={3}
                  onChange={(e) => {
                    setResult(null);
                    setCurrency(e.target.value.toUpperCase());
                  }}
                />
              </label>
              <label className="block text-sm">
                <span className="kpi-label">Total budget (major units)</span>
                <input
                  type="number"
                  min={0}
                  step="0.01"
                  className="mt-1 block w-40 rounded-lg border border-slate-200 px-3 py-2 text-sm tabular-nums dark-tenant:border-slate-800 dark-tenant:bg-slate-950"
                  value={budgetMajor}
                  onChange={(e) => {
                    setResult(null);
                    setBudgetMajor(e.target.value);
                  }}
                />
              </label>
            </div>
          </PageSection>

          {selectedCampaigns.length > 0 ? (
            <PageSection
              title="Allocation"
              description={`Percentages must sum to 100% (currently ${pctSum.toFixed(1)}%).`}
            >
              <div className="space-y-4">
                {selectedCampaigns.map((campaign) => {
                  const pct = pctById[campaign.id] ?? 0;
                  return (
                    <div key={campaign.id} className="space-y-1.5">
                      <div className="flex items-center justify-between gap-2 text-sm">
                        <span className="font-medium truncate">{campaign.name}</span>
                        <div className="flex items-center gap-2 shrink-0">
                          <input
                            type="number"
                            min={0}
                            max={100}
                            step={0.1}
                            className="w-20 rounded-lg border border-slate-200 px-2 py-1 text-sm tabular-nums dark-tenant:border-slate-800 dark-tenant:bg-slate-950"
                            value={pct}
                            onChange={(e) => setPct(campaign.id, Number(e.target.value))}
                          />
                          <span className="text-xs text-slate-500">%</span>
                        </div>
                      </div>
                      <input
                        type="range"
                        min={0}
                        max={100}
                        step={0.1}
                        value={pct}
                        onChange={(e) => setPct(campaign.id, Number(e.target.value))}
                        className="w-full"
                      />
                    </div>
                  );
                })}
              </div>
              <div className="mt-4">
                <button
                  type="button"
                  className="btn-primary text-sm"
                  disabled={simulateMutation.isPending || Math.abs(pctSum - 100) > 0.05}
                  onClick={() => simulateMutation.mutate()}
                >
                  {simulateMutation.isPending ? "Running…" : "Run simulation"}
                </button>
                {simulateMutation.isError ? (
                  <p className="mt-2 text-xs text-rose-600">
                    {getApiErrorMessage(simulateMutation.error)}
                  </p>
                ) : null}
              </div>
            </PageSection>
          ) : null}

          {result ? (
            <PageSection
              title="Simulation result"
              description={result.disclaimer ?? SIM_DISCLAIMER}
              action={<KindBadge kind={result.kind ?? "SIMULATED"} />}
            >
              <div className="mb-4 flex flex-wrap gap-3 text-sm">
                <div className="rounded-lg border border-slate-200 px-3 py-2 dark-tenant:border-slate-800">
                  <p className="kpi-label">Hypothetical total</p>
                  <p className="font-semibold tabular-nums">
                    {formatMoneyMinor(result.total_budget_minor, result.currency)}
                  </p>
                  <KindBadge kind="SIMULATED" />
                </div>
              </div>

              <div className="space-y-3">
                {(result.items ?? []).map((item) => {
                  const observedShare = parseShareFraction(item.observed_share);
                  const simulatedShare = parseShareFraction(item.simulated_share);
                  const ref = item.historical_reference_metrics ?? {};
                  return (
                    <div
                      key={item.campaign_id}
                      className="rounded-lg border border-slate-200 px-4 py-3 dark-tenant:border-slate-800"
                    >
                      <p className="font-medium text-sm">
                        {item.campaign_name ?? item.campaign_id}
                      </p>
                      <div className="mt-2 grid gap-3 sm:grid-cols-2">
                        <div className="rounded-md bg-slate-50 px-3 py-2 dark-tenant:bg-slate-900/50">
                          <div className="flex items-center gap-2">
                            <p className="kpi-label">Current observed</p>
                            <KindBadge kind="OBSERVED" />
                          </div>
                          <p className="mt-1 text-sm tabular-nums">
                            Spend {formatMoneyMinor(item.observed_spend_minor, result.currency)}
                          </p>
                          <p className="text-xs text-slate-500">
                            Share {formatRatioPct(observedShare)}
                          </p>
                          <div className="mt-2 space-y-0.5 text-[11px] text-slate-500">
                            {Object.entries(ref).map(([key, meta]) => (
                              <div key={key} className="flex justify-between gap-2">
                                <span>{titleCaseKey(key)}</span>
                                <span className="tabular-nums">
                                  {key.includes("minor")
                                    ? formatMoneyMinor(
                                        Number(meta.value),
                                        meta.currency ?? result.currency,
                                      )
                                    : formatNumber(Number(meta.value))}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                        <div className="rounded-md border border-dashed border-slate-300 px-3 py-2 dark-tenant:border-slate-700">
                          <div className="flex items-center gap-2">
                            <p className="kpi-label">Simulated allocation</p>
                            <KindBadge kind="SIMULATED" />
                          </div>
                          <p className="mt-1 text-sm tabular-nums">
                            Budget{" "}
                            {formatMoneyMinor(item.simulated_budget_minor, result.currency)}
                          </p>
                          <p className="text-xs text-slate-500">
                            Share {formatRatioPct(simulatedShare)} · Input{" "}
                            {formatRatioPct(parseShareFraction(item.allocation_pct))}
                          </p>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </PageSection>
          ) : null}
        </>
      ) : null}
    </PageShell>
  );
}
