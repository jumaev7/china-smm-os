"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { IntegrationCard } from "@/components/integrations/IntegrationCard";
import { IntegrationCenterHeader } from "@/components/integrations/IntegrationCenterHeader";
import { IntegrationCenterSkeleton } from "@/components/integrations/IntegrationCenterSkeleton";
import { IntegrationDetailDrawer } from "@/components/integrations/IntegrationDetailDrawer";
import {
  IntegrationAttentionPanel,
  IntegrationConnectedPanel,
  IntegrationEmptyState,
} from "@/components/integrations/IntegrationPanels";
import { ErrorState } from "@/components/ui/PageStates";
import { PageShell } from "@/components/ui/design-system";
import { useIntegrationCenterData } from "@/lib/integration-center-hooks";
import {
  filterIntegrationsByCategory,
  INTEGRATION_CATEGORIES,
  type IntegrationCategory,
  type ResolvedIntegration,
} from "@/lib/integration-center-ui";
import { cn } from "@/lib/utils";

export default function IntegrationsPage() {
  const [activeCategory, setActiveCategory] = useState<IntegrationCategory>("all");
  const [selected, setSelected] = useState<ResolvedIntegration | null>(null);

  const { integrations, summary, isLoading, isError, error, refetch, isFetching } =
    useIntegrationCenterData();

  const filtered = useMemo(
    () => filterIntegrationsByCategory(integrations, activeCategory),
    [integrations, activeCategory],
  );

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelected(null);
    };
    if (selected) {
      document.addEventListener("keydown", onKeyDown);
      return () => document.removeEventListener("keydown", onKeyDown);
    }
  }, [selected]);

  const showEmpty = !isLoading && !isError && summary.connectedCount === 0;

  return (
    <PageShell wide>
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div className="flex-1 min-w-0">
          <IntegrationCenterHeader
            connectedCount={summary.connectedCount}
            attentionCount={summary.attentionCount}
            notConnectedCount={summary.notConnectedCount}
            overallHealth={summary.overallHealth}
            activeCategory={activeCategory}
            onCategoryChange={setActiveCategory}
            categories={INTEGRATION_CATEGORIES}
          />
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          className={cn(
            "inline-flex items-center gap-2 self-start rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium",
            "text-gray-700 hover:border-brand-200 hover:text-brand-700 transition-colors disabled:opacity-60",
            "dark-tenant:bg-surface-dark-elevated dark-tenant:border-white/10 dark-tenant:text-slate-300",
            "dark-tenant:hover:border-violet-500/30 dark-tenant:hover:text-violet-300",
          )}
          aria-label="Refresh integrations"
        >
          <RefreshCw size={14} className={cn(isFetching && "animate-spin")} />
          Refresh
        </button>
      </div>

      {isLoading && <IntegrationCenterSkeleton />}

      {isError && (
        <ErrorState
          message={error instanceof Error ? error.message : "Failed to load integrations"}
          onRetry={() => refetch()}
        />
      )}

      {!isLoading && !isError && (
        <div className="space-y-6">
          {summary.attention.length > 0 ? (
            <IntegrationAttentionPanel items={summary.attention} onSelect={setSelected} />
          ) : null}

          {summary.connected.length > 0 ? (
            <IntegrationConnectedPanel items={summary.connected} onSelect={setSelected} />
          ) : null}

          {showEmpty ? <IntegrationEmptyState /> : null}

          <section aria-label="All integrations">
            <div className="flex items-center justify-between gap-2 mb-3">
              <h2 className="section-title">
                {activeCategory === "all"
                  ? "All integrations"
                  : INTEGRATION_CATEGORIES.find((c) => c.id === activeCategory)?.label}
              </h2>
              <span className="text-xs text-gray-500 dark-tenant:text-slate-500">
                {filtered.length} {filtered.length === 1 ? "integration" : "integrations"}
              </span>
            </div>

            {filtered.length === 0 ? (
              <p className="text-sm text-gray-500 py-8 text-center dark-tenant:text-slate-500">
                No integrations in this category.
              </p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {filtered.map((integration, index) => (
                  <IntegrationCard
                    key={integration.key}
                    integration={integration}
                    onSelect={setSelected}
                    index={index}
                  />
                ))}
              </div>
            )}
          </section>
        </div>
      )}

      <IntegrationDetailDrawer integration={selected} onClose={() => setSelected(null)} />
    </PageShell>
  );
}
