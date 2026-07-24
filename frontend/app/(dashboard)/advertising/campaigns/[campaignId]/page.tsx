"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { ArrowLeft, Link2, Megaphone, Unlink } from "lucide-react";

import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  DataTable,
  DataTableBody,
  DataTableHead,
  DataTableRow,
  DataTableTd,
  DataTableTh,
  KpiCard,
  PageHeader,
  PageSection,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import { ADVERTISING_QUERY_KEY, advertisingApi, getApiErrorMessage } from "@/lib/api";
import {
  entityStatusVariant,
  formatMoneyMinor,
  formatNumber,
  formatRatioPct,
  freshnessVariant,
  pacingLabel,
  pacingVariant,
  titleCaseKey,
} from "@/lib/advertising-ui";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

export default function AdvertisingCampaignDetailPage() {
  const params = useParams();
  const campaignId = String(params.campaignId);
  const queryClient = useQueryClient();
  const [internalId, setInternalId] = useState("");

  const campaignQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "campaign", campaignId],
    queryFn: () => advertisingApi.getCampaign(campaignId).then((r) => r.data),
    ...QUERY_OPTS,
  });
  const perfQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "campaign", campaignId, "performance"],
    queryFn: () => advertisingApi.campaignPerformance(campaignId).then((r) => r.data),
    ...QUERY_OPTS,
  });
  const adGroupsQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "campaign", campaignId, "ad-groups"],
    queryFn: () => advertisingApi.campaignAdGroups(campaignId, { limit: 100 }).then((r) => r.data),
    ...QUERY_OPTS,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: [...ADVERTISING_QUERY_KEY, "campaign", campaignId] });

  const linkMutation = useMutation({
    mutationFn: () => advertisingApi.linkCampaign(campaignId, internalId.trim()).then((r) => r.data),
    onSuccess: () => {
      toast.success("Linked to internal campaign");
      setInternalId("");
      invalidate();
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });
  const unlinkMutation = useMutation({
    mutationFn: () => advertisingApi.unlinkCampaign(campaignId).then((r) => r.data),
    onSuccess: () => {
      toast.success("Unlinked");
      invalidate();
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const campaign = campaignQuery.data;
  const perf = perfQuery.data;
  const adGroups = adGroupsQuery.data?.items ?? [];

  return (
    <PageShell wide>
      <PageHeader
        title={campaign?.name ?? "Campaign"}
        subtitle="Read-only provider campaign. No create, edit, pause, or budget actions are available."
        icon={Megaphone}
        badge={<StatusBadge variant="neutral">Read-only</StatusBadge>}
        actions={
          <Link href="/advertising/campaigns" className="btn-secondary text-sm">
            <ArrowLeft size={14} /> Campaigns
          </Link>
        }
      />

      {campaignQuery.isLoading ? <LoadingState message="Loading campaign…" /> : null}
      {campaignQuery.isError && !campaignQuery.isLoading ? (
        <ErrorState
          title="Unable to load campaign"
          message={getApiErrorMessage(campaignQuery.error)}
          onRetry={() => campaignQuery.refetch()}
        />
      ) : null}

      {campaign ? (
        <>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <StatusBadge variant={entityStatusVariant(campaign.status)}>
              {titleCaseKey(campaign.status)}
            </StatusBadge>
            <StatusBadge variant={pacingVariant(campaign.pacing_status)}>
              {pacingLabel(campaign.pacing_status)}
            </StatusBadge>
            <StatusBadge variant={freshnessVariant(campaign.freshness_status)}>
              {titleCaseKey(campaign.freshness_status)}
            </StatusBadge>
            <span className="text-slate-500">
              {titleCaseKey(campaign.provider)}
              {campaign.objective ? ` · ${titleCaseKey(campaign.objective)}` : ""}
            </span>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              label="Spend"
              value={formatMoneyMinor(perf?.spend_minor ?? campaign.spend_minor, perf?.currency ?? campaign.currency)}
            />
            <KpiCard label="Impressions" value={formatNumber(perf?.impressions ?? campaign.impressions)} />
            <KpiCard
              label="Clicks"
              value={formatNumber(perf?.clicks ?? campaign.clicks)}
              sub={perf?.ctr != null ? `${formatRatioPct(perf.ctr)} CTR` : undefined}
            />
            <KpiCard
              label="Budget"
              value={formatMoneyMinor(campaign.budget_amount_minor, campaign.currency)}
              sub={campaign.budget_type ? `${titleCaseKey(campaign.budget_type)} budget` : undefined}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard label="CPC" value={formatMoneyMinor(perf?.cpc_minor, perf?.currency ?? campaign.currency)} />
            <KpiCard label="CPM" value={formatMoneyMinor(perf?.cpm_minor, perf?.currency ?? campaign.currency)} />
            <KpiCard
              label="Conversions (reported)"
              value={formatNumber(perf?.conversions_reported ?? campaign.conversions_reported)}
              sub="Provider-reported"
              iconClassName="bg-slate-100 text-slate-600"
            />
            <KpiCard
              label="Conversions (CRM-confirmed)"
              value={
                (perf?.conversions_crm_confirmed ?? campaign.conversions_crm_confirmed) == null
                  ? "n/a"
                  : formatNumber(perf?.conversions_crm_confirmed ?? campaign.conversions_crm_confirmed)
              }
              sub="Requires reconciliation"
            />
          </div>

          <PageSection
            title="Internal campaign link"
            description="Links to an internal marketing campaign for attribution. This only writes to our linkage tables — never the provider."
          >
            {campaign.linked_internal_campaign_id ? (
              <div className="card-premium flex flex-wrap items-center justify-between gap-3 p-4">
                <div className="text-sm">
                  <StatusBadge variant="info">Linked</StatusBadge>
                  <span className="ml-2 font-mono text-xs text-slate-500">
                    {campaign.linked_internal_campaign_id}
                  </span>
                </div>
                <button
                  type="button"
                  className="btn-secondary text-sm"
                  disabled={unlinkMutation.isPending}
                  onClick={() => unlinkMutation.mutate()}
                >
                  <Unlink size={14} /> Unlink
                </button>
              </div>
            ) : (
              <div className="card-premium flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
                <label className="flex-1 text-sm">
                  <span className="mb-1 block text-xs font-medium text-slate-500">
                    Internal marketing campaign ID
                  </span>
                  <input
                    type="text"
                    value={internalId}
                    onChange={(e) => setInternalId(e.target.value)}
                    placeholder="UUID of internal campaign"
                    className="input w-full"
                  />
                </label>
                <button
                  type="button"
                  className="btn-primary text-sm"
                  disabled={!internalId.trim() || linkMutation.isPending}
                  onClick={() => linkMutation.mutate()}
                >
                  <Link2 size={14} /> Link
                </button>
              </div>
            )}
          </PageSection>

          <PageSection title="Ad groups">
            {adGroupsQuery.isLoading ? (
              <LoadingState message="Loading ad groups…" variant="inline" />
            ) : adGroups.length === 0 ? (
              <EmptyState title="No ad groups" description="This campaign has no imported ad groups." />
            ) : (
              <DataTable>
                <DataTableHead>
                  <DataTableRow>
                    <DataTableTh>Ad group</DataTableTh>
                    <DataTableTh>Status</DataTableTh>
                    <DataTableTh>Delivery</DataTableTh>
                    <DataTableTh className="text-right">Spend</DataTableTh>
                    <DataTableTh className="text-right">Impressions</DataTableTh>
                    <DataTableTh className="text-right">Clicks</DataTableTh>
                  </DataTableRow>
                </DataTableHead>
                <DataTableBody>
                  {adGroups.map((group) => (
                    <DataTableRow key={group.id}>
                      <DataTableTd>
                        <Link
                          href={`/advertising/ad-groups/${group.id}`}
                          className="font-medium hover:underline"
                        >
                          {group.name}
                        </Link>
                      </DataTableTd>
                      <DataTableTd>
                        <StatusBadge variant={entityStatusVariant(group.status)}>
                          {titleCaseKey(group.status)}
                        </StatusBadge>
                      </DataTableTd>
                      <DataTableTd>{titleCaseKey(group.delivery_status)}</DataTableTd>
                      <DataTableTd className="text-right tabular-nums">
                        {formatMoneyMinor(group.spend_minor, group.currency)}
                      </DataTableTd>
                      <DataTableTd className="text-right tabular-nums">
                        {formatNumber(group.impressions)}
                      </DataTableTd>
                      <DataTableTd className="text-right tabular-nums">
                        {formatNumber(group.clicks)}
                      </DataTableTd>
                    </DataTableRow>
                  ))}
                </DataTableBody>
              </DataTable>
            )}
          </PageSection>

          {perf?.pacing ? (
            <PageSection title="Pacing">
              <div className="card-premium grid gap-4 p-4 sm:grid-cols-3">
                <div>
                  <p className="kpi-label">Status</p>
                  <StatusBadge variant={pacingVariant(perf.pacing.status)}>
                    {pacingLabel(perf.pacing.status)}
                  </StatusBadge>
                </div>
                <div>
                  <p className="kpi-label">Spend</p>
                  <p className="mt-1 font-semibold tabular-nums">
                    {formatMoneyMinor(perf.pacing.spend_minor, perf.pacing.currency)}
                  </p>
                </div>
                <div>
                  <p className="kpi-label">Utilization</p>
                  <p className="mt-1 font-semibold tabular-nums">
                    {formatRatioPct(perf.pacing.pace_ratio)}
                  </p>
                </div>
              </div>
            </PageSection>
          ) : null}
        </>
      ) : null}
    </PageShell>
  );
}
