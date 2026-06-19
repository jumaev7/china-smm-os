"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Briefcase, ChevronRight, Contact, Loader2 } from "lucide-react";
import { clientsApi, crmApi, dealRiskApi, Client, CrmDeal, DealRiskLevel, DealStatus, normalizeList } from "@/lib/api";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

const DEAL_STATUS_STYLE: Record<DealStatus, string> = {
  new: "bg-gray-100 text-gray-700 border-gray-200",
  proposal: "bg-sky-100 text-sky-800 border-sky-200",
  contract: "bg-violet-100 text-violet-800 border-violet-200",
  invoice: "bg-amber-100 text-amber-800 border-amber-200",
  waiting_payment: "bg-orange-100 text-orange-800 border-orange-200",
  won: "bg-emerald-100 text-emerald-800 border-emerald-200",
  lost: "bg-red-100 text-red-800 border-red-200",
};

function formatValue(val: number | string | null | undefined): string {
  if (val == null || val === "") return "—";
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(n)) return String(val);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

const DEAL_RISK_STYLES: Record<DealRiskLevel, string> = {
  healthy: "bg-emerald-50 border-emerald-200 text-emerald-800",
  watchlist: "bg-amber-50 border-amber-200 text-amber-800",
  at_risk: "bg-orange-50 border-orange-200 text-orange-800",
  critical: "bg-red-50 border-red-300 text-red-900",
  stalled: "bg-gray-50 border-gray-200 text-gray-700",
  lost_probability_high: "bg-red-100 border-red-400 text-red-950",
};

function DealRow({
  deal,
  healthScore,
  riskLevel,
}: {
  deal: CrmDeal;
  healthScore?: number | null;
  riskLevel?: DealRiskLevel | null;
}) {
  return (
    <Link
      href={`/crm/deals/${deal.id}`}
      className="card p-4 flex items-center justify-between gap-3 hover:ring-1 hover:ring-brand-200 transition-shadow"
    >
      <div className="min-w-0">
        <p className="text-sm font-semibold text-gray-900 truncate">{deal.title}</p>
        <p className="text-xs text-gray-500 mt-0.5">
          {deal.lead_name ?? "Lead"} · {deal.client_name ?? "Client"}
        </p>
        <div className="flex flex-wrap items-center gap-2 mt-2 text-[11px] text-gray-500">
          <span>{deal.probability}% probability</span>
          <span>·</span>
          <span>{formatValue(deal.expected_value)} UZS</span>
          <span>·</span>
          <span>{deal.days_in_pipeline}d in pipeline</span>
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {healthScore != null && (
          <span className="text-[10px] px-2 py-0.5 rounded-full border bg-orange-50 border-orange-200 text-orange-900 font-semibold tabular-nums">
            {healthScore}
          </span>
        )}
        {riskLevel && (
          <span
            className={cn(
              "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
              DEAL_RISK_STYLES[riskLevel],
            )}
          >
            {riskLevel.replace(/_/g, " ")}
          </span>
        )}
        <span
          className={cn(
            "text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize",
            DEAL_STATUS_STYLE[deal.status],
          )}
        >
          {deal.status.replace("_", " ")}
        </span>
        <ChevronRight size={16} className="text-gray-400" />
      </div>
    </Link>
  );
}

export default function DealsListPage() {
  const [clientId, setClientId] = useState("");
  const [statusFilter, setStatusFilter] = useState<DealStatus | "">("");

  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list().then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clients);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["crm-deals", clientId, statusFilter],
    queryFn: () =>
      crmApi
        .listDeals({
          client_id: clientId || undefined,
          status: statusFilter || undefined,
        })
        .then((r) => r.data),
  });

  const { data: dealRiskData } = useQuery({
    queryKey: ["deal-risk-crm-deals", clientId],
    queryFn: () =>
      dealRiskApi.deals({ client_id: clientId || undefined, limit: 500 }).then((r) => r.data),
    staleTime: 60_000,
  });

  const dealRiskMap = useMemo(() => {
    const map = new Map<string, { health: number; risk: DealRiskLevel }>();
    for (const item of dealRiskData?.items ?? []) {
      map.set(item.deal_id, { health: item.deal_health_score, risk: item.risk_level });
    }
    return map;
  }, [dealRiskData?.items]);

  const deals = normalizeList<CrmDeal>(data);

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Briefcase size={20} className="text-violet-600" />
            Deal Room
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Central workspace for sales opportunities — {data?.total ?? 0} deals
          </p>
        </div>
        <Link
          href="/crm"
          className="text-sm text-brand-700 hover:text-brand-900 flex items-center gap-1"
        >
          <Contact size={14} />
          Back to CRM
        </Link>
      </div>

      <div className="flex flex-wrap gap-2 mb-4">
        <select
          className="input text-sm w-44"
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
        >
          <option value="">All clients</option>
          {clientOptions.map((c) => (
            <option key={c.id} value={c.id}>
              {c.company_name}
            </option>
          ))}
        </select>
        <select
          className="input text-sm w-40"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as DealStatus | "")}
        >
          <option value="">All statuses</option>
          {(Object.keys(DEAL_STATUS_STYLE) as DealStatus[]).map((s) => (
            <option key={s} value={s}>
              {s.replace("_", " ")}
            </option>
          ))}
        </select>
      </div>

      {isLoading && <LoadingState message="Loading deals…" />}

      {isError && (
        <ErrorState
          message={error instanceof Error ? error.message : "Failed to load deals"}
          onRetry={() => refetch()}
        />
      )}

      {!isLoading && !isError && deals.length === 0 && (
        <EmptyState
          title="No deals yet"
          description="Open a lead in CRM to start a deal workspace."
        />
      )}

      <div className="space-y-2">
        {deals.map((deal) => (
          <DealRow
            key={deal.id}
            deal={deal}
            healthScore={dealRiskMap.get(deal.id)?.health}
            riskLevel={dealRiskMap.get(deal.id)?.risk}
          />
        ))}
      </div>
    </div>
  );
}
