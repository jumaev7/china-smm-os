"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Building2,
  Filter,
  Loader2,
  Search,
  Shield,
  Sparkles,
  Target,
  Users,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  buyerFinderApi,
  productsApi,
  normalizeList,
  type Product,
  type BuyerRecommendation,
} from "@/lib/api";
import { ResultsTable } from "@/components/buyer-finder/BuyerFinderPanel";
import { EmptyState, LoadingState } from "@/components/ui/PageStates";
import {
  ActionBar,
  ExecutiveKpiBar,
  PageHeader,
  PageShell,
  SectionCard,
} from "@/components/ui/design-system";

export default function BuyerFinderPage() {
  const qc = useQueryClient();
  const [productId, setProductId] = useState("");
  const [clientFilter, setClientFilter] = useState("");

  const { data: products, isLoading: productsLoading } = useQuery({
    queryKey: ["products-buyer-finder", clientFilter],
    queryFn: () =>
      productsApi
        .list({ client_id: clientFilter || undefined, limit: 200, active: true })
        .then((r) => r.data),
  });

  const { data, isLoading } = useQuery({
    queryKey: ["buyer-finder", productId],
    queryFn: () => buyerFinderApi.getForProduct(productId).then((r) => r.data),
    enabled: !!productId,
  });

  const analyzeMutation = useMutation({
    mutationFn: () => buyerFinderApi.analyze(productId).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["buyer-finder", productId] });
      qc.invalidateQueries({ queryKey: ["export-dashboard"] });
      toast.success("Buyer analysis complete");
    },
    onError: (err: Error) => toast.error(err.message || "Analysis failed"),
  });

  const productList = normalizeList<Product>(products);
  const clients = Array.from(
    new Map(productList.map((p) => [p.client_id, p.company_name])).entries(),
  );

  const items = normalizeList<BuyerRecommendation>(analyzeMutation.data ?? data);
  const selectedProduct = productList.find((p) => p.id === productId);

  const stats = useMemo(() => {
    if (items.length === 0) {
      return { total: 0, highMatch: 0, avgScore: 0, countries: 0 };
    }
    const highMatch = items.filter((i) => i.score >= 70).length;
    const avgScore = Math.round(items.reduce((s, i) => s + i.score, 0) / items.length);
    const countries = new Set(items.map((i) => i.country).filter(Boolean)).size;
    return { total: items.length, highMatch, avgScore, countries };
  }, [items]);

  return (
    <PageShell wide>
      <PageHeader
        title="Buyer Search"
        subtitle="Intelligence-driven buyer matching for your product catalog — advisory only, no automatic outreach."
        icon={Search}
        iconClassName="text-sky-400"
        actions={
          productId ? (
            <button
              type="button"
              className="btn-primary text-sm flex items-center gap-1.5"
              disabled={analyzeMutation.isPending}
              onClick={() => analyzeMutation.mutate()}
            >
              {analyzeMutation.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Sparkles size={14} />
              )}
              Analyze buyers
            </button>
          ) : undefined
        }
      />

      <div className="rounded-xl border border-sky-200/80 bg-sky-50/40 px-4 py-3 flex items-start gap-2 text-xs text-sky-900 dark-tenant:border-sky-500/20 dark-tenant:bg-sky-500/10 dark-tenant:text-sky-200">
        <Shield className="w-4 h-4 shrink-0 mt-0.5 text-sky-600 dark-tenant:text-sky-400" />
        <span>
          Premium buyer intelligence workspace. Recommendations are heuristic matches — review manually before outreach.
        </span>
      </div>

      <SectionCard title="Product & catalog filters" icon={Filter} iconClassName="text-violet-400">
        <ActionBar>
          <div className="grid sm:grid-cols-2 gap-3 flex-1 min-w-0">
            <div>
              <label className="label">Filter by client</label>
              <select
                className="input text-sm"
                value={clientFilter}
                onChange={(e) => {
                  setClientFilter(e.target.value);
                  setProductId("");
                }}
              >
                <option value="">All clients</option>
                {clients.map(([id, name]) => (
                  <option key={id} value={id}>
                    {name ?? id}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Product</label>
              <select
                className="input text-sm"
                value={productId}
                onChange={(e) => setProductId(e.target.value)}
                disabled={productsLoading}
              >
                <option value="">Select a product</option>
                {productList.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                    {p.category ? ` · ${p.category}` : ""}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </ActionBar>

        {productId && selectedProduct && (
          <div className="flex flex-wrap items-center gap-3 text-xs text-gray-600 dark-tenant:text-slate-400">
            <span className="inline-flex items-center gap-1">
              <Building2 size={12} className="text-violet-400" />
              {selectedProduct.name}
              {selectedProduct.category ? ` · ${selectedProduct.category}` : ""}
            </span>
            <Link
              href={`/products/${productId}`}
              className="text-brand-700 hover:text-brand-900 dark-tenant:text-violet-400 dark-tenant:hover:text-violet-300 transition-colors"
            >
              View product →
            </Link>
          </div>
        )}
      </SectionCard>

      {productId && items.length > 0 && (
        <ExecutiveKpiBar
          items={[
            { label: "Matches", value: stats.total },
            { label: "High match (70+)", value: stats.highMatch },
            { label: "Avg score", value: stats.avgScore },
            { label: "Countries", value: stats.countries },
            {
              label: "Saved",
              value: data?.total ?? stats.total,
            },
          ]}
        />
      )}

      {!productsLoading && productList.length === 0 ? (
        <EmptyState
          title="No products in catalog"
          description="Add products to your client catalog, then return here to find matching buyers."
        />
      ) : !productId ? (
        <EmptyState
          title="Select a product"
          description="Choose a product above to view or generate buyer recommendations."
        />
      ) : isLoading && !analyzeMutation.data ? (
        <LoadingState message="Loading recommendations…" />
      ) : (
        <SectionCard
          title="Recommended buyers"
          icon={Users}
          iconClassName="text-emerald-400"
          footer={
            <p className="text-[10px] text-gray-400 dark-tenant:text-slate-500 flex items-center gap-1">
              <Target size={10} />
              Advisory only — no automatic CRM updates or outreach.
            </p>
          }
        >
          {selectedProduct && (
            <p className="text-xs text-gray-500 dark-tenant:text-slate-400 -mt-2">
              {selectedProduct.name}
              {selectedProduct.category ? ` · ${selectedProduct.category}` : ""}
              {data?.total != null ? ` · ${data.total} saved recommendations` : ""}
            </p>
          )}
          <ResultsTable
            items={items}
            demoMode={analyzeMutation.data?.demo_mode ?? data?.demo_mode}
            productId={productId}
          />
        </SectionCard>
      )}
    </PageShell>
  );
}
