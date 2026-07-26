"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Compass, FileText, Sparkles } from "lucide-react";

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
  advertisingApi,
  getApiErrorMessage,
} from "@/lib/api";
import { formatWhen, titleCaseKey } from "@/lib/advertising-ui";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

export default function AdvertisingDecisionSupportPage() {
  const queryClient = useQueryClient();

  const recommendationsQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "decision-support", "recommendations"],
    queryFn: () =>
      advertisingApi.decisionSupportRecommendations({ limit: 50 }).then((r) => r.data),
    ...QUERY_OPTS,
  });

  const concentrationQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "diagnostics", "concentration"],
    queryFn: () => advertisingApi.diagnosticsConcentration({ level: "campaign" }).then((r) => r.data),
    ...QUERY_OPTS,
  });

  const rotationQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "diagnostics", "creative-rotation"],
    queryFn: () => advertisingApi.diagnosticsCreativeRotation().then((r) => r.data),
    ...QUERY_OPTS,
  });

  const plansQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "change-plans"],
    queryFn: () => advertisingApi.listChangePlans({ limit: 50 }).then((r) => r.data),
    ...QUERY_OPTS,
  });

  const invalidatePlans = () =>
    queryClient.invalidateQueries({ queryKey: [...ADVERTISING_QUERY_KEY, "change-plans"] });

  const generateMutation = useMutation({
    mutationFn: () => advertisingApi.generateChangePlan().then((r) => r.data),
    onSuccess: () => invalidatePlans(),
  });

  const reviewMutation = useMutation({
    mutationFn: (planId: string) => advertisingApi.reviewChangePlan(planId).then((r) => r.data),
    onSuccess: () => invalidatePlans(),
  });

  const dismissMutation = useMutation({
    mutationFn: (planId: string) => advertisingApi.dismissChangePlan(planId).then((r) => r.data),
    onSuccess: () => invalidatePlans(),
  });

  const recommendations = recommendationsQuery.data?.items ?? [];
  const plans = plansQuery.data?.items ?? [];
  const loading =
    recommendationsQuery.isLoading ||
    concentrationQuery.isLoading ||
    rotationQuery.isLoading ||
    plansQuery.isLoading;
  const error =
    recommendationsQuery.error ||
    concentrationQuery.error ||
    rotationQuery.error ||
    plansQuery.error;

  return (
    <PageShell wide>
      <PageHeader
        title="Decision Support"
        subtitle="Advisory recommendations and draft change plans. Never modifies provider campaigns, budgets, or creatives."
        icon={Compass}
        badge={<StatusBadge variant="neutral">Advisory only</StatusBadge>}
      />
      <AdvertisingSubNav />

      <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark-tenant:border-amber-500/30 dark-tenant:bg-amber-500/10 dark-tenant:text-amber-100">
        Advisory only — this surface does not apply, pause, launch, or otherwise modify anything on
        the ad provider.
      </p>

      {loading ? <LoadingState message="Loading decision support…" /> : null}

      {error && !loading ? (
        <ErrorState
          title="Unable to load decision support"
          message={getApiErrorMessage(error)}
          onRetry={() => {
            recommendationsQuery.refetch();
            concentrationQuery.refetch();
            rotationQuery.refetch();
            plansQuery.refetch();
          }}
        />
      ) : null}

      {!loading && !error ? (
        <>
          <div className="grid gap-6 xl:grid-cols-2">
            <PageSection
              title="Concentration"
              description="Observed spend distribution across campaigns."
              action={<KindBadge kind={concentrationQuery.data?.kind ?? "OBSERVED"} />}
            >
              {concentrationQuery.data?.observation ? (
                <div className="space-y-2 text-sm">
                  <p>{concentrationQuery.data.observation}</p>
                  {concentrationQuery.data.interpretation ? (
                    <p className="text-slate-500">{concentrationQuery.data.interpretation}</p>
                  ) : null}
                  {concentrationQuery.data.possible_consideration ? (
                    <p className="text-slate-600 dark-tenant:text-slate-300">
                      {concentrationQuery.data.possible_consideration}
                    </p>
                  ) : null}
                </div>
              ) : (
                <p className="text-sm text-slate-500">No concentration signal available.</p>
              )}
            </PageSection>

            <PageSection
              title="Creative rotation"
              description="Observed creative exposure and fatigue-adjacent signals."
              action={<KindBadge kind={rotationQuery.data?.kind ?? "OBSERVED"} />}
            >
              {rotationQuery.data?.observation ? (
                <div className="space-y-2 text-sm">
                  <p>{rotationQuery.data.observation}</p>
                  {rotationQuery.data.interpretation ? (
                    <p className="text-slate-500">{rotationQuery.data.interpretation}</p>
                  ) : null}
                  {rotationQuery.data.possible_consideration ? (
                    <p className="text-slate-600 dark-tenant:text-slate-300">
                      {rotationQuery.data.possible_consideration}
                    </p>
                  ) : null}
                </div>
              ) : (
                <p className="text-sm text-slate-500">No creative rotation signal available.</p>
              )}
            </PageSection>
          </div>

          <PageSection
            title="Recommendations"
            description="Deterministic advisory suggestions from observed diagnostics."
          >
            {recommendations.length === 0 ? (
              <EmptyState
                title="No recommendations"
                description="Import accounts and refresh metrics to generate advisory recommendations."
              />
            ) : (
              <div className="space-y-3">
                {recommendations.map((rec, idx) => (
                  <div
                    key={rec.id ?? rec.recommendation_key ?? idx}
                    className="rounded-lg border border-slate-200 px-4 py-3 dark-tenant:border-slate-800"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <KindBadge kind={rec.kind ?? "DIRECTIONAL"} />
                      {rec.item_type ? (
                        <StatusBadge variant="neutral">{titleCaseKey(rec.item_type)}</StatusBadge>
                      ) : null}
                      {rec.risk ? (
                        <span className="text-[11px] text-slate-500">Risk: {rec.risk}</span>
                      ) : null}
                    </div>
                    <p className="mt-2 text-sm font-medium">
                      {rec.recommendation ?? rec.title ?? "Advisory recommendation"}
                    </p>
                    {rec.observation ? (
                      <p className="mt-1 text-sm text-slate-600 dark-tenant:text-slate-300">
                        {rec.observation}
                      </p>
                    ) : null}
                    {rec.reasoning ? (
                      <p className="mt-1 text-xs text-slate-500">{rec.reasoning}</p>
                    ) : null}
                    {rec.limitations && rec.limitations.length > 0 ? (
                      <ul className="mt-2 space-y-0.5 text-[11px] text-slate-500">
                        {rec.limitations.map((lim) => (
                          <li key={lim}>• {lim}</li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </PageSection>

          <PageSection
            title="Change plans"
            description="Draft human-review plans. Not executable against any provider."
            action={
              <button
                type="button"
                className="btn-secondary text-xs inline-flex items-center gap-1.5"
                disabled={generateMutation.isPending}
                onClick={() => generateMutation.mutate()}
              >
                <Sparkles size={14} />
                {generateMutation.isPending ? "Generating…" : "Generate draft change plan"}
              </button>
            }
          >
            {generateMutation.isError ? (
              <p className="mb-3 text-xs text-rose-600">
                {getApiErrorMessage(generateMutation.error)}
              </p>
            ) : null}

            {plans.length === 0 ? (
              <EmptyState
                title="No change plans"
                description="Generate a draft from current recommendations for human review."
              />
            ) : (
              <div className="space-y-3">
                {plans.map((plan) => (
                  <div
                    key={plan.id}
                    className="rounded-lg border border-slate-200 px-4 py-3 dark-tenant:border-slate-800"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <FileText size={14} className="text-slate-400 shrink-0" />
                          <p className="font-medium text-sm truncate">{plan.title}</p>
                          <StatusBadge variant="neutral">{titleCaseKey(plan.status)}</StatusBadge>
                          {plan.executable === false ? (
                            <StatusBadge variant="info">Not executable</StatusBadge>
                          ) : null}
                        </div>
                        {plan.summary ? (
                          <p className="mt-1 text-sm text-slate-600 dark-tenant:text-slate-300">
                            {plan.summary}
                          </p>
                        ) : null}
                        <p className="mt-1 text-[11px] text-slate-500">
                          Created {formatWhen(plan.created_at)}
                          {plan.items?.length
                            ? ` · ${plan.items.length} item${plan.items.length === 1 ? "" : "s"}`
                            : ""}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2 shrink-0">
                        {plan.status === "draft" ? (
                          <button
                            type="button"
                            className="btn-secondary text-xs"
                            disabled={reviewMutation.isPending}
                            onClick={() => reviewMutation.mutate(plan.id)}
                          >
                            Mark reviewed
                          </button>
                        ) : null}
                        {plan.status === "draft" || plan.status === "reviewed" ? (
                          <button
                            type="button"
                            className="btn-secondary text-xs"
                            disabled={dismissMutation.isPending}
                            onClick={() => dismissMutation.mutate(plan.id)}
                          >
                            Dismiss
                          </button>
                        ) : null}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </PageSection>
        </>
      ) : null}
    </PageShell>
  );
}
