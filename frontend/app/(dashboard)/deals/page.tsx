"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Briefcase, ChevronLeft, ChevronRight, Loader2, Plus, X } from "lucide-react";
import toast from "react-hot-toast";
import {
  normalizeList,
  salesCrmApi,
  SALES_DEAL_STAGES,
  type SalesDeal,
  type SalesDealStage,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { RelatedEntitiesPanel } from "@/components/platform/RelatedEntitiesPanel";

const STAGE_STYLE: Record<SalesDealStage, string> = {
  new_lead: "border-sky-200 bg-sky-50/50",
  contacted: "border-amber-200 bg-amber-50/50",
  negotiation: "border-violet-200 bg-violet-50/50",
  proposal_sent: "border-indigo-200 bg-indigo-50/50",
  won: "border-emerald-200 bg-emerald-50/50",
  lost: "border-gray-200 bg-gray-50/50",
};

function fmtMoney(value: number | null, currency = "USD") {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 0 }).format(value);
}

function stageLabel(stage: SalesDealStage, t: (k: string) => string) {
  const key = `salesCrm.stage.${stage}`;
  const translated = t(key);
  return translated === key ? stage.replace(/_/g, " ") : translated;
}

type DealForm = {
  title: string;
  value: string;
  currency: string;
  stage: SalesDealStage;
  probability: string;
  expected_close_date: string;
  notes: string;
};

const EMPTY_FORM: DealForm = {
  title: "",
  value: "",
  currency: "USD",
  stage: "new_lead",
  probability: "10",
  expected_close_date: "",
  notes: "",
};

