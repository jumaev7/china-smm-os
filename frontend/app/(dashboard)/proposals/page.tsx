"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Copy, FileSignature, Loader2, Plus, Search, Trash2 } from "lucide-react";
import toast from "react-hot-toast";
import {
  normalizeList,
  salesCrmApi,
  salesProposalsApi,
  type SalesProposal,
  type SalesProposalStatus,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

const STATUSES: SalesProposalStatus[] = ["draft", "sent", "viewed", "accepted", "rejected", "expired"];

const STATUS_STYLE: Record<SalesProposalStatus, string> = {
  draft: "bg-gray-100 text-gray-700",
  sent: "bg-violet-100 text-violet-800",
  viewed: "bg-sky-100 text-sky-800",
  accepted: "bg-emerald-100 text-emerald-800",
  rejected: "bg-red-100 text-red-800",
  expired: "bg-amber-100 text-amber-800",
};

function formatMoney(amount: number, currency: string) {
  return new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 2 }).format(amount);
}

export default function ProposalsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<SalesProposalStatus | "">("");
  const [customerFilter, setCustomerFilter] = useState("");
  const [dealFilter, setDealFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const params = useMemo(
    () => ({
      search: search.trim() || undefined,
      status: statusFilter || undefined,
      customer_id: customerFilter || undefined,
      deal_id: dealFilter || undefined,
      date_from: dateFrom ? new Date(dateFrom).toISOString() : undefined,
      date_to: dateTo ? new Date(`${dateTo}T23:59:59`).toISOString() : undefined,
      limit: 100,
    }),
    [search, statusFilter, customerFilter, dealFilter, dateFrom, dateTo],
  );

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sales-proposals", params],
    queryFn: () => salesProposalsApi.list(params).then((r) => r.data),
  });

  const { data: customersData } = useQuery({
    queryKey: ["sales-crm", "customers", "proposals-filter"],
    queryFn: () => salesCrmApi.listCustomers({ limit: 200 }).then((r) => r.data),
  });

  const { data: dealsData } = useQuery({
    queryKey: ["sales-crm", "deals", "proposals-filter"],
    queryFn: () => salesCrmApi.listDeals({ limit: 200 }).then((r) => r.data),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => salesProposalsApi.delete(id),
    onSuccess: () => {
      toast.success(t("commercialProposals.deleted"));
      qc.invalidateQueries({ queryKey: ["sales-proposals"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const duplicateMutation = useMutation({
    mutationFn: (id: string) => salesProposalsApi.duplicate(id).then((r) => r.data),
    onSuccess: (p) => {
      toast.success(t("commercialProposals.duplicated"));
      qc.invalidateQueries({ queryKey: ["sales-proposals"] });
      window.location.href = `/proposals/${p.id}`;
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const items = normalizeList(data) as SalesProposal[];
  const customers = normalizeList(customersData);
  const deals = normalizeList(dealsData);

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <FileSignature size={22} className="text-brand-600" />
            {t("commercialProposals.title")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t("commercialProposals.subtitle")}</p>
        </div>
        <Link href="/proposals/new" className="btn-primary text-sm flex items-center gap-1.5">
          <Plus size={15} />
          {t("commercialProposals.create")}
        </Link>
      </div>

      <div className="card p-4 flex flex-wrap gap-3 items-end">
        <div className="flex-1 min-w-[200px]">
          <label className="text-xs text-gray-500 block mb-1">{t("commercialProposals.search")}</label>
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              className="input pl-9 w-full"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("commercialProposals.searchPlaceholder")}
            />
          </div>
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">{t("commercialProposals.status")}</label>
          <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as SalesProposalStatus | "")}>
            <option value="">{t("commercialProposals.all")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{t(`commercialProposals.statuses.${s}`)}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">{t("commercialProposals.customer")}</label>
          <select className="input" value={customerFilter} onChange={(e) => setCustomerFilter(e.target.value)}>
            <option value="">{t("commercialProposals.all")}</option>
            {customers.map((c) => (
              <option key={c.id} value={c.id}>{c.name}{c.company ? ` — ${c.company}` : ""}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">{t("commercialProposals.deal")}</label>
          <select className="input" value={dealFilter} onChange={(e) => setDealFilter(e.target.value)}>
            <option value="">{t("commercialProposals.all")}</option>
            {deals.map((d) => (
              <option key={d.id} value={d.id}>{d.title}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">{t("commercialProposals.dateFrom")}</label>
          <input type="date" className="input" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">{t("commercialProposals.dateTo")}</label>
          <input type="date" className="input" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </div>
      </div>

      {isLoading ? (
        <LoadingState message={t("commercialProposals.loading")} />
      ) : isError ? (
        <ErrorState
          message={error instanceof Error ? error.message : t("commercialProposals.loadError")}
          onRetry={() => refetch()}
        />
      ) : items.length === 0 ? (
        <EmptyState
          title={t("commercialProposals.emptyTitle")}
          description={t("commercialProposals.emptyDescription")}
          action={
            <Link href="/proposals/new" className="btn-primary text-sm">{t("commercialProposals.create")}</Link>
          }
        />
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm table-premium">
            <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
              <tr>
                <th className="text-left px-4 py-2">{t("commercialProposals.colNumber")}</th>
                <th className="text-left px-4 py-2">{t("commercialProposals.colTitle")}</th>
                <th className="text-left px-4 py-2">{t("commercialProposals.customer")}</th>
                <th className="text-left px-4 py-2">{t("commercialProposals.colTotal")}</th>
                <th className="text-left px-4 py-2">{t("commercialProposals.status")}</th>
                <th className="text-left px-4 py-2">{t("commercialProposals.colIssueDate")}</th>
                <th className="text-right px-4 py-2">{t("commercialProposals.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} className="border-b border-gray-50 hover:bg-gray-50/50">
                  <td className="px-4 py-3 text-xs font-mono text-gray-500">{p.proposal_number}</td>
                  <td className="px-4 py-3">
                    <Link href={`/proposals/${p.id}`} className="font-medium text-brand-800 hover:underline">
                      {p.title}
                    </Link>
                    {(p.lead_name || p.deal_title) && (
                      <p className="text-xs text-gray-400 mt-0.5">
                        {[p.lead_name, p.deal_title].filter(Boolean).join(" · ")}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-600">{p.customer_name ?? "—"}</td>
                  <td className="px-4 py-3 font-medium">{formatMoney(p.total, p.currency)}</td>
                  <td className="px-4 py-3">
                    <span className={cn("text-[10px] px-2 py-0.5 rounded-full capitalize", STATUS_STYLE[p.status])}>
                      {t(`commercialProposals.statuses.${p.status}`)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
                    {format(parseISO(p.issue_date), "MMM d, yyyy")}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        type="button"
                        title={t("commercialProposals.duplicate")}
                        disabled={duplicateMutation.isPending}
                        onClick={() => duplicateMutation.mutate(p.id)}
                        className="p-1.5 text-gray-400 hover:text-brand-700 rounded"
                      >
                        {duplicateMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Copy size={14} />}
                      </button>
                      <button
                        type="button"
                        title={t("commercialProposals.delete")}
                        disabled={deleteMutation.isPending}
                        onClick={() => {
                          if (window.confirm(t("commercialProposals.deleteConfirm"))) {
                            deleteMutation.mutate(p.id);
                          }
                        }}
                        className="p-1.5 text-gray-400 hover:text-red-600 rounded"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
