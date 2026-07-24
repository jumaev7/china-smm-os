"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Layers } from "lucide-react";

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
  deliveryVariant,
  entityStatusVariant,
  formatMoneyMinor,
  formatNumber,
  freshnessVariant,
  titleCaseKey,
} from "@/lib/advertising-ui";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

export default function AdvertisingAdGroupDetailPage() {
  const params = useParams();
  const adGroupId = String(params.adGroupId);

  const groupQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "ad-group", adGroupId],
    queryFn: () => advertisingApi.getAdGroup(adGroupId).then((r) => r.data),
    ...QUERY_OPTS,
  });
  const deliveryQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "ad-group", adGroupId, "delivery"],
    queryFn: () => advertisingApi.adGroupDelivery(adGroupId).then((r) => r.data),
    ...QUERY_OPTS,
  });
  const adsQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "ad-group", adGroupId, "ads"],
    queryFn: () => advertisingApi.adGroupAds(adGroupId, { limit: 100 }).then((r) => r.data),
    ...QUERY_OPTS,
  });

  const group = groupQuery.data;
  const delivery = deliveryQuery.data;
  const ads = adsQuery.data?.items ?? [];

  return (
    <PageShell wide>
      <PageHeader
        title={group?.name ?? "Ad group"}
        subtitle="Read-only provider ad group and its ads."
        icon={Layers}
        badge={<StatusBadge variant="neutral">Read-only</StatusBadge>}
        actions={
          group?.campaign_id ? (
            <Link href={`/advertising/campaigns/${group.campaign_id}`} className="btn-secondary text-sm">
              <ArrowLeft size={14} /> Campaign
            </Link>
          ) : (
            <Link href="/advertising/campaigns" className="btn-secondary text-sm">
              <ArrowLeft size={14} /> Campaigns
            </Link>
          )
        }
      />

      {groupQuery.isLoading ? <LoadingState message="Loading ad group…" /> : null}
      {groupQuery.isError && !groupQuery.isLoading ? (
        <ErrorState
          title="Unable to load ad group"
          message={getApiErrorMessage(groupQuery.error)}
          onRetry={() => groupQuery.refetch()}
        />
      ) : null}

      {group ? (
        <>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <StatusBadge variant={entityStatusVariant(group.status)}>
              {titleCaseKey(group.status)}
            </StatusBadge>
            <StatusBadge variant={deliveryVariant(group.delivery_status)}>
              {titleCaseKey(group.delivery_status)}
            </StatusBadge>
            <StatusBadge variant={freshnessVariant(group.freshness_status)}>
              {titleCaseKey(group.freshness_status)}
            </StatusBadge>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard label="Spend" value={formatMoneyMinor(group.spend_minor, group.currency)} />
            <KpiCard label="Impressions" value={formatNumber(group.impressions)} />
            <KpiCard label="Clicks" value={formatNumber(group.clicks)} />
            <KpiCard
              label="Conversions (reported)"
              value={formatNumber(group.conversions_reported)}
              sub="Provider-reported"
            />
          </div>

          {delivery && delivery.reasons && delivery.reasons.length > 0 ? (
            <PageSection title="Delivery diagnostics">
              <div className="flex flex-wrap gap-2">
                {delivery.reasons.map((reason) => (
                  <StatusBadge key={reason} variant="warning">
                    {titleCaseKey(reason)}
                  </StatusBadge>
                ))}
              </div>
            </PageSection>
          ) : null}

          <PageSection title="Ads">
            {adsQuery.isLoading ? (
              <LoadingState message="Loading ads…" variant="inline" />
            ) : ads.length === 0 ? (
              <EmptyState title="No ads" description="This ad group has no imported ads." />
            ) : (
              <DataTable>
                <DataTableHead>
                  <DataTableRow>
                    <DataTableTh>Ad</DataTableTh>
                    <DataTableTh>Status</DataTableTh>
                    <DataTableTh className="text-right">Spend</DataTableTh>
                    <DataTableTh className="text-right">Impressions</DataTableTh>
                    <DataTableTh className="text-right">Clicks</DataTableTh>
                  </DataTableRow>
                </DataTableHead>
                <DataTableBody>
                  {ads.map((ad) => (
                    <DataTableRow key={ad.id}>
                      <DataTableTd>
                        <Link href={`/advertising/ads/${ad.id}`} className="font-medium hover:underline">
                          {ad.name}
                        </Link>
                      </DataTableTd>
                      <DataTableTd>
                        <StatusBadge variant={entityStatusVariant(ad.status)}>
                          {titleCaseKey(ad.status)}
                        </StatusBadge>
                      </DataTableTd>
                      <DataTableTd className="text-right tabular-nums">
                        {formatMoneyMinor(ad.spend_minor, ad.currency)}
                      </DataTableTd>
                      <DataTableTd className="text-right tabular-nums">
                        {formatNumber(ad.impressions)}
                      </DataTableTd>
                      <DataTableTd className="text-right tabular-nums">
                        {formatNumber(ad.clicks)}
                      </DataTableTd>
                    </DataTableRow>
                  ))}
                </DataTableBody>
              </DataTable>
            )}
          </PageSection>
        </>
      ) : null}
    </PageShell>
  );
}
