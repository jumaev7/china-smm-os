"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Loader2, Plus, Search, Trash2, Users, X } from "lucide-react";
import toast from "react-hot-toast";
import {
  normalizeList,
  salesCrmApi,
  type SalesCustomer,
  type SalesDeal,
  type SalesLead,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

type CustomerForm = {
  name: string;
  company: string;
  phone: string;
  email: string;
  telegram: string;
  whatsapp: string;
  wechat: string;
  country: string;
  city: string;
  notes: string;
};

const EMPTY_FORM: CustomerForm = {
  name: "",
  company: "",
  phone: "",
  email: "",
  telegram: "",
  whatsapp: "",
  wechat: "",
  country: "",
  city: "",
  notes: "",
};

function customerToForm(c: SalesCustomer): CustomerForm {
  return {
    name: c.name,
    company: c.company ?? "",
    phone: c.phone ?? "",
    email: c.email ?? "",
    telegram: c.telegram ?? "",
    whatsapp: c.whatsapp ?? "",
    wechat: c.wechat ?? "",
    country: c.country ?? "",
    city: c.city ?? "",
    notes: c.notes ?? "",
  };
}

function fmtMoney(value: number | null, currency = "USD") {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 0 }).format(value);
}

export default function CustomersPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [editing, setEditing] = useState<SalesCustomer | null>(null);
  const [form, setForm] = useState<CustomerForm>(EMPTY_FORM);

  const listParams = useMemo(
    () => ({ search: search.trim() || undefined, limit: 100 }),
    [search],
  );

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sales-crm", "customers", listParams],
    queryFn: () => salesCrmApi.listCustomers(listParams).then((r) => r.data),
  });

  const { data: linkedDeals } = useQuery({
    queryKey: ["sales-crm", "deals", "customer", detailId],
    queryFn: () => salesCrmApi.listDeals({ customer_id: detailId!, limit: 20 }).then((r) => r.data),
    enabled: !!detailId,
  });

  const { data: linkedLeads } = useQuery({
    queryKey: ["sales-crm", "leads", "customer", detailId],
    queryFn: () => salesCrmApi.listLeads({ customer_id: detailId!, limit: 20 }).then((r) => r.data),
    enabled: !!detailId,
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload = {
        name: form.name.trim(),
        company: form.company.trim() || null,
        phone: form.phone.trim() || null,
        email: form.email.trim() || null,
        telegram: form.telegram.trim() || null,
        whatsapp: form.whatsapp.trim() || null,
        wechat: form.wechat.trim() || null,
        country: form.country.trim() || null,
        city: form.city.trim() || null,
        notes: form.notes.trim() || null,
      };
      if (!payload.name) throw new Error(t("salesCrm.nameRequired"));
      if (editing) return salesCrmApi.updateCustomer(editing.id, payload);
      return salesCrmApi.createCustomer(payload);
    },
    onSuccess: () => {
      toast.success(editing ? t("salesCrm.customerUpdated") : t("salesCrm.customerCreated"));
      qc.invalidateQueries({ queryKey: ["sales-crm"] });
      closeModal();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => salesCrmApi.deleteCustomer(id),
    onSuccess: () => {
      toast.success(t("salesCrm.customerDeleted"));
      setDetailId(null);
      qc.invalidateQueries({ queryKey: ["sales-crm"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const items = normalizeList(data) as SalesCustomer[];
  const deals = normalizeList(linkedDeals) as SalesDeal[];
  const leads = normalizeList(linkedLeads) as SalesLead[];
  const selected = items.find((c) => c.id === detailId) ?? null;

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setModalOpen(true);
  }

  function openEdit(customer: SalesCustomer) {
    setEditing(customer);
    setForm(customerToForm(customer));
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
            <Users size={22} className="text-amber-600" />
            {t("nav.customers")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t("salesCrm.customersSubtitle")}</p>
        </div>
        <button type="button" onClick={openCreate} className="btn-primary text-sm flex items-center gap-1.5">
          <Plus size={15} />
          {t("salesCrm.addCustomer")}
        </button>
      </div>

      <div className="card p-4">
        <div className="relative max-w-md">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            className="input pl-9 w-full"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("salesCrm.searchCustomersPlaceholder")}
          />
        </div>
      </div>

      {isLoading ? (
        <LoadingState message={t("salesCrm.loading")} />
      ) : isError ? (
        <ErrorState message={error instanceof Error ? error.message : t("salesCrm.error")} onRetry={() => refetch()} />
      ) : items.length === 0 ? (
        <EmptyState
          title={t("salesCrm.noCustomers")}
          description={t("salesCrm.noCustomersHint")}
          action={<button type="button" onClick={openCreate} className="btn-primary text-sm">{t("salesCrm.addCustomer")}</button>}
        />
      ) : (
        <div className="grid lg:grid-cols-5 gap-5">
          <div className="lg:col-span-2 card overflow-hidden">
            <ul className="divide-y divide-gray-100">
              {items.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => setDetailId(c.id)}
                    className={`w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors ${
                      detailId === c.id ? "bg-brand-50 border-l-2 border-brand-600" : ""
                    }`}
                  >
                    <p className="font-medium text-gray-900 truncate">{c.name}</p>
                    <p className="text-xs text-gray-500 truncate">{c.company || c.email || "—"}</p>
                    <p className="text-[10px] text-gray-400 mt-0.5">
                      {[c.city, c.country].filter(Boolean).join(", ") || "—"}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="lg:col-span-3 card p-5">
            {!selected ? (
              <p className="text-sm text-gray-400">{t("salesCrm.selectCustomer")}</p>
            ) : (
              <div className="space-y-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-semibold text-gray-900">{selected.name}</h2>
                    {selected.company && <p className="text-sm text-gray-600">{selected.company}</p>}
                  </div>
                  <div className="flex gap-2">
                    <button type="button" onClick={() => openEdit(selected)} className="btn-secondary text-xs">
                      {t("salesCrm.edit")}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        if (confirm(t("salesCrm.confirmDeleteCustomer"))) deleteMutation.mutate(selected.id);
                      }}
                      className="text-red-600 hover:text-red-800 p-1"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>

                <div className="grid sm:grid-cols-2 gap-3 text-sm">
                  <div>
                    <p className="text-xs text-gray-500">{t("salesCrm.email")}</p>
                    <p className="text-gray-800">{selected.email || "—"}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">{t("salesCrm.phone")}</p>
                    <p className="text-gray-800">{selected.phone || "—"}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">Telegram</p>
                    <p className="text-gray-800">{selected.telegram || "—"}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">WhatsApp</p>
                    <p className="text-gray-800">{selected.whatsapp || "—"}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">WeChat</p>
                    <p className="text-gray-800">{selected.wechat || "—"}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">{t("salesCrm.location")}</p>
                    <p className="text-gray-800">
                      {[selected.city, selected.country].filter(Boolean).join(", ") || "—"}
                    </p>
                  </div>
                </div>

                {selected.notes && (
                  <div>
                    <p className="text-xs text-gray-500 mb-1">{t("salesCrm.notes")}</p>
                    <p className="text-sm text-gray-700 whitespace-pre-wrap">{selected.notes}</p>
                  </div>
                )}

                <div>
                  <h3 className="text-sm font-semibold text-gray-800 mb-2">{t("salesCrm.linkedDeals")}</h3>
                  {deals.length === 0 ? (
                    <p className="text-xs text-gray-400">{t("salesCrm.noLinkedDeals")}</p>
                  ) : (
                    <ul className="space-y-1.5">
                      {deals.map((d) => (
                        <li key={d.id} className="text-sm flex justify-between gap-2">
                          <span className="text-gray-800 truncate">{d.title}</span>
                          <span className="text-gray-500 shrink-0 capitalize">{d.stage.replace(/_/g, " ")}</span>
                          <span className="font-medium shrink-0">{fmtMoney(d.value, d.currency)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div>
                  <h3 className="text-sm font-semibold text-gray-800 mb-2">{t("salesCrm.linkedLeads")}</h3>
                  {leads.length === 0 ? (
                    <p className="text-xs text-gray-400">{t("salesCrm.noLinkedLeads")}</p>
                  ) : (
                    <ul className="space-y-1.5">
                      {leads.map((l) => (
                        <li key={l.id} className="text-sm flex justify-between gap-2">
                          <span className="text-gray-800">{l.name}</span>
                          <span className="capitalize text-gray-500">{l.status}</span>
                          <span className="text-[10px] text-gray-400">
                            {format(parseISO(l.updated_at), "MMM d")}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40">
          <div className="card w-full max-w-lg max-h-[90vh] overflow-y-auto p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-gray-900">
                {editing ? t("salesCrm.editCustomer") : t("salesCrm.addCustomer")}
              </h2>
              <button type="button" onClick={closeModal} className="text-gray-400 hover:text-gray-700">
                <X size={18} />
              </button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className="text-xs text-gray-500">{t("salesCrm.name")} *</label>
                <input className="input w-full mt-0.5" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-gray-500">{t("salesCrm.company")}</label>
                <input className="input w-full mt-0.5" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-gray-500">{t("salesCrm.phone")}</label>
                <input className="input w-full mt-0.5" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-gray-500">{t("salesCrm.email")}</label>
                <input className="input w-full mt-0.5" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
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
                <label className="text-xs text-gray-500">{t("salesCrm.country")}</label>
                <input className="input w-full mt-0.5" value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-gray-500">{t("salesCrm.city")}</label>
                <input className="input w-full mt-0.5" value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-gray-500">{t("salesCrm.notes")}</label>
                <textarea className="input w-full mt-0.5 min-h-[72px]" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              </div>
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
