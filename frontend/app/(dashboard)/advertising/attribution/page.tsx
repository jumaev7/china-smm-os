"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Link2 } from "lucide-react";

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
import { formatNumber, formatRatioPct, titleCaseKey } from "@/lib/advertising-ui";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

export default function AdvertisingAttributionPage() {
  const attributionQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "attribution"],
    queryFn: () => advertisingApi.attribution().then((r) => r.data),
    ...QUERY_OPTS,
  });

  const data = attributionQuery.data;

  return (
    <PageShell wide>
      <PageHeader
        title="Attribution coverage"
        subtitle="Provider-reported conversions are the provider's own attribution. CRM-confirmed conversions require reconciliation and are never inferred from provider data."
        icon={Link2}
        badge={<StatusBadge variant="neutral">Read-only</StatusBadge>}
        actions={
          <Link href="/advertising" className="btn-secondary text-sm">
            Overview
          </Link>
        }
      />

      {attributionQuery.isLoading ? <LoadingState message="Loading attribution…" /> : null}
      {attributionQuery.isError && !attributionQuery.isLoading ? (
        <ErrorState
          title="Unable to load attribution coverage"
          message={getApiErrorMessage(attributionQuery.error)}
          onRetry={() => attributionQuery.refetch()}
        />
      ) : null}

      {data ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard label="Linked campaigns" value={data.linked_campaign_count} />
            <KpiCard label="Unlinked campaigns" value={data.unlinked_campaign_count} />
            <KpiCard label="Coverage" value={formatRatioPct(data.coverage_ratio)} />
            <KpiCard
              label="Conversions (reported)"
              value={formatNumber(data.reported_conversions)}
              sub={`${formatNumber(data.crm_confirmed_conversions)} CRM-confirmed`}
            />
          </div>

          {data.note ? <p className="text-xs text-slate-500">{data.note}</p> : null}

          <PageSection title="By campaign">
            {data.by_campaign.length === 0 ? (
              <EmptyState title="No campaigns" description="Import an account to see attribution coverage." />
            ) : (
              <DataTable>
                <DataTableHead>
                  <DataTableRow>
                    <DataTableTh>Campaign</DataTableTh>
                    <DataTableTh>Provider</DataTableTh>
                    <DataTableTh>Linked</DataTableTh>
                    <DataTableTh className="text-right">Conv. (reported)</DataTableTh>
                    <DataTableTh className="text-right">Conv. (CRM-confirmed)</DataTableTh>
                  </DataTableRow>
                </DataTableHead>
                <DataTableBody>
                  {data.by_campaign.map((row) => (
                    <DataTableRow key={row.campaign_id}>
                      <DataTableTd>
                        <Link
                          href={`/advertising/campaigns/${row.campaign_id}`}
                          className="font-medium hover:underline"
                        >
                          {row.campaign_name ?? row.campaign_id}
                        </Link>
                      </DataTableTd>
                      <DataTableTd>{titleCaseKey(row.provider)}</DataTableTd>
                      <DataTableTd>
                        {row.linked_internal_campaign_id ? (
                          <StatusBadge variant="info">Linked</StatusBadge>
                        ) : (
                          <StatusBadge variant="neutral">Unlinked</StatusBadge>
                        )}
                      </DataTableTd>
                      <DataTableTd className="text-right tabular-nums">
                        {formatNumber(row.conversions_reported)}
                      </DataTableTd>
                      <DataTableTd className="text-right tabular-nums text-slate-500">
                        {row.conversions_crm_confirmed == null
                          ? "n/a"
                          : formatNumber(row.conversions_crm_confirmed)}
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
