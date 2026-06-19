"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Building2, Loader2, Plus, Search, Trash2, X } from "lucide-react";
import toast from "react-hot-toast";
import {
  BUYER_STATUSES,
  buyersApi,
  CENTRAL_ASIA_COUNTRIES,
  normalizeList,
  type Buyer,
  type BuyerStatus,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

const STATUS_STYLE: Record<BuyerStatus, string> = {
  prospect: "bg-sky-100 text-sky-800",
  contacted: "bg-amber-100 text-amber-800",
  interested: "bg-violet-100 text-violet-800",
  negotiating: "bg-orange-100 text-orange-800",
  active_buyer: "bg-emerald-100 text-emerald-800",
  inactive: "bg-gray-100 text-gray-600",
};

type BuyerForm = {
  company_name: string;
  contact_person: string;
  country: string;
  city: string;
  industry: string;
  website: string;
  email: string;
  phone: string;
  telegram: string;
  whatsapp: string;
  wechat: string;
  annual_purchase_volume: string;
  product_categories: string;
  notes: string;
  tags: string;
  status: BuyerStatus;
};

const EMPTY_FORM: BuyerForm = {
  company_name: "",
  contact_person: "",
  country: "",
  city: "",
  industry: "",
  website: "",
  email: "",
  phone: "",
  telegram: "",
  whatsapp: "",
  wechat: "",
  annual_purchase_volume: "",
  product_categories: "",
  notes: "",
  tags: "",
  status: "prospect",
};

function buyerToForm(buyer: Buyer): BuyerForm {
  return {
    company_name: buyer.company_name,
    contact_person: buyer.contact_person ?? "",
    country: buyer.country ?? "",
    city: buyer.city ?? "",
    industry: buyer.industry ?? "",
    website: buyer.website ?? "",
    email: buyer.email ?? "",
    phone: buyer.phone ?? "",
    telegram: buyer.telegram ?? "",
    whatsapp: buyer.whatsapp ?? "",
    wechat: buyer.wechat ?? "",
    annual_purchase_volume: buyer.annual_purchase_volume ?? "",
    product_categories: (buyer.product_categories ?? []).join(", "),
    notes: buyer.notes ?? "",
    tags: (buyer.tags ?? []).join(", "),
    status: buyer.status,
  };
}

function parseCsv(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function statusLabel(status: BuyerStatus, t: (k: string) => string) {
  const key = `buyerCrm.status.${status}`;
  const translated = t(key);
  return translated === key ? status.replace(/_/g, " ") : translated;
}

export default function BuyersPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<BuyerStatus | "">("");
  const [countryFilter, setCountryFilter] = useState("");
  const [industryFilter, setIndustryFilter] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Buyer | null>(null);
  const [form, setForm] = useState<BuyerForm>(EMPTY_FORM);

  const params = useMemo(
    () => ({
      search: search.trim() || undefined,
      status: statusFilter || undefined,
      country: countryFilter || undefined,
      industry: industryFilter || undefined,
      limit: 100,
    }),
    [search, statusFilter, countryFilter, industryFilter],
  );

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["buyers", "list", params],
    queryFn: () => buyersApi.list(params).then((r) => r.data),
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload = {
        company_name: form.company_name.trim(),
        contact_person: form.contact_person.trim() || null,
        country: form.country.trim() || null,
        city: form.city.trim() || null,
        industry: form.industry.trim() || null,
        website: form.website.trim() || null,
        email: form.email.trim() || null,
        phone: form.phone.trim() || null,
        telegram: form.telegram.trim() || null,
        whatsapp: form.whatsapp.trim() || null,
        wechat: form.wechat.trim() || null,
        annual_purchase_volume: form.annual_purchase_volume.trim() || null,
        product_categories: parseCsv(form.product_categories),
        notes: form.notes.trim() || null,
        tags: parseCsv(form.tags),
        status: form.status,
      };
      if (!payload.company_name) throw new Error(t("buyerCrm.companyRequired"));
      if (editing) return buyersApi.update(editing.id, payload);
      return buyersApi.create(payload);
    },
    onSuccess: () => {
      toast.success(editing ? t("buyerCrm.buyerUpdated") : t("buyerCrm.buyerCreated"));
      qc.invalidateQueries({ queryKey: ["buyers"] });
      closeModal();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => buyersApi.delete(id),
    onSuccess: () => {
      toast.success(t("buyerCrm.buyerDeleted"));
      qc.invalidateQueries({ queryKey: ["buyers"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const items = normalizeList(data) as Buyer[];

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setModalOpen(true);
  }

  function openEdit(buyer: Buyer) {
    setEditing(buyer);
    setForm(buyerToForm(buyer));
    setModalOpen(true);
  }

  function closeModal() {
    setModalOpen(false);
    setEditing(null);
    setForm(EMPTY_FORM);
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Building2 size={22} className="text-brand-600" />
            {t("nav.buyers")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t("buyerCrm.directorySubtitle")}</p>
        </div>
        <button type="button" onClick={openCreate} className="btn-primary text-sm flex items-center gap-1.5">
          <Plus size={15} />
          {t("buyerCrm.addBuyer")}
        </button>
      </div>

      <div className="card p-4 flex flex-wrap gap-3 items-end">
        <div className="flex-1 min-w-[200px]">
          <label className="text-xs text-gray-500 block mb-1">{t("buyerCrm.search")}</label>
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              className="input pl-9 w-full"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("buyerCrm.searchPlaceholder")}
            />
          </div>
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">{t("buyerCrm.status")}</label>
          <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as BuyerStatus | "")}>
            <option value="">{t("buyerCrm.all")}</option>
            {BUYER_STATUSES.map((s) => (
              <option key={s} value={s}>{statusLabel(s, t)}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">{t("buyerCrm.country")}</label>
          <select className="input" value={countryFilter} onChange={(e) => setCountryFilter(e.target.value)}>
            <option value="">{t("buyerCrm.all")}</option>
            {CENTRAL_ASIA_COUNTRIES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">{t("buyerCrm.industry")}</label>
          <input className="input" value={industryFilter} onChange={(e) => setIndustryFilter(e.target.value)} placeholder={t("buyerCrm.industryFilter")} />
        </div>
      </div>

      {isLoading ? (
        <LoadingState message={t("buyerCrm.loading")} />
      ) : isError ? (
        <ErrorState message={error instanceof Error ? error.message : t("buyerCrm.error")} onRetry={() => refetch()} />
      ) : items.length === 0 ? (
        <EmptyState
          title={t("buyerCrm.noBuyers")}
          description={t("buyerCrm.noBuyersHint")}
          action={
            <button type="button" onClick={openCreate} className="btn-primary text-sm">{t("buyerCrm.addBuyer")}</button>
          }
        />
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm table-premium">
            <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
              <tr>
                <th className="text-left px-4 py-2">{t("buyerCrm.company")}</th>
                <th className="text-left px-4 py-2">{t("buyerCrm.contactPerson")}</th>
                <th className="text-left px-4 py-2">{t("buyerCrm.location")}</th>
                <th className="text-left px-4 py-2">{t("buyerCrm.industry")}</th>
                <th className="text-left px-4 py-2">{t("buyerCrm.status")}</th>
                <th className="text-right px-4 py-2">{t("buyerCrm.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((buyer) => (
                <tr key={buyer.id} className="border-t border-gray-100 hover:bg-gray-50/50">
                  <td className="px-4 py-2.5">
                    <Link href={`/buyers/${buyer.id}`} className="font-medium text-brand-700 hover:underline">
                      {buyer.company_name}
                    </Link>
                    <p className="text-[10px] text-gray-400">{format(parseISO(buyer.updated_at), "MMM d, yyyy")}</p>
                  </td>
                  <td className="px-4 py-2.5 text-gray-600">{buyer.contact_person || "—"}</td>
                  <td className="px-4 py-2.5 text-gray-600 text-xs">
                    {[buyer.city, buyer.country].filter(Boolean).join(", ") || "—"}
                  </td>
                  <td className="px-4 py-2.5 text-gray-600">{buyer.industry || "—"}</td>
                  <td className="px-4 py-2.5">
                    <span className={cn("text-[10px] px-2 py-0.5 rounded-full", STATUS_STYLE[buyer.status])}>
                      {statusLabel(buyer.status, t)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right space-x-1">
                    <button type="button" onClick={() => openEdit(buyer)} className="text-brand-600 hover:underline text-xs">
                      {t("buyerCrm.edit")}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (confirm(t("buyerCrm.confirmDelete"))) deleteMutation.mutate(buyer.id);
                      }}
                      className="text-red-600 hover:text-red-800 p-1 inline-flex"
                      aria-label={t("buyerCrm.delete")}
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
          <div className="card w-full max-w-2xl max-h-[90vh] overflow-y-auto p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-gray-900">
                {editing ? t("buyerCrm.editBuyer") : t("buyerCrm.addBuyer")}
              </h2>
              <button type="button" onClick={closeModal} className="text-gray-400 hover:text-gray-700">
                <X size={18} />
              </button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className="text-xs text-gray-500">{t("buyerCrm.company")} *</label>
                <input className="input w-full mt-0.5" value={form.company_name} onChange={(e) => setForm({ ...form, company_name: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-gray-500">{t("buyerCrm.contactPerson")}</label>
                <input className="input w-full mt-0.5" value={form.contact_person} onChange={(e) => setForm({ ...form, contact_person: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-gray-500">{t("buyerCrm.status")}</label>
                <select className="input w-full mt-0.5" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value as BuyerStatus })}>
                  {BUYER_STATUSES.map((s) => <option key={s} value={s}>{statusLabel(s, t)}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500">{t("buyerCrm.country")}</label>
                <select className="input w-full mt-0.5" value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })}>
                  <option value="">—</option>
                  {CENTRAL_ASIA_COUNTRIES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500">{t("buyerCrm.city")}</label>
                <input className="input w-full mt-0.5" value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-gray-500">{t("buyerCrm.industry")}</label>
                <input className="input w-full mt-0.5" value={form.industry} onChange={(e) => setForm({ ...form, industry: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-gray-500">{t("buyerCrm.website")}</label>
                <input className="input w-full mt-0.5" value={form.website} onChange={(e) => setForm({ ...form, website: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-gray-500">{t("buyerCrm.email")}</label>
                <input className="input w-full mt-0.5" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-gray-500">{t("buyerCrm.phone")}</label>
                <input className="input w-full mt-0.5" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-gray-500">Telegram</label>
                <input className="input w-full mt-0.5" value={form.telegram} onChange={(e) => setForm({ ...form, telegram: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-gray-500">WhatsApp</label>
                <input className="input w-full mt-0.5" value={form.whatsapp} onChange={(e) => setForm({ ...form, whatsapp: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-gray-500">WeChat</label>
                <input className="input w-full mt-0.5" value={form.wechat} onChange={(e) => setForm({ ...form, wechat: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-gray-500">{t("buyerCrm.annualVolume")}</label>
                <input className="input w-full mt-0.5" value={form.annual_purchase_volume} onChange={(e) => setForm({ ...form, annual_purchase_volume: e.target.value })} />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-gray-500">{t("buyerCrm.productCategories")}</label>
                <input className="input w-full mt-0.5" value={form.product_categories} onChange={(e) => setForm({ ...form, product_categories: e.target.value })} placeholder={t("buyerCrm.csvHint")} />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-gray-500">{t("buyerCrm.tags")}</label>
                <input className="input w-full mt-0.5" value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} placeholder={t("buyerCrm.csvHint")} />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-gray-500">{t("buyerCrm.notes")}</label>
                <textarea className="input w-full mt-0.5 min-h-[72px]" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button type="button" onClick={closeModal} className="btn-secondary text-sm">{t("buyerCrm.cancel")}</button>
              <button
                type="button"
                onClick={() => saveMutation.mutate()}
                disabled={saveMutation.isPending}
                className="btn-primary text-sm flex items-center gap-1.5"
              >
                {saveMutation.isPending && <Loader2 size={14} className="animate-spin" />}
                {t("buyerCrm.save")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
