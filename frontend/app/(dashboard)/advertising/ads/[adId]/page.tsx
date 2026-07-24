"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Image as ImageIcon, Radio } from "lucide-react";

import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  KpiCard,
  PageHeader,
  PageSection,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import { ADVERTISING_QUERY_KEY, advertisingApi, getApiErrorMessage } from "@/lib/api";
import {
  entityStatusVariant,
  fatigueLabel,
  fatigueVariant,
  formatMoneyMinor,
  formatNumber,
  freshnessVariant,
  titleCaseKey,
} from "@/lib/advertising-ui";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

export default function AdvertisingAdDetailPage() {
  const params = useParams();
  const adId = String(params.adId);

  const adQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "ad", adId],
    queryFn: () => advertisingApi.getAd(adId).then((r) => r.data),
    ...QUERY_OPTS,
  });
  const creativeQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "ad", adId, "creative"],
    queryFn: () => advertisingApi.adCreative(adId).then((r) => r.data),
    retry: false,
    ...QUERY_OPTS,
  });

  const ad = adQuery.data;
  const creative = creativeQuery.data;

  return (
    <PageShell wide>
      <PageHeader
        title={ad?.name ?? "Ad"}
        subtitle="Read-only provider ad."
        icon={Radio}
        badge={<StatusBadge variant="neutral">Read-only</StatusBadge>}
        actions={
          ad?.ad_group_id ? (
            <Link href={`/advertising/ad-groups/${ad.ad_group_id}`} className="btn-secondary text-sm">
              <ArrowLeft size={14} /> Ad group
            </Link>
          ) : (
            <Link href="/advertising/campaigns" className="btn-secondary text-sm">
              <ArrowLeft size={14} /> Campaigns
            </Link>
          )
        }
      />

      {adQuery.isLoading ? <LoadingState message="Loading ad…" /> : null}
      {adQuery.isError && !adQuery.isLoading ? (
        <ErrorState
          title="Unable to load ad"
          message={getApiErrorMessage(adQuery.error)}
          onRetry={() => adQuery.refetch()}
        />
      ) : null}

      {ad ? (
        <>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <StatusBadge variant={entityStatusVariant(ad.status)}>{titleCaseKey(ad.status)}</StatusBadge>
            <StatusBadge variant={freshnessVariant(ad.freshness_status)}>
              {titleCaseKey(ad.freshness_status)}
            </StatusBadge>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard label="Spend" value={formatMoneyMinor(ad.spend_minor, ad.currency)} />
            <KpiCard label="Impressions" value={formatNumber(ad.impressions)} />
            <KpiCard label="Clicks" value={formatNumber(ad.clicks)} />
            <KpiCard
              label="Conversions (reported)"
              value={formatNumber(ad.conversions_reported)}
              sub="Provider-reported"
            />
          </div>

          <PageSection title="Creative">
            {creative ? (
              <div className="card-premium flex flex-col gap-4 p-4 sm:flex-row">
                <div className="flex h-32 w-32 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-slate-200 bg-slate-50 dark-tenant:border-slate-800">
                  {creative.thumbnail_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={creative.thumbnail_url}
                      alt={creative.name}
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <ImageIcon size={28} className="text-slate-300" />
                  )}
                </div>
                <div className="min-w-0 flex-1 space-y-2">
                  <Link
                    href={`/advertising/creatives/${creative.id}`}
                    className="font-medium hover:underline"
                  >
                    {creative.name}
                  </Link>
                  <div className="flex flex-wrap items-center gap-2">
                    {creative.format ? (
                      <StatusBadge variant="neutral">{titleCaseKey(creative.format)}</StatusBadge>
                    ) : null}
                    <StatusBadge variant={fatigueVariant(creative.fatigue_status)}>
                      {fatigueLabel(creative.fatigue_status)}
                    </StatusBadge>
                  </div>
                  {creative.preview_url ? (
                    <a
                      href={creative.preview_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-sm text-brand-600 underline underline-offset-2"
                    >
                      Open provider preview
                    </a>
                  ) : null}
                </div>
              </div>
            ) : (
              <p className="text-sm text-slate-500 dark-tenant:text-slate-400">
                No creative linked to this ad.
              </p>
            )}
          </PageSection>
        </>
      ) : null}
    </PageShell>
  );
}
