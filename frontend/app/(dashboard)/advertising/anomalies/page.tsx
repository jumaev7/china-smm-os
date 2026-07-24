"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";

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
import { formatWhen, severityVariant, titleCaseKey } from "@/lib/advertising-ui";

const QUERY_OPTS = { staleTime: 30_000, refetchOnWindowFocus: false } as const;

const STATUS_OPTIONS = [
  { label: "Open", value: "open" },
  { label: "Acknowledged", value: "acknowledged" },
  { label: "Resolved", value: "resolved" },
  { label: "Dismissed", value: "dismissed" },
  { label: "All", value: "" },
];

export default function AdvertisingAnomaliesPage() {
  const [status, setStatus] = useState("open");

  const anomaliesQuery = useQuery({
    queryKey: [...ADVERTISING_QUERY_KEY, "anomalies", status],
    queryFn: () =>
      advertisingApi.anomalies({ status: status || undefined, limit: 100 }).then((r) => r.data),
    ...QUERY_OPTS,
  });

  const items = anomaliesQuery.data?.items ?? [];

  return (
    <PageShell wide>
      <PageHeader
        title="Delivery anomalies"
        subtitle="Advisory data-quality and delivery signals detected from provider reporting. Informational only — no provider actions are taken."
        icon={AlertTriangle}
        badge={<StatusBadge variant="neutral">Read-only</StatusBadge>}
        actions={
          <Link href="/advertising" className="btn-secondary text-sm">
            Overview
          </Link>
        }
      />

      <ActionBar>
        <div className="flex flex-wrap items-center gap-3">
          <FilterBar options={STATUS_OPTIONS} value={status} onChange={setStatus} />
          <span className="text-xs text-slate-500">{anomaliesQuery.data?.total ?? 0} anomalies</span>
        </div>
      </ActionBar>

      {anomaliesQuery.isLoading ? <LoadingState message="Loading anomalies…" /> : null}
      {anomaliesQuery.isError && !anomaliesQuery.isLoading ? (
        <ErrorState
          title="Unable to load anomalies"
          message={getApiErrorMessage(anomaliesQuery.error)}
          onRetry={() => anomaliesQuery.refetch()}
        />
      ) : null}

      {!anomaliesQuery.isLoading && !anomaliesQuery.isError ? (
        items.length === 0 ? (
          <EmptyState
            title="No anomalies"
            description="No delivery or data-quality anomalies match this filter."
          />
        ) : (
          <DataTable>
            <DataTableHead>
              <DataTableRow>
                <DataTableTh>Anomaly</DataTableTh>
                <DataTableTh>Severity</DataTableTh>
                <DataTableTh>Entity</DataTableTh>
                <DataTableTh>Metric</DataTableTh>
                <DataTableTh>Status</DataTableTh>
                <DataTableTh>Detected</DataTableTh>
              </DataTableRow>
            </DataTableHead>
            <DataTableBody>
              {items.map((anomaly) => (
                <DataTableRow key={anomaly.id}>
                  <DataTableTd className="font-medium">
                    {titleCaseKey(anomaly.anomaly_key)}
                  </DataTableTd>
                  <DataTableTd>
                    <StatusBadge variant={severityVariant(anomaly.severity)}>
                      {titleCaseKey(anomaly.severity)}
                    </StatusBadge>
                  </DataTableTd>
                  <DataTableTd className="text-xs text-slate-500">
                    {anomaly.entity_type ? titleCaseKey(anomaly.entity_type) : "—"}
                  </DataTableTd>
                  <DataTableTd className="text-xs text-slate-500">
                    {anomaly.metric_key ?? "—"}
                  </DataTableTd>
                  <DataTableTd>
                    <StatusBadge variant={anomaly.status === "resolved" ? "success" : "neutral"}>
                      {titleCaseKey(anomaly.status)}
                    </StatusBadge>
                  </DataTableTd>
                  <DataTableTd className="whitespace-nowrap text-xs text-slate-500">
                    {formatWhen(anomaly.created_at)}
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
