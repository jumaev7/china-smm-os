"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Megaphone } from "lucide-react";

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
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import { ADVERTISING_QUERY_KEY, advertisingApi, getApiErrorMessage } from "@/lib/api";
import {
  ADVERTISING_LINKED_OPTIONS,
  ADVERTISING_STATUS_OPTIONS,
  entityStatusVariant,
  formatMoneyMinor,
  formatNumber,
  freshnessVariant,
  pacingLabel,
  pacingVariant,
  titleCaseKey,
} from "@/lib/advertising-ui";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

export default function AdvertisingCampaignsPage() {
  const searchParams = useSearchParams();
  const accountId = searchParams.get("account_id") ?? undefined;
  const [status, setStatus] = useState(searchParams.get("status") ?? "");
  const [linked, setLinked] = useState("");

  const linkedBool = linked === "true" ? true : linked === "false" ? false : undefined;

  const campaignsQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "campaigns", { accountId, status, linked }],
    queryFn: () =>
      advertisingApi
        .listCampaigns({
          account_id: accountId,
          status: status || undefined,
          linked: linkedBool,
          limit: 100,
        })
        .then((r) => r.data),
    ...QUERY_OPTS,
  });

  const items = campaignsQuery.data?.items ?? [];
  const total = campaignsQuery.data?.total ?? 0;

  const subtitle = useMemo(
    () =>
      accountId
        ? "Provider campaigns for the selected account. No create, edit, pause, or budget actions are available."
        : "All provider campaigns. Read-only — no create, edit, pause, or budget actions.",
    [accountId],
  );

  return (
    <PageShell wide>
      <PageHeader
        title="Campaigns"
        subtitle={subtitle}
        icon={Megaphone}
        badge={<StatusBadge variant="neutral">Read-only</StatusBadge>}
        actions={
          <div className="flex flex-wrap gap-2">
            <Link href="/advertising" className="btn-secondary text-sm">
              Overview
            </Link>
            <Link href="/advertising/accounts" className="btn-secondary text-sm">
              Accounts
            </Link>
          </div>
        }
      />

      <ActionBar>
        <div className="flex flex-wrap items-center gap-3">
          <FilterBar options={ADVERTISING_STATUS_OPTIONS} value={status} onChange={setStatus} />
          <FilterBar options={ADVERTISING_LINKED_OPTIONS} value={linked} onChange={setLinked} />
          <span className="text-xs text-slate-500">{total} campaigns</span>
        </div>
      </ActionBar>

      {campaignsQuery.isLoading ? <LoadingState message="Loading campaigns…" /> : null}

      {campaignsQuery.isError && !campaignsQuery.isLoading ? (
        <ErrorState
          title="Unable to load campaigns"
          message={getApiErrorMessage(campaignsQuery.error)}
          onRetry={() => campaignsQuery.refetch()}
        />
      ) : null}

      {!campaignsQuery.isLoading && !campaignsQuery.isError ? (
        items.length === 0 ? (
          <EmptyState
            title="No campaigns found"
            description="Import an account to mirror its provider campaigns here."
          />
        ) : (
          <DataTable>
            <DataTableHead>
              <DataTableRow>
                <DataTableTh>Campaign</DataTableTh>
                <DataTableTh>Status</DataTableTh>
                <DataTableTh className="text-right">Spend</DataTableTh>
                <DataTableTh className="text-right">Impressions</DataTableTh>
                <DataTableTh className="text-right">Clicks</DataTableTh>
                <DataTableTh className="text-right">Conv. (reported)</DataTableTh>
                <DataTableTh>Pacing</DataTableTh>
                <DataTableTh>Linked</DataTableTh>
                <DataTableTh>Freshness</DataTableTh>
              </DataTableRow>
            </DataTableHead>
            <DataTableBody>
              {items.map((campaign) => (
                <DataTableRow key={campaign.id}>
                  <DataTableTd>
                    <Link
                      href={`/advertising/campaigns/${campaign.id}`}
                      className="font-medium hover:underline"
                    >
                      {campaign.name}
                    </Link>
                    <p className="text-[11px] text-slate-500">
                      {titleCaseKey(campaign.provider)}
                      {campaign.objective ? ` · ${titleCaseKey(campaign.objective)}` : ""}
                    </p>
                  </DataTableTd>
                  <DataTableTd>
                    <StatusBadge variant={entityStatusVariant(campaign.status)}>
                      {titleCaseKey(campaign.status)}
                    </StatusBadge>
                  </DataTableTd>
                  <DataTableTd className="text-right tabular-nums">
                    {formatMoneyMinor(campaign.spend_minor, campaign.currency)}
                  </DataTableTd>
                  <DataTableTd className="text-right tabular-nums">
                    {formatNumber(campaign.impressions)}
                  </DataTableTd>
                  <DataTableTd className="text-right tabular-nums">
                    {formatNumber(campaign.clicks)}
                  </DataTableTd>
                  <DataTableTd className="text-right tabular-nums">
                    {formatNumber(campaign.conversions_reported)}
                  </DataTableTd>
                  <DataTableTd>
                    <StatusBadge variant={pacingVariant(campaign.pacing_status)}>
                      {pacingLabel(campaign.pacing_status)}
                    </StatusBadge>
                  </DataTableTd>
                  <DataTableTd>
                    {campaign.linked_internal_campaign_id ? (
                      <StatusBadge variant="info">Linked</StatusBadge>
                    ) : (
                      <StatusBadge variant="neutral">Unlinked</StatusBadge>
                    )}
                  </DataTableTd>
                  <DataTableTd>
                    <StatusBadge variant={freshnessVariant(campaign.freshness_status)}>
                      {titleCaseKey(campaign.freshness_status)}
                    </StatusBadge>
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
