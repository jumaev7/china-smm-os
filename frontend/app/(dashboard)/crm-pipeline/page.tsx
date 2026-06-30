"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Kanban, RefreshCw } from "lucide-react";
import toast from "react-hot-toast";
import {
  CrmPipelineFilterBar,
  DEFAULT_CRM_PIPELINE_FILTERS,
  applyCrmPipelineFilters,
  extractOwnersFromDeals,
  type CrmPipelineFilters,
} from "@/components/crm-pipeline/CrmPipelineFilters";
import { DealDrawer } from "@/components/crm-pipeline/DealDrawer";
import { ExecutiveBriefPanel } from "@/components/crm-pipeline/ExecutiveBriefPanel";
import { ManagerPerformancePanel } from "@/components/crm-pipeline/ManagerPerformancePanel";
import { PipelineColumn } from "@/components/crm-pipeline/PipelineColumn";
import { PipelineKpiRow } from "@/components/crm-pipeline/PipelineKpiRow";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { PageHeader, PageShell } from "@/components/ui/design-system";
import {
  crmPipelineApi,
  normalizeList,
  publishingApi,
  salesCrmApi,
  SALES_DEAL_STAGES,
  type Platform,
  type PublishingAccount,
  type SalesCustomer,
  type SalesDeal,
  type SalesDealStage,
} from "@/lib/api";
import { crmPipelineCanTransition } from "@/lib/crm-pipeline";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";

function stageLabel(stage: SalesDealStage, t: (k: string) => string) {
  const key = `salesCrm.stage.${stage}`;
  const translated = t(key);
  return translated === key ? stage.replace(/_/g, " ") : translated;
}

const QUERY_ROOT = ["executive-crm-pipeline"];

const META_PLATFORMS = new Set<Platform>(["facebook", "instagram"]);
const META_USABLE = new Set(["connected", "mock"]);

function buildMetaByCustomer(
  customers: SalesCustomer[],
  accounts: PublishingAccount[],
): Map<string, boolean> {
  const metaAccountIds = new Set(
    accounts
      .filter((a) => META_PLATFORMS.has(a.platform) && META_USABLE.has(a.status))
      .map((a) => a.id),
  );
  const map = new Map<string, boolean>();
  for (const c of customers) {
    if (c.id && c.primary_publishing_account_id) {
      map.set(c.id, metaAccountIds.has(c.primary_publishing_account_id));
    }
  }
  return map;
}

