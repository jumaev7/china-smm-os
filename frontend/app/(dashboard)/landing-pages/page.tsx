"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, FileText, Loader2, Plus } from "lucide-react";
import toast from "react-hot-toast";
import {
  attributionLinksApi,
  campaignsApi,
  clientsApi,
  Client,
  landingPagesApi,
  LandingPage,
  LandingPageStatus,
  productsApi,
  normalizeList,
} from "@/lib/api";
import { EmptyState } from "@/components/ui/PageStates";

const STATUS_LABELS: Record<LandingPageStatus, string> = {
  draft: "Draft",
  published: "Published",
  archived: "Archived",
};

function PageRow({ page }: { page: LandingPage }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(page.public_url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    toast.success("Landing page URL copied");
  };

  return (
    <div className="card p-4 space-y-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-gray-900">{page.title}</p>
          <p className="text-xs text-gray-500">
            {page.client_name ? page.client_name : "—"}
            {page.product_name ? ` · ${page.product_name}` : ""}
            {page.campaign_name ? ` · ${page.campaign_name}` : ""}
          </p>
        </div>
        <span className="text-[10px] px-2 py-0.5 rounded border bg-gray-50 capitalize">
          {STATUS_LABELS[page.status]}
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
        <div>
          <p className="text-gray-400">Leads</p>
          <p className="font-medium tabular-nums">{page.leads_count}</p>
        </div>
        <div className="col-span-2">
          <p className="text-gray-400">Slug</p>
          <p className="font-medium">/l/{page.slug}</p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <code className="text-[11px] bg-gray-50 px-2 py-1 rounded border truncate max-w-full">{page.public_url}</code>
        <button type="button" onClick={copy} className="text-xs text-brand-700 hover:text-brand-900 flex items-center gap-1">
          <Copy size={12} />
          {copied ? "Copied" : "Copy link"}
        </button>
      </div>
    </div>
  );
}

