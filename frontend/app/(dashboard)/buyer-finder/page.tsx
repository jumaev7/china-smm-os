"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Search, Sparkles } from "lucide-react";
import toast from "react-hot-toast";
import { buyerFinderApi, productsApi, normalizeList, type Product, type BuyerRecommendation } from "@/lib/api";
import { ResultsTable } from "@/components/buyer-finder/BuyerFinderPanel";
import { EmptyState, LoadingState } from "@/components/ui/PageStates";

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

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
          <Search size={22} className="text-indigo-600" />
          Buyer Finder
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Recommend likely buyers and profiles for your products — advisory only
        </p>
      </div>

      <div className="card p-4 space-y-4">
        <p className="text-sm font-semibold text-gray-900">Product selector</p>
        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className="label">Filter by client</label>
            <select
              className="input"
              value={clientFilter}
              onChange={(e) => {
                setClientFilter(e.target.value);
                setProductId("");
              }}
            >
              <option value="">All clients</option>
              {clients.map(([id, name]) => (
                <option key={id} value={id}>{name ?? id}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Product</label>
            <select
              className="input"
              value={productId}
              onChange={(e) => setProductId(e.target.value)}
              disabled={productsLoading}
            >
              <option value="">Select a product</option>
              {productList.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}{p.category ? ` · ${p.category}` : ""}
                </option>
              ))}
            </select>
          </div>
        </div>

        {productId && (
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {selectedProduct && (
              <Link
                href={`/products/${productId}`}
                className="text-xs text-brand-700 hover:text-brand-900"
              >
                View product →
              </Link>
            )}
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
          </div>
        )}
      </div>

      {!productId ? (
        <EmptyState
          title="Select a product"
          description="Choose a product above to view or generate buyer recommendations."
        />
      ) : isLoading && !analyzeMutation.data ? (
        <LoadingState message="Loading recommendations…" />
      ) : (
        <div className="card p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-900">Recommended buyers</p>
          {selectedProduct && (
            <p className="text-xs text-gray-500">
              {selectedProduct.name}
              {selectedProduct.category ? ` · ${selectedProduct.category}` : ""}
              {data?.total != null ? ` · ${data.total} saved recommendations` : ""}
            </p>
          )}
          <ResultsTable
            items={items}
            demoMode={analyzeMutation.data?.demo_mode ?? data?.demo_mode}
          />
        </div>
      )}
    </div>
  );
}
