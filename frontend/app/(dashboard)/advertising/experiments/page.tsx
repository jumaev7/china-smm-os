"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical } from "lucide-react";

import { AdvertisingSubNav } from "@/components/advertising/AdvertisingSubNav";
import { KindBadge } from "@/components/advertising/KindBadge";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  ActionBar,
  DataTable,
  DataTableBody,
  DataTableHead,
  DataTableRow,
  DataTableTd,
  DataTableTh,
  FilterBar,
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

const STATUS_OPTIONS = [
  { label: "All statuses", value: "" },
  { label: "Draft", value: "draft" },
  { label: "Ready", value: "ready" },
  { label: "Observing", value: "running_observation" },
  { label: "Completed", value: "completed" },
  { label: "Cancelled", value: "cancelled" },
  { label: "Archived", value: "archived" },
];

const EXPERIMENT_TYPES = [
  { value: "creative", label: "Creative" },
  { value: "audience", label: "Audience" },
  { value: "bidding", label: "Bidding" },
  { value: "budget", label: "Budget" },
  { value: "other", label: "Other" },
];

type VariantForm = {
  variant_key: string;
  label: string;
  entity_type: string;
  entity_id: string;
};

const EMPTY_VARIANT = (): VariantForm => ({
  variant_key: "",
  label: "",
  entity_type: "campaign",
  entity_id: "",
});

