"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Contact, Loader2, Plus, Search, Trash2, X } from "lucide-react";
import toast from "react-hot-toast";
import {
  normalizeList,
  salesCrmApi,
  type SalesLead,
  type SalesLeadPriority,
  type SalesLeadSource,
  type SalesLeadStatus,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { RelatedEntitiesPanel } from "@/components/platform/RelatedEntitiesPanel";

const STATUSES: SalesLeadStatus[] = ["new", "contacted", "qualified", "converted", "lost"];
const PRIORITIES: SalesLeadPriority[] = ["high", "medium", "low"];
const SOURCES: SalesLeadSource[] = ["manual", "website", "referral", "exhibition", "social", "other"];

const STATUS_STYLE: Record<SalesLeadStatus, string> = {
  new: "bg-sky-100 text-sky-800",
  contacted: "bg-amber-100 text-amber-800",
  qualified: "bg-violet-100 text-violet-800",
  converted: "bg-emerald-100 text-emerald-800",
  lost: "bg-gray-100 text-gray-600",
};

const PRIORITY_STYLE: Record<SalesLeadPriority, string> = {
  high: "bg-red-100 text-red-800",
  medium: "bg-yellow-100 text-yellow-800",
  low: "bg-gray-100 text-gray-600",
};

type LeadForm = {
  name: string;
  company: string;
  phone: string;
  email: string;
  telegram: string;
  whatsapp: string;
  wechat: string;
  country: string;
  city: string;
  source: SalesLeadSource;
  status: SalesLeadStatus;
  priority: SalesLeadPriority;
  notes: string;
  assigned_to: string;
};

const EMPTY_FORM: LeadForm = {
  name: "",
  company: "",
  phone: "",
  email: "",
  telegram: "",
  whatsapp: "",
  wechat: "",
  country: "",
  city: "",
  source: "manual",
  status: "new",
  priority: "medium",
  notes: "",
  assigned_to: "",
};

function leadToForm(lead: SalesLead): LeadForm {
  return {
    name: lead.name,
    company: lead.company ?? "",
    phone: lead.phone ?? "",
    email: lead.email ?? "",
    telegram: lead.telegram ?? "",
    whatsapp: lead.whatsapp ?? "",
    wechat: lead.wechat ?? "",
    country: lead.country ?? "",
    city: lead.city ?? "",
    source: lead.source,
    status: lead.status,
    priority: lead.priority,
    notes: lead.notes ?? "",
    assigned_to: lead.assigned_to ?? "",
  };
}

export default function LeadsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<SalesLeadStatus | "">("");
  const [sourceFilter, setSourceFilter] = useState<SalesLeadSource | "">("");
  const [priorityFilter, setPriorityFilter] = useState<SalesLeadPriority | "">("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<SalesLead | null>(null);
  const [form, setForm] = useState<LeadForm>(EMPTY_FORM);

  const params = useMemo(
    () => ({
      search: search.trim() || undefined,
      status: statusFilter || undefined,
      source: sourceFilter || undefined,
      priority: priorityFilter || undefined,
      limit: 100,
    }),
    [search, statusFilter, sourceFilter, priorityFilter],
  );

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sales-crm", "leads", params],
    queryFn: () => salesCrmApi.listLeads(params).then((r) => r.data),
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
        source: form.source,
        status: form.status,
        priority: form.priority,
        notes: form.notes.trim() || null,
        assigned_to: form.assigned_to.trim() || null,
        customer_id: null,
      };
      if (!payload.name) throw new Error(t("salesCrm.nameRequired"));
      if (editing) return salesCrmApi.updateLead(editing.id, payload);
      return salesCrmApi.createLead(payload);
    },
    onSuccess: () => {
      toast.success(editing ? t("salesCrm.leadUpdated") : t("salesCrm.leadCreated"));
      qc.invalidateQueries({ queryKey: ["sales-crm"] });
      closeModal();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => salesCrmApi.deleteLead(id),
    onSuccess: () => {
      toast.success(t("salesCrm.leadDeleted"));
      qc.invalidateQueries({ queryKey: ["sales-crm"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const items = normalizeList(data) as SalesLead[];

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setModalOpen(true);
  }

  function openEdit(lead: SalesLead) {
    setEditing(lead);
    setForm(leadToForm(lead));
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
            <Contact size={22} className="text-brand-600" />
            {t("nav.leads")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t("salesCrm.leadsSubtitle")}</p>
        </div>
        <button type="button" onClick={openCreate} className="btn-primary text-sm flex items-center gap-1.5">
          <Plus size={15} />
          {t("salesCrm.addLead")}
        </button>
      </div>

      <div className="card p-4 flex flex-wrap gap-3 items-end">
        <div className="flex-1 min-w-[200px]">
          <label className="text-xs text-gray-500 block mb-1">{t("salesCrm.search")}</label>
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              className="input pl-9 w-full"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("salesCrm.searchLeadsPlaceholder")}
            />
          </div>
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">{t("salesCrm.status")}</label>
          <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as SalesLeadStatus | "")}>
            <option value="">{t("salesCrm.all")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s} className="capitalize">{s}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">{t("salesCrm.source")}</label>
          <select className="input" value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value as SalesLeadSource | "")}>
            <option value="">{t("salesCrm.all")}</option>
            {SOURCES.map((s) => (
              <option key={s} value={s} className="capitalize">{s}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">{t("salesCrm.priority")}</label>
          <select className="input" value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value as SalesLeadPriority | "")}>
            <option value="">{t("salesCrm.all")}</option>
            {PRIORITIES.map((p) => (
              <option key={p} value={p} className="capitalize">{p}</option>
            ))}
          </select>
        </div>
      </div>

      {isLoading ? (
        <LoadingState message={t("salesCrm.loading")} />
      ) : isError ? (
        <ErrorState message={error instanceof Error ? error.message : t("salesCrm.error")} onRetry={() => refetch()} />
      ) : items.length === 0 ? (
        <EmptyState title={t("salesCrm.noLeads")} description={t("salesCrm.noLeadsHint")} action={
          <button type="button" onClick={openCreate} className="btn-primary text-sm">{t("salesCrm.addLead")}</button>
        } />
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm table-premium">
            <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
              <tr>
                <th className="text-left px-4 py-2">{t("salesCrm.name")}</th>
                <th className="text-left px-4 py-2">{t("salesCrm.company")}</th>
                <th className="text-left px-4 py-2">{t("salesCrm.contact")}</th>
                <th className="text-left px-4 py-2">{t("salesCrm.status")}</th>
                <th className="text-left px-4 py-2">{t("salesCrm.priority")}</th>
                <th className="text-left px-4 py-2">{t("salesCrm.source")}</th>
                <th className="text-right px-4 py-2">{t("salesCrm.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((lead) => (
                <tr key={lead.id} className="border-t border-gray-100 hover:bg-gray-50/50">
                  <td className="px-4 py-2.5">
                    <button type="button" onClick={() => openEdit(lead)} className="font-medium text-brand-700 hover:underline text-left">
                      {lead.name}
                    </button>
                    <p className="text-[10px] text-gray-400">{format(parseISO(lead.updated_at), "MMM d, yyyy")}</p>
                  </td>
                  <td className="px-4 py-2.5 text-gray-600">{lead.company || "—"}</td>
                  <td className="px-4 py-2.5 text-gray-600 text-xs">
                    {lead.email || lead.phone || lead.telegram || "—"}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={cn("text-[10px] px-2 py-0.5 rounded-full capitalize", STATUS_STYLE[lead.status])}>
                      {lead.status}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={cn("text-[10px] px-2 py-0.5 rounded-full capitalize", PRIORITY_STYLE[lead.priority])}>
                      {lead.priority}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 capitalize text-gray-600">{lead.source}</td>
                  <td className="px-4 py-2.5 text-right">
                    <button
                      type="button"
                      onClick={() => {
                        if (confirm(t("salesCrm.confirmDeleteLead"))) deleteMutation.mutate(lead.id);
                      }}
                      className="text-red-600 hover:text-red-800 p-1"
                      aria-label={t("salesCrm.delete")}
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
          <div className="card w-full max-w-lg max-h-[90vh] overflow-y-auto p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-gray-900">
                {editing ? t("salesCrm.editLead") : t("salesCrm.addLead")}
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
              <div>
                <label className="text-xs text-gray-500">{t("salesCrm.source")}</label>
                <select className="input w-full mt-0.5" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value as SalesLeadSource })}>
                  {SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500">{t("salesCrm.status")}</label>
                <select className="input w-full mt-0.5" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value as SalesLeadStatus })}>
                  {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500">{t("salesCrm.priority")}</label>
                <select className="input w-full mt-0.5" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value as SalesLeadPriority })}>
                  {PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500">{t("salesCrm.assignedTo")}</label>
                <input className="input w-full mt-0.5" value={form.assigned_to} onChange={(e) => setForm({ ...form, assigned_to: e.target.value })} />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-gray-500">{t("salesCrm.notes")}</label>
                <textarea className="input w-full mt-0.5 min-h-[72px]" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              </div>
              {editing && (
                <div className="col-span-2 border-t border-gray-100 pt-3">
                  <RelatedEntitiesPanel entityType="lead" entityId={editing.id} />
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
