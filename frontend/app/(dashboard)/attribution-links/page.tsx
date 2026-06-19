"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Link2, Loader2, Plus } from "lucide-react";
import toast from "react-hot-toast";
import {
  attributionLinksApi,
  campaignsApi,
  clientsApi,
  Client,
  Campaign,
  Partner,
  partnersApi,
  Product,
  productsApi,
  AttributionLink,
  AttributionLinkChannel,
  ATTRIBUTION_CHANNEL_LABELS,
  normalizeList,
} from "@/lib/api";
import { EmptyState } from "@/components/ui/PageStates";

function formatMoney(val: number | string | null | undefined): string {
  if (val == null || val === "") return "—";
  const n = typeof val === "string" ? parseFloat(val) : val;
  if (Number.isNaN(n)) return String(val);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

function LinkRow({ link }: { link: AttributionLink }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(link.tracking_url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    toast.success("Tracking URL copied");
  };

  return (
    <div className="card p-4 space-y-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-gray-900">{link.title}</p>
          <p className="text-xs text-gray-500">
            {ATTRIBUTION_CHANNEL_LABELS[link.channel]}
            {link.client_name ? ` · ${link.client_name}` : ""}
            {link.campaign_name ? ` · ${link.campaign_name}` : ""}
            {link.product_name ? ` · ${link.product_name}` : ""}
          </p>
        </div>
        <span className="text-[10px] px-2 py-0.5 rounded border bg-gray-50 capitalize">{link.channel}</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-xs">
        <div><p className="text-gray-400">Clicks</p><p className="font-medium tabular-nums">{link.clicks_count}</p></div>
        <div><p className="text-gray-400">Leads</p><p className="font-medium tabular-nums">{link.leads_count}</p></div>
        <div><p className="text-gray-400">Conv.</p><p className="font-medium tabular-nums">{link.conversion_rate}%</p></div>
        <div><p className="text-gray-400">Revenue</p><p className="font-medium tabular-nums">{formatMoney(link.linked_revenue)}</p></div>
        <div><p className="text-gray-400">Won</p><p className="font-medium tabular-nums">{link.won_deals_count}</p></div>
      </div>
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <code className="text-[11px] bg-gray-50 px-2 py-1 rounded border truncate max-w-full">{link.tracking_url}</code>
        <button type="button" onClick={copy} className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1">
          <Copy size={12} />
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}

export default function AttributionLinksPage() {
  const searchParams = useSearchParams();
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [clientId, setClientId] = useState("");
  const [filterClient, setFilterClient] = useState("");
  const [form, setForm] = useState({
    client_id: "",
    campaign_id: "",
    product_id: "",
    partner_id: "",
    channel: "telegram" as AttributionLinkChannel,
    destination_url: "",
    title: "",
    description: "",
  });

  useEffect(() => {
    const c = searchParams.get("client");
    const camp = searchParams.get("campaign");
    const prod = searchParams.get("product");
    const partner = searchParams.get("partner");
    if (c) {
      setClientId(c);
      setFilterClient(c);
      setForm((f) => ({ ...f, client_id: c, campaign_id: camp ?? "", product_id: prod ?? "", partner_id: partner ?? "" }));
      setShowForm(true);
    }
  }, [searchParams]);

  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list({ limit: 200 }).then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clients);

  const { data: campaigns } = useQuery({
    queryKey: ["campaigns-attrib", form.client_id],
    queryFn: () => campaignsApi.list({ client_id: form.client_id, limit: 200 }).then((r) => r.data),
    enabled: !!form.client_id,
  });

  const { data: products } = useQuery({
    queryKey: ["products-attrib", form.client_id],
    queryFn: () => productsApi.list({ client_id: form.client_id, limit: 200 }).then((r) => r.data),
    enabled: !!form.client_id,
  });

  const { data: partners } = useQuery({
    queryKey: ["partners-attrib"],
    queryFn: () => partnersApi.list({ limit: 200 }).then((r) => r.data),
  });

  const { data: linksData, isLoading } = useQuery({
    queryKey: ["attribution-links", filterClient],
    queryFn: () =>
      attributionLinksApi.list({ client_id: filterClient || undefined, limit: 100 }).then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      attributionLinksApi.create({
        client_id: form.client_id,
        channel: form.channel,
        destination_url: form.destination_url,
        title: form.title,
        campaign_id: form.campaign_id || null,
        product_id: form.product_id || null,
        partner_id: form.partner_id || null,
        description: form.description || null,
      }).then((r) => r.data),
    onSuccess: (link) => {
      qc.invalidateQueries({ queryKey: ["attribution-links"] });
      setShowForm(false);
      toast.success(`Link created: ${link.code}`);
    },
    onError: (err: Error) => toast.error(err.message || "Failed to create link"),
  });

  const links = normalizeList<AttributionLink>(linksData);

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Link2 size={22} className="text-teal-600" />
            Attribution Links
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Track clicks and route buyers into controlled channels — redirect only, no auto messaging
          </p>
        </div>
        <button type="button" className="btn-primary text-sm flex items-center gap-1" onClick={() => setShowForm((v) => !v)}>
          <Plus size={14} />
          Create link
        </button>
      </div>

      <div className="card p-4">
        <select className="input text-sm w-full sm:w-64" value={filterClient} onChange={(e) => setFilterClient(e.target.value)}>
          <option value="">All clients</option>
          {clientOptions.map((c) => (
            <option key={c.id} value={c.id}>{c.company_name}</option>
          ))}
        </select>
      </div>

      {showForm && (
        <div className="card p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-900">New tracking link</p>
          <select
            className="input text-sm w-full"
            value={form.client_id}
            onChange={(e) => setForm({ ...form, client_id: e.target.value, campaign_id: "", product_id: "" })}
          >
            <option value="">Client *</option>
            {clientOptions.map((c) => (
              <option key={c.id} value={c.id}>{c.company_name}</option>
            ))}
          </select>
          <div className="grid sm:grid-cols-2 gap-2">
            <select className="input text-sm" value={form.campaign_id} onChange={(e) => setForm({ ...form, campaign_id: e.target.value })} disabled={!form.client_id}>
              <option value="">Campaign (optional)</option>
              {normalizeList<Campaign>(campaigns).map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            <select className="input text-sm" value={form.product_id} onChange={(e) => setForm({ ...form, product_id: e.target.value })} disabled={!form.client_id}>
              <option value="">Product (optional)</option>
              {normalizeList<Product>(products).map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
          <select className="input text-sm w-full" value={form.partner_id} onChange={(e) => setForm({ ...form, partner_id: e.target.value })}>
            <option value="">Partner (optional)</option>
            {normalizeList<Partner>(partners).map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <div className="grid sm:grid-cols-2 gap-2">
            <select className="input text-sm" value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value as AttributionLinkChannel })}>
              {(Object.keys(ATTRIBUTION_CHANNEL_LABELS) as AttributionLinkChannel[]).map((ch) => (
                <option key={ch} value={ch}>{ATTRIBUTION_CHANNEL_LABELS[ch]}</option>
              ))}
            </select>
            <input className="input text-sm" placeholder="Title *" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </div>
          <input className="input text-sm w-full" placeholder="Destination URL *" value={form.destination_url} onChange={(e) => setForm({ ...form, destination_url: e.target.value })} />
          <textarea className="input text-sm w-full min-h-[60px]" placeholder="Description (optional)" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          <button
            type="button"
            className="btn-primary text-sm w-full sm:w-auto"
            disabled={!form.client_id || !form.title.trim() || !form.destination_url.trim() || createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            {createMutation.isPending ? <Loader2 size={14} className="animate-spin inline" /> : "Create tracking link"}
          </button>
        </div>
      )}

      <div className="space-y-2">
        {isLoading ? (
          <p className="text-sm text-gray-500">Loading links…</p>
        ) : links.length === 0 ? (
          <EmptyState title="No attribution links" description="Create a link to track clicks and attribute leads." />
        ) : (
          links.map((link) => <LinkRow key={link.id} link={link} />)
        )}
      </div>
    </div>
  );
}