export default function AdvertisingExperimentsPage() {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [experimentType, setExperimentType] = useState("creative");
  const [hypothesis, setHypothesis] = useState("");
  const [primaryMetric, setPrimaryMetric] = useState("conversions");
  const [currency, setCurrency] = useState("");
  const [variants, setVariants] = useState<VariantForm[]>([
    { ...EMPTY_VARIANT(), variant_key: "A", label: "Variant A" },
    { ...EMPTY_VARIANT(), variant_key: "B", label: "Variant B" },
  ]);

  const experimentsQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "experiments", status],
    queryFn: () =>
      advertisingApi
        .listExperiments({ status: status || undefined, limit: 100 })
        .then((r) => r.data),
    ...QUERY_OPTS,
  });

  const createMutation = useMutation({
    mutationFn: () =>
      advertisingApi
        .createExperiment({
          name: name.trim(),
          experiment_type: experimentType,
          hypothesis: hypothesis.trim(),
          primary_metric_key: primaryMetric.trim(),
          currency: currency.trim() ? currency.trim().toUpperCase() : null,
          variants: variants.map((v) => ({
            variant_key: v.variant_key.trim(),
            label: v.label.trim(),
            entity_type: v.entity_type.trim(),
            entity_id: v.entity_id.trim(),
          })),
        })
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [...ADVERTISING_QUERY_KEY, "experiments"] });
      setShowForm(false);
      setName("");
      setHypothesis("");
      setVariants([
        { ...EMPTY_VARIANT(), variant_key: "A", label: "Variant A" },
        { ...EMPTY_VARIANT(), variant_key: "B", label: "Variant B" },
      ]);
    },
  });

  const items = experimentsQuery.data?.items ?? [];

  return (
    <PageShell wide>
      <PageHeader
        title="Experiments"
        subtitle="Observation plans only. Experiments are never launched on Meta or any other provider from this platform."
        icon={FlaskConical}
        badge={<StatusBadge variant="neutral">Observation only</StatusBadge>}
        actions={
          <button
            type="button"
            className="btn-secondary text-sm"
            onClick={() => setShowForm((v) => !v)}
          >
            {showForm ? "Hide form" : "Create experiment"}
          </button>
        }
      />
      <AdvertisingSubNav />

      <ActionBar>
        <div className="flex flex-wrap items-center gap-3">
          <FilterBar options={STATUS_OPTIONS} value={status} onChange={setStatus} />
          <span className="text-xs text-slate-500">
            {experimentsQuery.data?.total ?? 0} experiments
          </span>
        </div>
      </ActionBar>

      {showForm ? (
        <PageSection
          title="Create observation plan"
          description="Define a hypothesis and entity variants to observe. No provider launch actions are available."
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-sm sm:col-span-2">
              <span className="kpi-label">Name</span>
              <input
                className="mt-1 block w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark-tenant:border-slate-800 dark-tenant:bg-slate-950"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label className="block text-sm">
              <span className="kpi-label">Type</span>
              <select
                className="mt-1 block w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark-tenant:border-slate-800 dark-tenant:bg-slate-950"
                value={experimentType}
                onChange={(e) => setExperimentType(e.target.value)}
              >
                {EXPERIMENT_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              <span className="kpi-label">Primary metric</span>
              <input
                className="mt-1 block w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark-tenant:border-slate-800 dark-tenant:bg-slate-950"
                value={primaryMetric}
                onChange={(e) => setPrimaryMetric(e.target.value)}
                placeholder="e.g. conversions, ctr, cpa_minor"
              />
            </label>
            <label className="block text-sm sm:col-span-2">
              <span className="kpi-label">Hypothesis</span>
              <textarea
                rows={3}
                className="mt-1 block w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark-tenant:border-slate-800 dark-tenant:bg-slate-950"
                value={hypothesis}
                onChange={(e) => setHypothesis(e.target.value)}
              />
            </label>
            <label className="block text-sm">
              <span className="kpi-label">Currency (optional)</span>
              <input
                className="mt-1 block w-28 rounded-lg border border-slate-200 px-3 py-2 text-sm dark-tenant:border-slate-800 dark-tenant:bg-slate-950"
                value={currency}
                maxLength={3}
                onChange={(e) => setCurrency(e.target.value.toUpperCase())}
              />
            </label>
          </div>

          <div className="mt-4 space-y-3">
            <p className="kpi-label">Variants (entity IDs)</p>
            {variants.map((variant, idx) => (
              <div
                key={idx}
                className="grid gap-2 sm:grid-cols-4 rounded-lg border border-slate-200 p-3 dark-tenant:border-slate-800"
              >
                <input
                  placeholder="Key"
                  className="rounded-lg border border-slate-200 px-2 py-1.5 text-sm dark-tenant:border-slate-800 dark-tenant:bg-slate-950"
                  value={variant.variant_key}
                  onChange={(e) => {
                    const next = [...variants];
                    next[idx] = { ...variant, variant_key: e.target.value };
                    setVariants(next);
                  }}
                />
                <input
                  placeholder="Label"
                  className="rounded-lg border border-slate-200 px-2 py-1.5 text-sm dark-tenant:border-slate-800 dark-tenant:bg-slate-950"
                  value={variant.label}
                  onChange={(e) => {
                    const next = [...variants];
                    next[idx] = { ...variant, label: e.target.value };
                    setVariants(next);
                  }}
                />
                <select
                  className="rounded-lg border border-slate-200 px-2 py-1.5 text-sm dark-tenant:border-slate-800 dark-tenant:bg-slate-950"
                  value={variant.entity_type}
                  onChange={(e) => {
                    const next = [...variants];
                    next[idx] = { ...variant, entity_type: e.target.value };
                    setVariants(next);
                  }}
                >
                  <option value="campaign">Campaign</option>
                  <option value="ad_group">Ad group</option>
                  <option value="ad">Ad</option>
                  <option value="creative">Creative</option>
                </select>
                <input
                  placeholder="Entity UUID"
                  className="rounded-lg border border-slate-200 px-2 py-1.5 text-sm dark-tenant:border-slate-800 dark-tenant:bg-slate-950"
                  value={variant.entity_id}
                  onChange={(e) => {
                    const next = [...variants];
                    next[idx] = { ...variant, entity_id: e.target.value };
                    setVariants(next);
                  }}
                />
              </div>
            ))}
            {variants.length < 6 ? (
              <button
                type="button"
                className="btn-secondary text-xs"
                onClick={() => setVariants((v) => [...v, EMPTY_VARIANT()])}
              >
                Add variant
              </button>
            ) : null}
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              className="btn-primary text-sm"
              disabled={
                createMutation.isPending ||
                !name.trim() ||
                !hypothesis.trim() ||
                variants.length < 2 ||
                variants.some((v) => !v.variant_key || !v.label || !v.entity_id)
              }
              onClick={() => createMutation.mutate()}
            >
              {createMutation.isPending ? "Creating…" : "Create experiment"}
            </button>
            {createMutation.isError ? (
              <p className="text-xs text-rose-600">{getApiErrorMessage(createMutation.error)}</p>
            ) : null}
          </div>
        </PageSection>
      ) : null}

      {experimentsQuery.isLoading ? <LoadingState message="Loading experiments…" /> : null}
      {experimentsQuery.isError && !experimentsQuery.isLoading ? (
        <ErrorState
          title="Unable to load experiments"
          message={getApiErrorMessage(experimentsQuery.error)}
          onRetry={() => experimentsQuery.refetch()}
        />
      ) : null}

      {!experimentsQuery.isLoading && !experimentsQuery.isError ? (
        items.length === 0 ? (
          <EmptyState
            title="No experiments"
            description="Create an observation plan to track a hypothesis across entity variants."
          />
        ) : (
          <DataTable>
            <DataTableHead>
              <DataTableRow>
                <DataTableTh>Experiment</DataTableTh>
                <DataTableTh>Type</DataTableTh>
                <DataTableTh>Status</DataTableTh>
                <DataTableTh>Primary metric</DataTableTh>
                <DataTableTh>Kind</DataTableTh>
                <DataTableTh>Created</DataTableTh>
              </DataTableRow>
            </DataTableHead>
            <DataTableBody>
              {items.map((exp) => (
                <DataTableRow key={exp.id}>
                  <DataTableTd>
                    <Link
                      href={`/advertising/experiments/${exp.id}`}
                      className="font-medium hover:underline"
                    >
                      {exp.name}
                    </Link>
                    <p className="text-[11px] text-slate-500 line-clamp-1">{exp.hypothesis}</p>
                  </DataTableTd>
                  <DataTableTd>{titleCaseKey(exp.experiment_type)}</DataTableTd>
                  <DataTableTd>
                    <StatusBadge variant="neutral">{titleCaseKey(exp.status)}</StatusBadge>
                  </DataTableTd>
                  <DataTableTd className="tabular-nums text-sm">
                    {exp.primary_metric_key}
                  </DataTableTd>
                  <DataTableTd>
                    <KindBadge kind={exp.kind ?? "OBSERVATION_PLAN"} />
                  </DataTableTd>
                  <DataTableTd className="text-sm text-slate-500">
                    {formatWhen(exp.created_at)}
                  </DataTableTd>
                </DataTableRow>
              ))}
            </DataTableBody>
          </DataTable>
        )
      ) : null}
    </PageShell>
  );
}
