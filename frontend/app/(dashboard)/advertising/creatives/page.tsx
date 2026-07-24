"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Image as ImageIcon, Layers } from "lucide-react";

import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  ActionBar,
  FilterBar,
  PageHeader,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import { ADVERTISING_QUERY_KEY, advertisingApi, getApiErrorMessage } from "@/lib/api";
import {
  ADVERTISING_FATIGUE_OPTIONS,
  fatigueLabel,
  fatigueVariant,
  formatFrequency,
  formatMoneyMinor,
  formatNumber,
  titleCaseKey,
} from "@/lib/advertising-ui";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

export default function AdvertisingCreativesPage() {
  const searchParams = useSearchParams();
  const accountId = searchParams.get("account_id") ?? undefined;
  const [fatigue, setFatigue] = useState(searchParams.get("fatigue_status") ?? "");

  const creativesQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "creatives", { accountId, fatigue }],
    queryFn: () =>
      advertisingApi
        .listCreatives({ account_id: accountId, fatigue_status: fatigue || undefined, limit: 100 })
        .then((r) => r.data),
    ...QUERY_OPTS,
  });

  const creatives = creativesQuery.data?.items ?? [];

  return (
    <PageShell wide>
      <PageHeader
        title="Creatives"
        subtitle="Read-only provider creatives with an advisory, frequency-based fatigue signal."
        icon={Layers}
        badge={<StatusBadge variant="neutral">Read-only</StatusBadge>}
        actions={
          <Link href="/advertising" className="btn-secondary text-sm">
            Overview
          </Link>
        }
      />

      <ActionBar>
        <div className="flex flex-wrap items-center gap-3">
          <FilterBar options={ADVERTISING_FATIGUE_OPTIONS} value={fatigue} onChange={setFatigue} />
          <span className="text-xs text-slate-500">{creativesQuery.data?.total ?? 0} creatives</span>
        </div>
      </ActionBar>

      {creativesQuery.isLoading ? <LoadingState message="Loading creatives…" /> : null}
      {creativesQuery.isError && !creativesQuery.isLoading ? (
        <ErrorState
          title="Unable to load creatives"
          message={getApiErrorMessage(creativesQuery.error)}
          onRetry={() => creativesQuery.refetch()}
        />
      ) : null}

      {!creativesQuery.isLoading && !creativesQuery.isError ? (
        creatives.length === 0 ? (
          <EmptyState
            title="No creatives found"
            description="Import an account to mirror its provider creatives here."
          />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {creatives.map((creative) => (
              <Link
                key={creative.id}
                href={`/advertising/creatives/${creative.id}`}
                className="card-premium group flex flex-col overflow-hidden p-0 transition-all hover:border-brand-200/60"
              >
                <div className="flex h-36 items-center justify-center overflow-hidden bg-slate-50 dark-tenant:bg-slate-900">
                  {creative.thumbnail_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={creative.thumbnail_url}
                      alt={creative.name}
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <ImageIcon size={30} className="text-slate-300" />
                  )}
                </div>
                <div className="flex flex-1 flex-col gap-2 p-4">
                  <p className="truncate font-medium">{creative.name}</p>
                  <div className="flex flex-wrap items-center gap-2">
                    {creative.format ? (
                      <StatusBadge variant="neutral">{titleCaseKey(creative.format)}</StatusBadge>
                    ) : null}
                    <StatusBadge variant={fatigueVariant(creative.fatigue_status)}>
                      {fatigueLabel(creative.fatigue_status)}
                    </StatusBadge>
                    {creative.linked_content_id ? (
                      <StatusBadge variant="info">Linked</StatusBadge>
                    ) : null}
                  </div>
                  <div className="mt-auto grid grid-cols-3 gap-1 text-xs text-slate-500">
                    <span title="Spend">{formatMoneyMinor(creative.spend_minor, creative.currency)}</span>
                    <span title="Impressions">{formatNumber(creative.impressions)} impr</span>
                    <span title="Frequency">{formatFrequency(creative.frequency)}</span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )
      ) : null}
    </PageShell>
  );
}