export default function CrmPipelinePage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [filters, setFilters] = useState<CrmPipelineFilters>(DEFAULT_CRM_PIPELINE_FILTERS);
  const [selectedDeal, setSelectedDeal] = useState<SalesDeal | null>(null);
  const [draggingDeal, setDraggingDeal] = useState<SalesDeal | null>(null);
  const [dragOverStage, setDragOverStage] = useState<SalesDealStage | null>(null);

  const dashboardQuery = useQuery({
    queryKey: [...QUERY_ROOT, "dashboard"],
    queryFn: () => crmPipelineApi.dashboard().then((r) => r.data),
  });

  const managerQuery = useQuery({
    queryKey: [...QUERY_ROOT, "manager-insights"],
    queryFn: () => crmPipelineApi.managerInsights().then((r) => r.data),
  });

  const briefQuery = useQuery({
    queryKey: [...QUERY_ROOT, "morning-brief"],
    queryFn: () => crmPipelineApi.morningBrief().then((r) => r.data),
    staleTime: 120_000,
  });

  const dealsQuery = useQuery({
    queryKey: [...QUERY_ROOT, "deals"],
    queryFn: () => crmPipelineApi.listDeals({ limit: 200 }).then((r) => r.data),
  });

  const customersQuery = useQuery({
    queryKey: [...QUERY_ROOT, "customers"],
    queryFn: () => salesCrmApi.listCustomers({ limit: 500 }).then((r) => r.data),
    staleTime: 60_000,
  });

  const accountsQuery = useQuery({
    queryKey: [...QUERY_ROOT, "publishing-accounts"],
    queryFn: () => publishingApi.listAccounts().then((r) => r.data),
    staleTime: 60_000,
  });

  const moveMutation = useMutation({
    mutationFn: ({ dealId, stage }: { dealId: string; stage: SalesDealStage }) =>
      crmPipelineApi.updateDealStage(dealId, { stage, stage_override: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QUERY_ROOT });
      toast.success(t("crmPipeline.stageUpdated"));
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const allDeals = normalizeList(dealsQuery.data) as SalesDeal[];
  const customers = normalizeList(customersQuery.data) as SalesCustomer[];
  const accounts = normalizeList(accountsQuery.data) as PublishingAccount[];

  const metaByCustomer = useMemo(
    () => buildMetaByCustomer(customers, accounts),
    [customers, accounts],
  );

  const filteredDeals = useMemo(
    () => applyCrmPipelineFilters(allDeals, filters),
    [allDeals, filters],
  );

  const dealsByStage = useMemo(() => {
    const map = Object.fromEntries(SALES_DEAL_STAGES.map((s) => [s, [] as SalesDeal[]])) as Record<
      SalesDealStage,
      SalesDeal[]
    >;
    for (const deal of filteredDeals) {
      if (map[deal.stage]) map[deal.stage].push(deal);
    }
    return map;
  }, [filteredDeals]);

  const owners = useMemo(() => extractOwnersFromDeals(allDeals), [allDeals]);

  const handleDragStart = useCallback((deal: SalesDeal, e: React.DragEvent) => {
    setDraggingDeal(deal);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", deal.id);
  }, []);

  const handleDrop = useCallback(
    (targetStage: SalesDealStage, e: React.DragEvent) => {
      e.preventDefault();
      setDragOverStage(null);
      const deal = draggingDeal;
      setDraggingDeal(null);
      if (!deal || deal.stage === targetStage) return;

      if (!crmPipelineCanTransition(deal.stage, targetStage)) {
        toast.error(
          t("crmPipeline.illegalTransition", {
            from: stageLabel(deal.stage, t),
            to: stageLabel(targetStage, t),
          }),
        );
        return;
      }

      moveMutation.mutate({ dealId: deal.id, stage: targetStage });
    },
    [draggingDeal, moveMutation, t],
  );

  const isLoading = dashboardQuery.isLoading || dealsQuery.isLoading || managerQuery.isLoading;
  const isError = dashboardQuery.isError || dealsQuery.isError || managerQuery.isError;
  const error =
    dashboardQuery.error || dealsQuery.error || managerQuery.error;

  const refetchAll = () => {
    dashboardQuery.refetch();
    dealsQuery.refetch();
    managerQuery.refetch();
    briefQuery.refetch();
    customersQuery.refetch();
    accountsQuery.refetch();
  };

  if (isLoading) {
    return (
      <PageShell>
        <LoadingState message={t("crmPipeline.loading")} />
      </PageShell>
    );
  }

  if (isError) {
    return (
      <PageShell>
        <ErrorState
          message={error instanceof Error ? error.message : t("crmPipeline.error")}
          onRetry={refetchAll}
        />
      </PageShell>
    );
  }

  const dashboard = dashboardQuery.data;
  const managerPerf = managerQuery.data;

  if (!dashboard || !managerPerf) return null;

  const visibleStages = filters.stage
    ? SALES_DEAL_STAGES.filter((s) => s === filters.stage)
    : SALES_DEAL_STAGES;

  const drawerDeal = selectedDeal
    ? allDeals.find((d) => d.id === selectedDeal.id) ?? selectedDeal
    : null;

  return (
    <PageShell wide className="space-y-5">
      <PageHeader
        title={t("crmPipeline.title")}
        subtitle={t("crmPipeline.subtitle")}
        icon={Kanban}
        actions={
          <button
            type="button"
            onClick={refetchAll}
            className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 dark-tenant:border-white/[0.08] dark-tenant:text-slate-400 dark-tenant:hover:bg-white/[0.04] transition-colors"
          >
            <RefreshCw size={13} className={cn(dealsQuery.isFetching && "animate-spin")} />
            {t("common.refresh")}
          </button>
        }
      />

      <ExecutiveBriefPanel brief={briefQuery.data} isLoading={briefQuery.isLoading} />

      <PipelineKpiRow dashboard={dashboard} managerPerf={managerPerf} />

      <ManagerPerformancePanel data={managerPerf} />

      <CrmPipelineFilterBar filters={filters} onChange={setFilters} owners={owners} />

      {filteredDeals.length === 0 ? (
        <EmptyState
          title={t("crmPipeline.noDeals")}
          description={t("crmPipeline.noDealsHint")}
          action={
            <Link href="/deals" className="btn-primary text-sm mt-2">
              {t("crmPipeline.createDeal")}
            </Link>
          }
        />
      ) : (
        <div className="overflow-x-auto pb-4 -mx-1 px-1">
          <div className="flex gap-3 min-w-max">
            {visibleStages.map((stage) => (
              <PipelineColumn
                key={stage}
                stage={stage}
                deals={dealsByStage[stage]}
                metaByCustomer={metaByCustomer}
                dragOver={dragOverStage === stage}
                draggingDealId={draggingDeal?.id ?? null}
                onDealClick={setSelectedDeal}
                onDragStart={handleDragStart}
                onDragOver={(e) => {
                  e.preventDefault();
                  e.dataTransfer.dropEffect = "move";
                  setDragOverStage(stage);
                }}
                onDragLeave={() => setDragOverStage(null)}
                onDrop={(e) => handleDrop(stage, e)}
              />
            ))}
          </div>
        </div>
      )}

      {drawerDeal && (
        <DealDrawer
          deal={drawerDeal}
          publishingHealth={dashboard.publishing_health}
          metaConnected={
            drawerDeal.customer_id
              ? metaByCustomer.get(drawerDeal.customer_id) === true
              : false
          }
          onClose={() => setSelectedDeal(null)}
        />
      )}
    </PageShell>
  );
}