export default function DealsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<SalesDeal | null>(null);
  const [form, setForm] = useState<DealForm>(EMPTY_FORM);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sales-crm", "deals"],
    queryFn: () => salesCrmApi.listDeals({ limit: 200 }).then((r) => r.data),
  });

  const moveMutation = useMutation({
    mutationFn: ({ id, stage }: { id: string; stage: SalesDealStage }) =>
      salesCrmApi.moveDealStage(id, stage),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sales-crm"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload = {
        title: form.title.trim(),
        value: form.value ? Number(form.value) : null,
        currency: form.currency || "USD",
        stage: form.stage,
        probability: Number(form.probability) || 10,
        expected_close_date: form.expected_close_date
          ? new Date(form.expected_close_date).toISOString()
          : null,
        notes: form.notes.trim() || null,
        customer_id: editing?.customer_id ?? null,
        lead_id: editing?.lead_id ?? null,
      };
      if (!payload.title) throw new Error(t("salesCrm.titleRequired"));
      if (editing) return salesCrmApi.updateDeal(editing.id, payload);
      return salesCrmApi.createDeal(payload);
    },
    onSuccess: () => {
      toast.success(editing ? t("salesCrm.dealUpdated") : t("salesCrm.dealCreated"));
      qc.invalidateQueries({ queryKey: ["sales-crm"] });
      closeModal();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const items = normalizeList(data) as SalesDeal[];

  const byStage = useMemo(() => {
    const map: Record<SalesDealStage, SalesDeal[]> = {
      new_lead: [],
      contacted: [],
      negotiation: [],
      proposal_sent: [],
      won: [],
      lost: [],
    };
    for (const deal of items) {
      if (map[deal.stage]) map[deal.stage].push(deal);
    }
    return map;
  }, [items]);

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setModalOpen(true);
  }

  function openEdit(deal: SalesDeal) {
    setEditing(deal);
    setForm({
      title: deal.title,
      value: deal.value != null ? String(deal.value) : "",
      currency: deal.currency,
      stage: deal.stage,
      probability: String(deal.probability),
      expected_close_date: deal.expected_close_date
        ? format(parseISO(deal.expected_close_date), "yyyy-MM-dd")
        : "",
      notes: deal.notes ?? "",
    });
    setModalOpen(true);
  }

  function closeModal() {
    setModalOpen(false);
    setEditing(null);
    setForm(EMPTY_FORM);
  }

  function moveStage(deal: SalesDeal, direction: -1 | 1) {
    const idx = SALES_DEAL_STAGES.indexOf(deal.stage);
    const next = SALES_DEAL_STAGES[idx + direction];
    if (next) moveMutation.mutate({ id: deal.id, stage: next });
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Briefcase size={22} className="text-violet-600" />
            {t("nav.deals")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t("salesCrm.dealsSubtitle")}</p>
        </div>
        <button type="button" onClick={openCreate} className="btn-primary text-sm flex items-center gap-1.5">
          <Plus size={15} />
          {t("salesCrm.addDeal")}
        </button>
      </div>

      {isLoading ? (
        <LoadingState message={t("salesCrm.loading")} />
      ) : isError ? (
        <ErrorState message={error instanceof Error ? error.message : t("salesCrm.error")} onRetry={() => refetch()} />
      ) : items.length === 0 ? (
        <EmptyState
          title={t("salesCrm.noDeals")}
          description={t("salesCrm.noDealsHint")}
          action={<button type="button" onClick={openCreate} className="btn-primary text-sm">{t("salesCrm.addDeal")}</button>}
        />
      ) : (
        <div className="flex gap-3 overflow-x-auto pb-2">
          {SALES_DEAL_STAGES.map((stage) => (
            <div
              key={stage}
              className={cn("min-w-[220px] flex-1 rounded-xl border p-3", STAGE_STYLE[stage])}
            >
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-xs font-semibold text-gray-700 capitalize">
                  {stageLabel(stage, t)}
                </h3>
                <span className="text-[10px] bg-white/80 px-1.5 py-0.5 rounded-full text-gray-600">
                  {byStage[stage].length}
                </span>
              </div>
              <div className="space-y-2">
                {byStage[stage].map((deal) => (
                  <div key={deal.id} className="card p-3 bg-white shadow-sm">
                    <button
                      type="button"
                      onClick={() => openEdit(deal)}
                      className="text-sm font-medium text-brand-800 hover:underline text-left w-full truncate"
                    >
                      {deal.title}
                    </button>
                    <p className="text-xs text-gray-500 mt-0.5 truncate">
                      {deal.customer_name || deal.lead_name || "—"}
                    </p>
                    <p className="text-sm font-semibold text-gray-900 mt-1">
                      {fmtMoney(deal.value, deal.currency)}
                    </p>
                    {deal.expected_close_date && (
                      <p className="text-[10px] text-gray-400 mt-0.5">
                        {t("salesCrm.expectedClose")}: {format(parseISO(deal.expected_close_date), "MMM d, yyyy")}
                      </p>
                    )}
                    <div className="flex items-center justify-between mt-2 pt-2 border-t border-gray-100">
                      <button
                        type="button"
                        disabled={stage === "new_lead" || moveMutation.isPending}
                        onClick={() => moveStage(deal, -1)}
                        className="text-gray-400 hover:text-gray-700 disabled:opacity-30"
                        aria-label="Previous stage"
                      >
                        <ChevronLeft size={16} />
                      </button>
                      <span className="text-[10px] text-gray-500">{deal.probability}%</span>
                      <button
                        type="button"
                        disabled={stage === "lost" || moveMutation.isPending}
                        onClick={() => moveStage(deal, 1)}
                        className="text-gray-400 hover:text-gray-700 disabled:opacity-30"
                        aria-label="Next stage"
                      >
                        <ChevronRight size={16} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
          <div className="card w-full max-w-md p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-gray-900">
                {editing ? t("salesCrm.editDeal") : t("salesCrm.addDeal")}
              </h2>
              <button type="button" onClick={closeModal} className="text-gray-400 hover:text-gray-700">
                <X size={18} />
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-500">{t("salesCrm.dealTitle")} *</label>
                <input className="input w-full mt-0.5" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-500">{t("salesCrm.value")}</label>
                  <input className="input w-full mt-0.5" type="number" min="0" value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
                </div>
                <div>
                  <label className="text-xs text-gray-500">{t("salesCrm.currency")}</label>
                  <input className="input w-full mt-0.5" value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-500">{t("salesCrm.stage")}</label>
                  <select className="input w-full mt-0.5" value={form.stage} onChange={(e) => setForm({ ...form, stage: e.target.value as SalesDealStage })}>
                    {SALES_DEAL_STAGES.map((s) => (
                      <option key={s} value={s}>{stageLabel(s, t)}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-gray-500">{t("salesCrm.probability")}</label>
                  <input className="input w-full mt-0.5" type="number" min="0" max="100" value={form.probability} onChange={(e) => setForm({ ...form, probability: e.target.value })} />
                </div>
              </div>
              <div>
                <label className="text-xs text-gray-500">{t("salesCrm.expectedClose")}</label>
                <input className="input w-full mt-0.5" type="date" value={form.expected_close_date} onChange={(e) => setForm({ ...form, expected_close_date: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-gray-500">{t("salesCrm.notes")}</label>
                <textarea className="input w-full mt-0.5 min-h-[64px]" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              </div>
              {editing && (
                <div className="border-t border-gray-100 pt-3">
                  <RelatedEntitiesPanel entityType="deal" entityId={editing.id} />
                </div>
              )}
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button type="button" onClick={closeModal} className="btn-secondary text-sm">{t("salesCrm.cancel")}</button>
              <button
                type="button"
                onClick={() => saveMutation.mutate()}
                disabled={saveMutation.isPending}
                className="btn-primary text-sm flex items-center gap-1.5"
              >
                {saveMutation.isPending && <Loader2 size={14} className="animate-spin" />}
                {t("salesCrm.save")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
