"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Package, Plus, Search, Upload, Loader2 } from "lucide-react";
import toast from "react-hot-toast";
import { clientsApi, Client, productsApi, Product, normalizeList } from "@/lib/api";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import { useTranslation } from "@/lib/I18nProvider";

export default function ProductsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [clientFilter, setClientFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    client_id: "",
    name: "",
    sku: "",
    category: "",
    unit_price: "",
    currency: "USD",
    moq: "",
    description: "",
  });

  const { data: clientsData } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list({ limit: 200 }).then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clientsData);

  const { data: categoriesData } = useQuery({
    queryKey: ["product-categories", clientFilter],
    queryFn: () =>
      productsApi.categories(clientFilter || undefined).then((r) => r.data),
  });

  const {
    data,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ["products", clientFilter, categoryFilter, search],
    queryFn: () =>
      productsApi
        .list({
          client_id: clientFilter || undefined,
          category: categoryFilter || undefined,
          search: search || undefined,
          limit: 200,
        })
        .then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      productsApi.create({
        client_id: form.client_id,
        name: form.name,
        sku: form.sku || null,
        category: form.category || null,
        description: form.description || null,
        moq: form.moq ? parseInt(form.moq, 10) : null,
        unit_price: form.unit_price ? parseFloat(form.unit_price) : null,
        currency: form.currency,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["products"] });
      setShowForm(false);
      setForm({
        client_id: "",
        name: "",
        sku: "",
        category: "",
        unit_price: "",
        currency: "USD",
        moq: "",
        description: "",
      });
      toast.success("Product created");
    },
    onError: (err: Error) => toast.error(err.message || "Create failed"),
  });

  const products = useMemo(() => normalizeList<Product>(data), [data]);
  const categories = categoriesData?.categories ?? [];

  if (isLoading) return <LoadingState message={t("products.loading")} />;
  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : t("products.loadError")}
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Package size={22} className="text-brand-600" />
            {t("products.title")}
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t("products.subtitle")} · {data?.total ?? 0}</p>
        </div>
        <div className="flex gap-2">
          <Link href="/products/import" className="btn-secondary flex items-center gap-2">
            <Upload size={15} />
            {t("products.importCsv")}
          </Link>
          <button type="button" className="btn-primary flex items-center gap-2" onClick={() => setShowForm(true)}>
            <Plus size={15} />
            {t("products.addProduct")}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            className="input pl-9 w-full"
            placeholder={t("products.searchPlaceholder")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select
          className="input text-sm min-w-[160px]"
          value={clientFilter}
          onChange={(e) => {
            setClientFilter(e.target.value);
            setCategoryFilter("");
          }}
        >
          <option value="">{t("common.allClients")}</option>
          {clientOptions.map((c) => (
            <option key={c.id} value={c.id}>
              {c.company_name}
            </option>
          ))}
        </select>
        <select
          className="input text-sm min-w-[140px]"
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
        >
          <option value="">{t("products.allCategories")}</option>
          {categories.map((cat) => (
            <option key={cat} value={cat}>
              {cat}
            </option>
          ))}
        </select>
      </div>

      {showForm && (
        <div className="card p-4 space-y-3">
          <p className="text-sm font-semibold text-gray-900">New product</p>
          <div className="grid sm:grid-cols-2 gap-3">
            <select
              className="input text-sm"
              value={form.client_id}
              onChange={(e) => setForm({ ...form, client_id: e.target.value })}
            >
              <option value="">Select client</option>
              {clientOptions.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.company_name}
                </option>
              ))}
            </select>
            <input
              className="input text-sm"
              placeholder="Product name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
            <input
              className="input text-sm"
              placeholder="SKU"
              value={form.sku}
              onChange={(e) => setForm({ ...form, sku: e.target.value })}
            />
            <input
              className="input text-sm"
              placeholder="Category"
              value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })}
            />
            <input
              className="input text-sm"
              placeholder="Unit price"
              type="number"
              value={form.unit_price}
              onChange={(e) => setForm({ ...form, unit_price: e.target.value })}
            />
            <input
              className="input text-sm"
              placeholder="MOQ"
              type="number"
              value={form.moq}
              onChange={(e) => setForm({ ...form, moq: e.target.value })}
            />
          </div>
          <textarea
            className="input text-sm min-h-[72px]"
            placeholder="Description"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-primary text-sm"
              disabled={!form.client_id || !form.name || createMutation.isPending}
              onClick={() => createMutation.mutate()}
            >
              {createMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : "Save"}
            </button>
            <button type="button" className="btn-secondary text-sm" onClick={() => setShowForm(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="card overflow-hidden">
        {products.length === 0 ? (
          <p className="p-8 text-center text-sm text-gray-400">No products yet. Add manually or import a catalog.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50 text-left">
                <th className="px-4 py-3 font-medium text-gray-600">Product</th>
                <th className="px-4 py-3 font-medium text-gray-600">Client</th>
                <th className="px-4 py-3 font-medium text-gray-600">Category</th>
                <th className="px-4 py-3 font-medium text-gray-600">Price</th>
                <th className="px-4 py-3 font-medium text-gray-600">MOQ</th>
                <th className="px-4 py-3 font-medium text-gray-600">SKU</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {products.map((p: Product) => (
                <tr key={p.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium">
                    <Link href={`/products/${p.id}`} className="text-brand-700 hover:text-brand-900">
                      {p.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-gray-600">{p.company_name ?? "—"}</td>
                  <td className="px-4 py-3 text-gray-600">{p.category ?? "—"}</td>
                  <td className="px-4 py-3 text-gray-600 tabular-nums">
                    {p.unit_price != null ? `${p.unit_price} ${p.currency}` : "—"}
                  </td>
                  <td className="px-4 py-3 text-gray-600 tabular-nums">{p.moq ?? "—"}</td>
                  <td className="px-4 py-3 text-gray-500">{p.sku ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