export default function LandingPagesPage() {
  const searchParams = useSearchParams();
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [filterClient, setFilterClient] = useState("");
  const [form, setForm] = useState({
    client_id: "",
    campaign_id: "",
    product_id: "",
    attribution_link_id: "",
    slug: "",
    title: "",
    subtitle: "",
    description: "",
    cta_text: "Get in touch",
    status: "draft" as LandingPageStatus,
  });

  useEffect(() => {
    const c = searchParams.get("client");
    const camp = searchParams.get("campaign");
    const prod = searchParams.get("product");
    if (c) {
      setFilterClient(c);
      setForm((f) => ({
        ...f,
        client_id: c,
        campaign_id: camp ?? "",
        product_id: prod ?? "",
      }));
      setShowForm(true);
    }
  }, [searchParams]);

  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list({ limit: 200 }).then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clients);

  const { data: campaigns } = useQuery({
    queryKey: ["campaigns-landing", form.client_id],
    queryFn: () => campaignsApi.list({ client_id: form.client_id, limit: 200 }).then((r) => r.data),
    enabled: !!form.client_id,
  });

  const { data: products } = useQuery({
    queryKey: ["products-landing", form.client_id],
    queryFn: () => productsApi.list({ client_id: form.client_id, limit: 200 }).then((r) => r.data),
    enabled: !!form.client_id,
  });

  const { data: attributionLinks } = useQuery({
    queryKey: ["attribution-links-landing", form.client_id],
    queryFn: () => attributionLinksApi.list({ client_id: form.client_id, limit: 200 }).then((r) => r.data),
    enabled: !!form.client_id,
  });

  const { data: pages, isLoading } = useQuery({
    queryKey: ["landing-pages", filterClient],
    queryFn: () =>
      landingPagesApi
        .list({ client_id: filterClient || undefined, limit: 200 })
        .then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      landingPagesApi.create({
        client_id: form.client_id,
        slug: form.slug,
        title: form.title,
        subtitle: form.subtitle || null,
        description: form.description || null,
        cta_text: form.cta_text || "Get in touch",
        campaign_id: form.campaign_id || null,
        product_id: form.product_id || null,
        attribution_link_id: form.attribution_link_id || null,
        status: form.status,
      }),
    onSuccess: () => {
      toast.success("Landing page created");
      qc.invalidateQueries({ queryKey: ["landing-pages"] });
      setShowForm(false);
      setForm({
        client_id: form.client_id,
        campaign_id: "",
        product_id: "",
        attribution_link_id: "",
        slug: "",
        title: "",
        subtitle: "",
        description: "",
        cta_text: "Get in touch",
        status: "draft",
      });
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || "Could not create landing page");
    },
  });

  const items = normalizeList<LandingPage>(pages);

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <FileText size={22} className="text-brand-600" />
            Landing Pages
          </h1>
          <p className="text-sm text-gray-500 mt-1">Public lead capture pages for products and campaigns</p>
        </div>
        <button type="button" className="btn-primary flex items-center gap-1.5" onClick={() => setShowForm((v) => !v)}>
          <Plus size={16} />
          New landing page
        </button>
      </div>

      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <label className="label">Filter by client</label>
          <select
            className="input w-48"
            value={filterClient}
            onChange={(e) => setFilterClient(e.target.value)}
          >
            <option value="">All clients</option>
            {clientOptions.map((c) => (
              <option key={c.id} value={c.id}>{c.company_name}</option>
            ))}
          </select>
        </div>
      </div>

      {showForm && (
        <div className="card p-5 space-y-4">
          <h2 className="text-sm font-semibold text-gray-900">Create landing page</h2>
          <div className="grid sm:grid-cols-2 gap-4">
            <div>
              <label className="label">Client *</label>
              <select
                className="input"
                value={form.client_id}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    client_id: e.target.value,
                    campaign_id: "",
                    product_id: "",
                    attribution_link_id: "",
                  }))
                }
              >
                <option value="">Select client</option>
                {clientOptions.map((c) => (
                  <option key={c.id} value={c.id}>{c.company_name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Status</label>
              <select
                className="input"
                value={form.status}
                onChange={(e) => setForm((f) => ({ ...f, status: e.target.value as LandingPageStatus }))}
              >
                <option value="draft">Draft</option>
                <option value="published">Published</option>
                <option value="archived">Archived</option>
              </select>
            </div>
            <div>
              <label className="label">Campaign</label>
              <select
                className="input"
                value={form.campaign_id}
                onChange={(e) => setForm((f) => ({ ...f, campaign_id: e.target.value }))}
                disabled={!form.client_id}
              >
                <option value="">None</option>
                {normalizeList(campaigns).map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Product</label>
              <select
                className="input"
                value={form.product_id}
                onChange={(e) => setForm((f) => ({ ...f, product_id: e.target.value }))}
                disabled={!form.client_id}
              >
                <option value="">None</option>
                {normalizeList(products).map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
            <div className="sm:col-span-2">
              <label className="label">Attribution link (optional)</label>
              <select
                className="input"
                value={form.attribution_link_id}
                onChange={(e) => setForm((f) => ({ ...f, attribution_link_id: e.target.value }))}
                disabled={!form.client_id}
              >
                <option value="">None</option>
                {normalizeList(attributionLinks).map((l) => (
                  <option key={l.id} value={l.id}>{l.title} ({l.code})</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Title *</label>
              <input
                className="input"
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                placeholder="Product inquiry"
              />
            </div>
            <div>
              <label className="label">Slug *</label>
              <input
                className="input"
                value={form.slug}
                onChange={(e) => setForm((f) => ({ ...f, slug: e.target.value }))}
                placeholder="my-product-inquiry"
              />
            </div>
            <div className="sm:col-span-2">
              <label className="label">Subtitle</label>
              <input
                className="input"
                value={form.subtitle}
                onChange={(e) => setForm((f) => ({ ...f, subtitle: e.target.value }))}
              />
            </div>
            <div className="sm:col-span-2">
              <label className="label">Description</label>
              <textarea
                className="input min-h-[80px]"
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              />
            </div>
            <div>
              <label className="label">CTA button text</label>
              <input
                className="input"
                value={form.cta_text}
                onChange={(e) => setForm((f) => ({ ...f, cta_text: e.target.value }))}
              />
            </div>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-primary"
              disabled={!form.client_id || !form.title || !form.slug || createMutation.isPending}
              onClick={() => createMutation.mutate()}
            >
              {createMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : "Create"}
            </button>
            <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="animate-spin text-brand-600" size={24} />
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          title="No landing pages yet"
          description="Create a public page to capture buyer leads from products or campaigns."
        />
      ) : (
        <div className="space-y-3">
          {items.map((page) => (
            <PageRow key={page.id} page={page} />
          ))}
        </div>
      )}
    </div>
  );
}
