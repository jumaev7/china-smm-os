"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Loader2, Plus, Trash2 } from "lucide-react";
import toast from "react-hot-toast";
import {
  normalizeList,
  salesCrmApi,
  salesProposalsApi,
  type SalesProposalItemInput,
} from "@/lib/api";
import { LoadingState } from "@/components/ui/PageStates";
import { useTranslation } from "@/lib/I18nProvider";

const CURRENCIES = ["USD", "EUR", "CNY", "RUB", "AED", "BRL"];

type ItemRow = SalesProposalItemInput & { key: string };

function emptyItem(): ItemRow {
  return {
    key: crypto.randomUUID(),
    product_or_service_name: "",
    description: "",
    quantity: 1,
    unit_price: 0,
    discount: 0,
  };
}

function calcItemTotal(item: ItemRow) {
  return Math.max(item.quantity * item.unit_price - item.discount, 0);
}

function ProposalForm() {
  const { t } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [title, setTitle] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [leadId, setLeadId] = useState("");
  const [dealId, setDealId] = useState("");
  const [issueDate, setIssueDate] = useState(new Date().toISOString().slice(0, 10));
  const [validUntil, setValidUntil] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [proposalDiscount, setProposalDiscount] = useState(0);
  const [tax, setTax] = useState(0);
  const [notes, setNotes] = useState("");
  const [terms, setTerms] = useState("");
  const [items, setItems] = useState<ItemRow[]>([emptyItem()]);

  useEffect(() => {
    const lead = searchParams.get("lead_id");
    const deal = searchParams.get("deal_id");
    const customer = searchParams.get("customer_id");
    if (lead) setLeadId(lead);
    if (deal) setDealId(deal);
    if (customer) setCustomerId(customer);
  }, [searchParams]);

  const { data: customersData } = useQuery({
    queryKey: ["sales-crm", "customers"],
    queryFn: () => salesCrmApi.listCustomers({ limit: 200 }).then((r) => r.data),
  });

  const { data: leadsData } = useQuery({
    queryKey: ["sales-crm", "leads"],
    queryFn: () => salesCrmApi.listLeads({ limit: 200 }).then((r) => r.data),
  });

  const { data: dealsData } = useQuery({
    queryKey: ["sales-crm", "deals"],
    queryFn: () => salesCrmApi.listDeals({ limit: 200 }).then((r) => r.data),
  });

  const fromLeadMutation = useMutation({
    mutationFn: (id: string) => salesProposalsApi.createFromLead(id).then((r) => r.data),
    onSuccess: (p) => {
      toast.success(t("commercialProposals.created"));
      router.push(`/proposals/${p.id}`);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const fromDealMutation = useMutation({
    mutationFn: (id: string) => salesProposalsApi.createFromDeal(id).then((r) => r.data),
    onSuccess: (p) => {
      toast.success(t("commercialProposals.created"));
      router.push(`/proposals/${p.id}`);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const createMutation = useMutation({
    mutationFn: () => {
      const payloadItems = items.map(({ key: _k, ...rest }) => ({
        ...rest,
        product_or_service_name: rest.product_or_service_name.trim(),
        description: rest.description?.trim() || null,
      }));
      if (!title.trim()) throw new Error(t("commercialProposals.titleRequired"));
      if (payloadItems.some((i) => !i.product_or_service_name)) {
        throw new Error(t("commercialProposals.itemNameRequired"));
      }
      return salesProposalsApi.create({
        title: title.trim(),
        customer_id: customerId || null,
        lead_id: leadId || null,
        deal_id: dealId || null,
        issue_date: new Date(issueDate).toISOString(),
        valid_until: validUntil ? new Date(validUntil).toISOString() : null,
        currency,
        discount: proposalDiscount,
        tax,
        notes: notes.trim() || null,
        terms: terms.trim() || null,
        items: payloadItems,
      }).then((r) => r.data);
    },
    onSuccess: (p) => {
      toast.success(t("commercialProposals.created"));
      router.push(`/proposals/${p.id}`);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const subtotal = useMemo(() => items.reduce((s, i) => s + calcItemTotal(i), 0), [items]);
  const total = useMemo(() => Math.max(subtotal - proposalDiscount, 0) + tax, [subtotal, proposalDiscount, tax]);

  const customers = normalizeList(customersData);
  const leads = normalizeList(leadsData);
  const deals = normalizeList(dealsData);

  function updateItem(key: string, patch: Partial<ItemRow>) {
    setItems((prev) => prev.map((i) => (i.key === key ? { ...i, ...patch } : i)));
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <Link href="/proposals" className="text-xs text-gray-500 hover:text-gray-800 flex items-center gap-1 mb-2">
          <ArrowLeft size={12} />
          {t("commercialProposals.backToList")}
        </Link>
        <h1 className="page-title">{t("commercialProposals.createTitle")}</h1>
        <p className="text-sm text-gray-500 mt-1">{t("commercialProposals.createSubtitle")}</p>
      </div>

      {(searchParams.get("lead_id") || searchParams.get("deal_id")) && (
        <div className="card p-4 bg-brand-50/50 border-brand-100 flex flex-wrap gap-2">
          {searchParams.get("lead_id") && (
            <button
              type="button"
              disabled={fromLeadMutation.isPending}
              onClick={() => fromLeadMutation.mutate(searchParams.get("lead_id")!)}
              className="btn-secondary text-sm"
            >
              {fromLeadMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : t("commercialProposals.quickFromLead")}
            </button>
          )}
          {searchParams.get("deal_id") && (
            <button
              type="button"
              disabled={fromDealMutation.isPending}
              onClick={() => fromDealMutation.mutate(searchParams.get("deal_id")!)}
              className="btn-secondary text-sm"
            >
              {fromDealMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : t("commercialProposals.quickFromDeal")}
            </button>
          )}
        </div>
      )}

      <div className="card p-4 space-y-4">
        <div className="grid sm:grid-cols-2 gap-3">
          <label className="block text-xs space-y-1 sm:col-span-2">
            <span className="text-gray-600 font-medium">{t("commercialProposals.colTitle")} *</span>
            <input className="input w-full" value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="block text-xs space-y-1">
            <span className="text-gray-600 font-medium">{t("commercialProposals.customer")}</span>
            <select className="input w-full" value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
              <option value="">{t("commercialProposals.none")}</option>
              {customers.map((c) => (
                <option key={c.id} value={c.id}>{c.name}{c.company ? ` — ${c.company}` : ""}</option>
              ))}
            </select>
          </label>
          <label className="block text-xs space-y-1">
            <span className="text-gray-600 font-medium">{t("commercialProposals.linkedLead")}</span>
            <select className="input w-full" value={leadId} onChange={(e) => setLeadId(e.target.value)}>
              <option value="">{t("commercialProposals.none")}</option>
              {leads.map((l) => (
                <option key={l.id} value={l.id}>{l.name}{l.company ? ` — ${l.company}` : ""}</option>
              ))}
            </select>
          </label>
          <label className="block text-xs space-y-1">
            <span className="text-gray-600 font-medium">{t("commercialProposals.linkedDeal")}</span>
            <select className="input w-full" value={dealId} onChange={(e) => setDealId(e.target.value)}>
              <option value="">{t("commercialProposals.none")}</option>
              {deals.map((d) => (
                <option key={d.id} value={d.id}>{d.title}</option>
              ))}
            </select>
          </label>
          <label className="block text-xs space-y-1">
            <span className="text-gray-600 font-medium">{t("commercialProposals.issueDate")}</span>
            <input type="date" className="input w-full" value={issueDate} onChange={(e) => setIssueDate(e.target.value)} />
          </label>
          <label className="block text-xs space-y-1">
            <span className="text-gray-600 font-medium">{t("commercialProposals.validUntil")}</span>
            <input type="date" className="input w-full" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} />
          </label>
          <label className="block text-xs space-y-1">
            <span className="text-gray-600 font-medium">{t("commercialProposals.currency")}</span>
            <select className="input w-full" value={currency} onChange={(e) => setCurrency(e.target.value)}>
              {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
        </div>
      </div>

      <div className="card p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900">{t("commercialProposals.lineItems")}</h2>
          <button type="button" onClick={() => setItems((p) => [...p, emptyItem()])} className="btn-secondary text-xs flex items-center gap-1">
            <Plus size={12} /> {t("commercialProposals.addItem")}
          </button>
        </div>
        {items.map((item, idx) => (
          <div key={item.key} className="border border-gray-100 rounded-lg p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-gray-500">#{idx + 1}</span>
              {items.length > 1 && (
                <button type="button" onClick={() => setItems((p) => p.filter((i) => i.key !== item.key))} className="text-gray-400 hover:text-red-600">
                  <Trash2 size={14} />
                </button>
              )}
            </div>
            <input
              className="input w-full text-sm"
              placeholder={t("commercialProposals.itemName")}
              value={item.product_or_service_name}
              onChange={(e) => updateItem(item.key, { product_or_service_name: e.target.value })}
            />
            <textarea
              className="input w-full text-sm min-h-[60px]"
              placeholder={t("commercialProposals.itemDescription")}
              value={item.description ?? ""}
              onChange={(e) => updateItem(item.key, { description: e.target.value })}
            />
            <div className="grid grid-cols-4 gap-2">
              <label className="text-xs space-y-1">
                <span className="text-gray-500">{t("commercialProposals.quantity")}</span>
                <input type="number" min={0.0001} step="any" className="input w-full" value={item.quantity}
                  onChange={(e) => updateItem(item.key, { quantity: Number(e.target.value) })} />
              </label>
              <label className="text-xs space-y-1">
                <span className="text-gray-500">{t("commercialProposals.unitPrice")}</span>
                <input type="number" min={0} step="0.01" className="input w-full" value={item.unit_price}
                  onChange={(e) => updateItem(item.key, { unit_price: Number(e.target.value) })} />
              </label>
              <label className="text-xs space-y-1">
                <span className="text-gray-500">{t("commercialProposals.itemDiscount")}</span>
                <input type="number" min={0} step="0.01" className="input w-full" value={item.discount}
                  onChange={(e) => updateItem(item.key, { discount: Number(e.target.value) })} />
              </label>
              <label className="text-xs space-y-1">
                <span className="text-gray-500">{t("commercialProposals.itemTotal")}</span>
                <div className="input w-full bg-gray-50 text-gray-700">{calcItemTotal(item).toFixed(2)}</div>
              </label>
            </div>
          </div>
        ))}
      </div>

      <div className="card p-4 grid sm:grid-cols-2 gap-4">
        <label className="block text-xs space-y-1">
          <span className="text-gray-600 font-medium">{t("commercialProposals.proposalDiscount")}</span>
          <input type="number" min={0} step="0.01" className="input w-full" value={proposalDiscount}
            onChange={(e) => setProposalDiscount(Number(e.target.value))} />
        </label>
        <label className="block text-xs space-y-1">
          <span className="text-gray-600 font-medium">{t("commercialProposals.tax")}</span>
          <input type="number" min={0} step="0.01" className="input w-full" value={tax}
            onChange={(e) => setTax(Number(e.target.value))} />
        </label>
        <label className="block text-xs space-y-1 sm:col-span-2">
          <span className="text-gray-600 font-medium">{t("commercialProposals.notes")}</span>
          <textarea className="input w-full min-h-[60px]" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        <label className="block text-xs space-y-1 sm:col-span-2">
          <span className="text-gray-600 font-medium">{t("commercialProposals.terms")}</span>
          <textarea className="input w-full min-h-[80px]" value={terms} onChange={(e) => setTerms(e.target.value)} />
        </label>
        <div className="sm:col-span-2 bg-gray-50 rounded-lg p-4 space-y-1 text-sm">
          <div className="flex justify-between"><span>{t("commercialProposals.subtotal")}</span><span>{subtotal.toFixed(2)} {currency}</span></div>
          <div className="flex justify-between text-gray-500"><span>{t("commercialProposals.proposalDiscount")}</span><span>-{proposalDiscount.toFixed(2)}</span></div>
          <div className="flex justify-between text-gray-500"><span>{t("commercialProposals.tax")}</span><span>+{tax.toFixed(2)}</span></div>
          <div className="flex justify-between font-semibold text-base pt-2 border-t border-gray-200">
            <span>{t("commercialProposals.total")}</span><span>{total.toFixed(2)} {currency}</span>
          </div>
        </div>
      </div>

      <button
        type="button"
        disabled={createMutation.isPending}
        onClick={() => createMutation.mutate()}
        className="btn-primary w-full flex items-center justify-center gap-2"
      >
        {createMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : t("commercialProposals.saveDraft")}
      </button>
    </div>
  );
}

export default function NewProposalPage() {
  const { t } = useTranslation();
  return (
    <Suspense fallback={<LoadingState message={t("commercialProposals.loading")} className="min-h-[40vh]" />}>
      <ProposalForm />
    </Suspense>
  );
}
