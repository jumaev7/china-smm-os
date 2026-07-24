"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { Building2, DownloadCloud, Plus, RefreshCw } from "lucide-react";

import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import {
  DataTable,
  DataTableBody,
  DataTableHead,
  DataTableRow,
  DataTableTd,
  DataTableTh,
  PageHeader,
  PageSection,
  PageShell,
  StatusBadge,
} from "@/components/ui/design-system";
import { ADVERTISING_QUERY_KEY, advertisingApi, getApiErrorMessage } from "@/lib/api";
import {
  connectionVariant,
  formatWhen,
  freshnessVariant,
  titleCaseKey,
} from "@/lib/advertising-ui";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

export default function AdvertisingAccountsPage() {
  const queryClient = useQueryClient();
  const [showRegister, setShowRegister] = useState(false);
  const [mockName, setMockName] = useState("");
  const [mockCurrency, setMockCurrency] = useState("USD");

  const accountsQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "accounts"],
    queryFn: () => advertisingApi.listAccounts({ limit: 100 }).then((r) => r.data),
    ...QUERY_OPTS,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: [...ADVERTISING_QUERY_KEY, "accounts"] });

  const registerMutation = useMutation({
    mutationFn: () =>
      advertisingApi
        .registerMockAccount({ name: mockName.trim(), currency: mockCurrency.trim().toUpperCase() })
        .then((r) => r.data),
    onSuccess: () => {
      toast.success("Mock account registered");
      setShowRegister(false);
      setMockName("");
      invalidate();
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const importMutation = useMutation({
    mutationFn: (accountId: string) => advertisingApi.importAccount(accountId).then((r) => r.data),
    onSuccess: (run) => {
      toast.success(`Import ${run.status}`);
      invalidate();
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const refreshMutation = useMutation({
    mutationFn: (accountId: string) =>
      advertisingApi.refreshAccountMetrics(accountId).then((r) => r.data),
    onSuccess: (run) => {
      toast.success(`Metrics refresh ${run.status}`);
      invalidate();
    },
    onError: (err) => toast.error(getApiErrorMessage(err)),
  });

  const accounts = accountsQuery.data?.items ?? [];

  return (
    <PageShell wide>
      <PageHeader
        title="Advertising accounts"
        subtitle="Connected provider ad accounts. Metric imports read from the provider only — provider state is never modified."
        icon={Building2}
        badge={<StatusBadge variant="neutral">Read-only</StatusBadge>}
        actions={
          <div className="flex flex-wrap gap-2">
            <Link href="/advertising" className="btn-secondary text-sm">
              Overview
            </Link>
            <Link href="/integrations" className="btn-secondary text-sm">
              Reconnect (Integrations)
            </Link>
            <button
              type="button"
              className="btn-primary text-sm"
              onClick={() => setShowRegister((v) => !v)}
            >
              <Plus size={14} /> Register mock account
            </button>
          </div>
        }
      />

      {showRegister ? (
        <PageSection title="Register mock account (local/dev)">
          <div className="card-premium p-4 flex flex-col gap-3 sm:flex-row sm:items-end">
            <label className="flex-1 text-sm">
              <span className="mb-1 block text-xs font-medium text-slate-500">Name</span>
              <input
                type="text"
                value={mockName}
                onChange={(e) => setMockName(e.target.value)}
                placeholder="Demo Ad Account"
                className="input w-full"
              />
            </label>
            <label className="w-32 text-sm">
              <span className="mb-1 block text-xs font-medium text-slate-500">Currency</span>
              <input
                type="text"
                value={mockCurrency}
                onChange={(e) => setMockCurrency(e.target.value.toUpperCase())}
                maxLength={3}
                className="input w-full uppercase"
              />
            </label>
            <button
              type="button"
              className="btn-primary text-sm"
              disabled={!mockName.trim() || mockCurrency.trim().length !== 3 || registerMutation.isPending}
              onClick={() => registerMutation.mutate()}
            >
              {registerMutation.isPending ? "Registering…" : "Register"}
            </button>
          </div>
          <p className="mt-2 text-xs text-slate-500">
            Mock accounts are for local/development only and never contact a live provider. Live
            providers connect through Integrations.
          </p>
        </PageSection>
      ) : null}

      {accountsQuery.isLoading ? <LoadingState message="Loading accounts…" /> : null}

      {accountsQuery.isError && !accountsQuery.isLoading ? (
        <ErrorState
          title="Unable to load accounts"
          message={getApiErrorMessage(accountsQuery.error)}
          onRetry={() => accountsQuery.refetch()}
        />
      ) : null}

      {!accountsQuery.isLoading && !accountsQuery.isError ? (
        accounts.length === 0 ? (
          <EmptyState
            title="No advertising accounts"
            description="Connect a provider via Integrations, or register a mock account for local testing."
          />
        ) : (
          <DataTable>
            <DataTableHead>
              <DataTableRow>
                <DataTableTh>Account</DataTableTh>
                <DataTableTh>Provider</DataTableTh>
                <DataTableTh>Connection</DataTableTh>
                <DataTableTh>Currency</DataTableTh>
                <DataTableTh>Freshness</DataTableTh>
                <DataTableTh>Last refresh</DataTableTh>
                <DataTableTh className="text-right">Actions</DataTableTh>
              </DataTableRow>
            </DataTableHead>
            <DataTableBody>
              {accounts.map((account) => (
                <DataTableRow key={account.id}>
                  <DataTableTd>
                    <div className="flex items-center gap-2">
                      <Link
                        href={`/advertising/campaigns?account_id=${account.id}`}
                        className="font-medium hover:underline"
                      >
                        {account.name}
                      </Link>
                      {account.is_mock ? (
                        <StatusBadge variant="neutral">Mock</StatusBadge>
                      ) : null}
                    </div>
                    {account.external_account_id ? (
                      <p className="text-[11px] text-slate-500">{account.external_account_id}</p>
                    ) : null}
                  </DataTableTd>
                  <DataTableTd>{titleCaseKey(account.provider)}</DataTableTd>
                  <DataTableTd>
                    <StatusBadge variant={connectionVariant(account.status)}>
                      {titleCaseKey(account.status)}
                    </StatusBadge>
                  </DataTableTd>
                  <DataTableTd>{account.currency ?? "—"}</DataTableTd>
                  <DataTableTd>
                    <StatusBadge variant={freshnessVariant(account.freshness_status)}>
                      {titleCaseKey(account.freshness_status)}
                    </StatusBadge>
                  </DataTableTd>
                  <DataTableTd className="whitespace-nowrap text-xs text-slate-500">
                    {formatWhen(account.last_metric_refresh_at)}
                  </DataTableTd>
                  <DataTableTd className="text-right">
                    <div className="flex justify-end gap-2">
                      <button
                        type="button"
                        className="btn-secondary text-xs"
                        disabled={importMutation.isPending}
                        onClick={() => importMutation.mutate(account.id)}
                        title="Import campaigns / ad groups / ads (reads provider only)"
                      >
                        <DownloadCloud size={13} /> Import
                      </button>
                      <button
                        type="button"
                        className="btn-secondary text-xs"
                        disabled={refreshMutation.isPending}
                        onClick={() => refreshMutation.mutate(account.id)}
                        title="Refresh provider-reported metrics"
                      >
                        <RefreshCw size={13} /> Refresh
                      </button>
                    </div>
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
