"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Loader2, Package, Trash2 } from "lucide-react";
import toast from "react-hot-toast";
import { productsApi } from "@/lib/api";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import { PartnerMatchPanel } from "@/components/partners/PartnerMatchPanel";
import { ExportAnalysisPanel } from "@/components/export/ExportAnalysisPanel";
import { BuyerFinderPanel } from "@/components/buyer-finder/BuyerFinderPanel";
import { AskAiAboutItem } from "@/components/assistant/AskAiAboutItem";

export default function ProductDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    name: "",
    sku: "",
    category: "",
    description: "",
    moq: "",
    unit_price: "",
    currency: "USD",
    active: true,
  });

  const { data: product, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["product", id],
    queryFn: () => productsApi.get(id).then((r) => r.data),
  });

  const updateMutation = useMutation({
    mutationFn: () =>
      productsApi.update(id, {
        name: form.name,
        sku: form.sku || null,
        category: form.category || null,
        description: form.description || null,
        moq: form.moq ? parseInt(form.moq, 10) : null,
        unit_price: form.unit_price ? parseFloat(form.unit_price) : null,
        currency: form.currency,
        active: form.active,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["product", id] });
      qc.invalidateQueries({ queryKey: ["products"] });
      setEditing(false);
      toast.success("Product updated");
    },
    onError: (err: Error) => toast.error(err.message || "Update failed"),
  });

  const deleteMutation = useMutation({
    mutationFn: () => productsApi.delete(id),
    onSuccess: () => {
      toast.success("Product deleted");
      window.location.href = "/products";
    },
    onError: (err: Error) => toast.error(err.message || "Delete failed"),
  });

  if (isLoading) return <LoadingState message="Loading product…" />;
  if (isError || !product) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Product not found"}
        onRetry={() => refetch()}
      />
    );
  }

  const startEdit = () => {
    setForm({
      name: product.name,
      sku: product.sku ?? "",
      category: product.category ?? "",
      description: product.description ?? "",
      moq: product.moq != null ? String(product.moq) : "",
      unit_price: product.unit_price != null ? String(product.unit_price) : "",
      currency: product.currency,
      active: product.active,
    });
    setEditing(true);
  };

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <div>
        <Link href="/products" className="text-xs text-brand-700 hover:text-brand-900 inline-flex items-center gap-1 mb-2">
          <ArrowLeft size={12} />
          Back to products
        </Link>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
              <Package size={22} className="text-brand-600" />
              {product.name}
            </h1>
            <p className="text-sm text-gray-500 mt-1">{product.company_name}</p>
          </div>
          <div className="flex gap-2 flex-wrap items-center">
            <AskAiAboutItem entityLabel={product.name} />
            <Link
              href={`/proposals/new?client_id=${product.client_id}&product_id=${id}`}
              className="text-xs px-3 py-1.5 rounded-lg border border-indigo-200 text-indigo-800 hover:bg-indigo-50"
            >
              Generate proposal
            </Link>
            <Link
              href={`/attribution-links?client=${product.client_id}&product=${id}`}
              className="text-xs px-3 py-1.5 rounded-lg border border-teal-200 text-teal-800 hover:bg-teal-50"
            >
              Create tracking link
            </Link>
            {!editing && (
              <button type="button" className="btn-secondary text-sm" onClick={startEdit}>
                Edit
              </button>
            )}
            <button
              type="button"
              className="text-sm text-red-600 hover:text-red-800 flex items-center gap-1 px-2"
              onClick={() => {
                if (window.confirm("Delete this product?")) deleteMutation.mutate();
              }}
            >
              <Trash2 size={14} />
              Delete
            </button>
          </div>
        </div>
      </div>

      {editing ? (
        <div className="card p-4 space-y-3">
          <input className="input text-sm" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <div className="grid sm:grid-cols-2 gap-3">
            <input className="input text-sm" placeholder="SKU" value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} />
            <input className="input text-sm" placeholder="Category" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
            <input className="input text-sm" placeholder="Unit price" type="number" value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} />
            <input className="input text-sm" placeholder="MOQ" type="number" value={form.moq} onChange={(e) => setForm({ ...form, moq: e.target.value })} />
          </div>
          <textarea className="input text-sm min-h-[100px]" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />
            Active
          </label>
          <div className="flex gap-2">
            <button type="button" className="btn-primary text-sm" disabled={updateMutation.isPending} onClick={() => updateMutation.mutate()}>
              {updateMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : "Save"}
            </button>
            <button type="button" className="btn-secondary text-sm" onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </div>
      ) : (
        <div className="card p-4 grid sm:grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-[10px] uppercase text-gray-400">SKU</p>
            <p className="text-gray-900">{product.sku ?? "—"}</p>
          </div>
          <div>
            <p className="text-[10px] uppercase text-gray-400">Category</p>
            <p className="text-gray-900">{product.category ?? "—"}</p>
          </div>
          <div>
            <p className="text-[10px] uppercase text-gray-400">Price</p>
            <p className="text-gray-900 tabular-nums">
              {product.unit_price != null ? `${product.unit_price} ${product.currency}` : "—"}
            </p>
          </div>
          <div>
            <p className="text-[10px] uppercase text-gray-400">MOQ</p>
            <p className="text-gray-900 tabular-nums">{product.moq ?? "—"}</p>
          </div>
          <div className="sm:col-span-2">
            <p className="text-[10px] uppercase text-gray-400">Description</p>
            <p className="text-gray-700 whitespace-pre-wrap">{product.description ?? "—"}</p>
          </div>
          {product.attributes_json && Object.keys(product.attributes_json).length > 0 && (
            <div className="sm:col-span-2">
              <p className="text-[10px] uppercase text-gray-400 mb-1">Specs</p>
              <dl className="grid sm:grid-cols-2 gap-1 text-xs">
                {Object.entries(product.attributes_json).map(([k, v]) => (
                  <div key={k} className="flex gap-2">
                    <dt className="text-gray-500">{k}:</dt>
                    <dd className="text-gray-800">{String(v)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
        </div>
      )}

      <PartnerMatchPanel mode="product" entityId={id} />

      <BuyerFinderPanel productId={id} />

      <ExportAnalysisPanel productId={id} />
    </div>
  );
}
