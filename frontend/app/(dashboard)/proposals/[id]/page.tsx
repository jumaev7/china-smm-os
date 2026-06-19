"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import {
  ArrowLeft,
  CheckCircle2,
  Circle,
  Copy,
  Loader2,
  Pencil,
  Printer,
  Trash2,
  X,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  salesProposalsApi,
  type SalesProposalStatus,
} from "@/lib/api";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import { RelatedEntitiesPanel } from "@/components/platform/RelatedEntitiesPanel";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";

const WORKFLOW: SalesProposalStatus[] = ["draft", "sent", "viewed", "accepted", "rejected", "expired"];

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

function workflowIndex(status: SalesProposalStatus): number {
  if (status === "rejected" || status === "expired") {
    return WORKFLOW.indexOf(status);
  }
  return WORKFLOW.indexOf(status);
}

export default function ProposalDetailPage() {
  const { t } = useTranslation();
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const qc = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editNotes, setEditNotes] = useState("");
  const [editTerms, setEditTerms] = useState("");

  const { data: proposal, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sales-proposal", id],
    queryFn: () => salesProposalsApi.get(id).then((r) => r.data),
  });

  const statusMutation = useMutation({
    mutationFn: (status: SalesProposalStatus) =>
      salesProposalsApi.updateStatus(id, status).then((r) => r.data),
    onSuccess: () => {
      toast.success(t("commercialProposals.statusUpdated"));
      qc.invalidateQueries({ queryKey: ["sales-proposal", id] });
      qc.invalidateQueries({ queryKey: ["sales-proposals"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const duplicateMutation = useMutation({
    mutationFn: () => salesProposalsApi.duplicate(id).then((r) => r.data),
    onSuccess: (p) => {
      toast.success(t("commercialProposals.duplicated"));
      router.push(`/proposals/${p.id}`);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const deleteMutation = useMutation({
    mutationFn: () => salesProposalsApi.delete(id),
    onSuccess: () => {
      toast.success(t("commercialProposals.deleted"));
      router.push("/proposals");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const updateMutation = useMutation({
    mutationFn: () =>
      salesProposalsApi.update(id, {
        title: editTitle.trim(),
        notes: editNotes.trim() || null,
        terms: editTerms.trim() || null,
      }).then((r) => r.data),
    onSuccess: () => {
      toast.success(t("commercialProposals.updated"));
      setEditOpen(false);
      qc.invalidateQueries({ queryKey: ["sales-proposal", id] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const timeline = useMemo(() => {
    if (!proposal?.status_history?.length) return [];
    return [...proposal.status_history].sort(
      (a, b) => new Date(a.at).getTime() - new Date(b.at).getTime(),
    );
  }, [proposal]);

  if (isLoading) return <LoadingState message={t("commercialProposals.loading")} className="min-h-[50vh]" />;
  if (isError || !proposal) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : t("commercialProposals.loadError")}
        onRetry={() => refetch()}
      />
    );
  }

  const p = proposal;
  const currentStep = workflowIndex(p.status);

  function openEdit() {
    setEditTitle(p.title);
    setEditNotes(p.notes ?? "");
    setEditTerms(p.terms ?? "");
    setEditOpen(true);
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link href="/proposals" className="text-xs text-gray-500 hover:text-gray-800 flex items-center gap-1 mb-2">
            <ArrowLeft size={12} />
            {t("commercialProposals.backToList")}
          </Link>
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="page-title">{p.title}</h1>
            <span className={cn("text-xs px-2 py-0.5 rounded-full", STATUS_STYLE[p.status])}>
              {t(`commercialProposals.statuses.${p.status}`)}
            </span>
          </div>
          <p className="text-sm text-gray-500 mt-1 font-mono">{p.proposal_number}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href={`/proposals/${id}/print`} target="_blank" className="btn-secondary text-sm flex items-center gap-1.5">
            <Printer size={14} />
            {t("commercialProposals.print")}
          </Link>
          <button type="button" onClick={openEdit} className="btn-secondary text-sm flex items-center gap-1.5">
            <Pencil size={14} />
            {t("commercialProposals.edit")}
          </button>
          <button
            type="button"
            disabled={duplicateMutation.isPending}
            onClick={() => duplicateMutation.mutate()}
            className="btn-secondary text-sm flex items-center gap-1.5"
          >
            {duplicateMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Copy size={14} />}
            {t("commercialProposals.duplicate")}
          </button>
          <button
            type="button"
            disabled={deleteMutation.isPending}
            onClick={() => {
              if (window.confirm(t("commercialProposals.deleteConfirm"))) deleteMutation.mutate();
            }}
            className="btn-secondary text-sm text-red-600 flex items-center gap-1.5"
          >
            <Trash2 size={14} />
            {t("commercialProposals.delete")}
          </button>
        </div>
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        <div className="lg:col-span-2 space-y-5">
          {/* Preview */}
          <div className="card p-6 space-y-5" id="proposal-preview">
            <div className="flex justify-between items-start border-b border-gray-100 pb-4">
              <div>
                <p className="text-xs text-gray-400 uppercase tracking-wide">{t("commercialProposals.commercialProposal")}</p>
                <p className="text-lg font-semibold mt-1">{p.title}</p>
                <p className="text-xs text-gray-500 font-mono mt-0.5">{p.proposal_number}</p>
              </div>
              <div className="text-right text-xs text-gray-500 space-y-0.5">
                <p>{t("commercialProposals.issueDate")}: {format(parseISO(p.issue_date), "MMM d, yyyy")}</p>
                {p.valid_until && (
                  <p>{t("commercialProposals.validUntil")}: {format(parseISO(p.valid_until), "MMM d, yyyy")}</p>
                )}
              </div>
            </div>

            {p.customer_name && (
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase">{t("commercialProposals.customer")}</p>
                <p className="text-sm font-medium mt-0.5">{p.customer_name}</p>
              </div>
            )}

            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-400 border-b border-gray-100">
                  <th className="pb-2 font-medium">{t("commercialProposals.itemName")}</th>
                  <th className="pb-2 font-medium text-right">{t("commercialProposals.quantity")}</th>
                  <th className="pb-2 font-medium text-right">{t("commercialProposals.unitPrice")}</th>
                  <th className="pb-2 font-medium text-right">{t("commercialProposals.itemDiscount")}</th>
                  <th className="pb-2 font-medium text-right">{t("commercialProposals.itemTotal")}</th>
                </tr>
              </thead>
              <tbody>
                {p.items.map((item) => (
                  <tr key={item.id} className="border-b border-gray-50">
                    <td className="py-2.5">
                      <p className="font-medium text-gray-900">{item.product_or_service_name}</p>
                      {item.description && <p className="text-xs text-gray-400 mt-0.5">{item.description}</p>}
                    </td>
                    <td className="py-2.5 text-right text-gray-600">{item.quantity}</td>
                    <td className="py-2.5 text-right text-gray-600">{formatMoney(item.unit_price, p.currency)}</td>
                    <td className="py-2.5 text-right text-gray-600">{item.discount > 0 ? formatMoney(item.discount, p.currency) : "—"}</td>
                    <td className="py-2.5 text-right font-medium">{formatMoney(item.total, p.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="flex justify-end">
              <div className="w-64 space-y-1 text-sm">
                <div className="flex justify-between text-gray-600">
                  <span>{t("commercialProposals.subtotal")}</span>
                  <span>{formatMoney(p.subtotal, p.currency)}</span>
                </div>
                {p.discount > 0 && (
                  <div className="flex justify-between text-gray-500">
                    <span>{t("commercialProposals.proposalDiscount")}</span>
                    <span>-{formatMoney(p.discount, p.currency)}</span>
                  </div>
                )}
                {p.tax > 0 && (
                  <div className="flex justify-between text-gray-500">
                    <span>{t("commercialProposals.tax")}</span>
                    <span>+{formatMoney(p.tax, p.currency)}</span>
                  </div>
                )}
                <div className="flex justify-between font-semibold text-base pt-2 border-t border-gray-200">
                  <span>{t("commercialProposals.total")}</span>
                  <span>{formatMoney(p.total, p.currency)}</span>
                </div>
              </div>
            </div>

            {p.notes && (
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase">{t("commercialProposals.notes")}</p>
                <p className="text-sm text-gray-700 mt-1 whitespace-pre-wrap">{p.notes}</p>
              </div>
            )}
            {p.terms && (
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase">{t("commercialProposals.terms")}</p>
                <p className="text-sm text-gray-700 mt-1 whitespace-pre-wrap">{p.terms}</p>
              </div>
            )}
          </div>
        </div>

        <div className="space-y-5">
          {/* Linked entities */}
          <div className="card p-4 space-y-3">
            <h2 className="text-sm font-semibold text-gray-900">{t("commercialProposals.linkedEntities")}</h2>
            {p.customer_name && (
              <div className="text-sm">
                <span className="text-gray-500">{t("commercialProposals.customer")}: </span>
                {p.customer_id ? (
                  <Link href={`/customers`} className="text-brand-700 hover:underline">{p.customer_name}</Link>
                ) : p.customer_name}
              </div>
            )}
            {p.lead_name && (
              <div className="text-sm">
                <span className="text-gray-500">{t("commercialProposals.linkedLead")}: </span>
                {p.lead_id ? (
                  <Link href={`/leads`} className="text-brand-700 hover:underline">{p.lead_name}</Link>
                ) : p.lead_name}
              </div>
            )}
            {p.deal_title && (
              <div className="text-sm">
                <span className="text-gray-500">{t("commercialProposals.linkedDeal")}: </span>
                {p.deal_id ? (
                  <Link href={`/deals`} className="text-brand-700 hover:underline">{p.deal_title}</Link>
                ) : p.deal_title}
              </div>
            )}
            {!p.customer_name && !p.lead_name && !p.deal_title && (
              <p className="text-xs text-gray-400">{t("commercialProposals.noLinks")}</p>
            )}
          </div>

          {/* Status timeline */}
          <div className="card p-4 space-y-3">
            <h2 className="text-sm font-semibold text-gray-900">{t("commercialProposals.statusTimeline")}</h2>
            <div className="space-y-2">
              {WORKFLOW.filter((s) => s !== "expired" || p.status === "expired").slice(0, 5).map((step, idx) => {
                const reached = p.status === "rejected"
                  ? idx <= 2 || step === "rejected"
                  : p.status === "expired"
                    ? idx <= WORKFLOW.indexOf("sent")
                    : idx <= currentStep;
                const isCurrent = step === p.status;
                return (
                  <div key={step} className="flex items-center gap-2 text-sm">
                    {reached ? (
                      isCurrent ? <CheckCircle2 size={16} className="text-brand-600 shrink-0" /> : <CheckCircle2 size={16} className="text-emerald-500 shrink-0" />
                    ) : (
                      <Circle size={16} className="text-gray-300 shrink-0" />
                    )}
                    <span className={cn(isCurrent && "font-medium text-gray-900", !reached && "text-gray-400")}>
                      {t(`commercialProposals.statuses.${step}`)}
                    </span>
                  </div>
                );
              })}
            </div>
            {timeline.length > 0 && (
              <div className="border-t border-gray-100 pt-3 space-y-2">
                {timeline.map((ev, i) => (
                  <div key={i} className="text-xs text-gray-500">
                    <span className="font-medium text-gray-700">{t(`commercialProposals.statuses.${ev.status}`)}</span>
                    {" · "}
                    {format(parseISO(ev.at), "MMM d, yyyy HH:mm")}
                    {ev.note && <p className="text-gray-400 mt-0.5">{ev.note}</p>}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card p-4">
            <RelatedEntitiesPanel entityType="proposal" entityId={id} />
          </div>

          {/* Change status */}
          <div className="card p-4 space-y-3">
            <h2 className="text-sm font-semibold text-gray-900">{t("commercialProposals.changeStatus")}</h2>
            <select
              className="input w-full text-sm"
              value={p.status}
              disabled={statusMutation.isPending}
              onChange={(e) => statusMutation.mutate(e.target.value as SalesProposalStatus)}
            >
              {WORKFLOW.map((s) => (
                <option key={s} value={s}>{t(`commercialProposals.statuses.${s}`)}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {editOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="card p-5 w-full max-w-lg space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">{t("commercialProposals.edit")}</h3>
              <button type="button" onClick={() => setEditOpen(false)}><X size={18} /></button>
            </div>
            <label className="block text-xs space-y-1">
              <span className="text-gray-600">{t("commercialProposals.colTitle")}</span>
              <input className="input w-full" value={editTitle} onChange={(e) => setEditTitle(e.target.value)} />
            </label>
            <label className="block text-xs space-y-1">
              <span className="text-gray-600">{t("commercialProposals.notes")}</span>
              <textarea className="input w-full min-h-[60px]" value={editNotes} onChange={(e) => setEditNotes(e.target.value)} />
            </label>
            <label className="block text-xs space-y-1">
              <span className="text-gray-600">{t("commercialProposals.terms")}</span>
              <textarea className="input w-full min-h-[80px]" value={editTerms} onChange={(e) => setEditTerms(e.target.value)} />
            </label>
            <div className="flex gap-2 justify-end">
              <button type="button" onClick={() => setEditOpen(false)} className="btn-secondary text-sm">{t("commercialProposals.cancel")}</button>
              <button type="button" disabled={updateMutation.isPending} onClick={() => updateMutation.mutate()} className="btn-primary text-sm">
                {updateMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : t("commercialProposals.save")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
