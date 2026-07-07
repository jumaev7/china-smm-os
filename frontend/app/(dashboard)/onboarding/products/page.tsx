"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Package, Plus, Upload } from "lucide-react";
import toast from "react-hot-toast";
import { factoryPlatformApi } from "@/lib/api";
import { OnboardingActionCard } from "@/components/onboarding/OnboardingActionCard";
import { OnboardingStepShell } from "@/components/onboarding/OnboardingStepShell";
import { useOnboardingRefresh, useOnboardingTenantId } from "@/lib/onboarding-hooks";

export default function OnboardingProductsPage() {
  const qc = useQueryClient();
  const tenantId = useOnboardingTenantId();
  const refresh = useOnboardingRefresh();
  const [productName, setProductName] = useState("");
  const [category, setCategory] = useState("");

  const { data: catalog } = useQuery({
    queryKey: ["factory-catalog", tenantId],
    queryFn: () => factoryPlatformApi.catalog(tenantId).then((r) => r.data),
    enabled: !!tenantId,
  });

  const items = catalog?.items ?? [];
  const hasProducts = items.length > 0;

  const createProduct = useMutation({
    mutationFn: () =>
      factoryPlatformApi.createCatalogProduct(tenantId, {
        product_name: productName.trim(),
        category: category.trim() || undefined,
        status: "active",
        export_available: true,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["factory-catalog", tenantId] });
      refresh.mutate();
      setProductName("");
      setCategory("");
      toast.success("Product added to catalog");
    },
    onError: () => toast.error("Could not add product"),
  });

  return (
    <OnboardingStepShell
      stepId="products_imported"
      title="Build your product catalog"
      subtitle="Your catalog powers AI content, proposals, and buyer outreach."
      illustration="platform"
      nextHref="/onboarding/content"
      nextLabel="Continue to content"
    >
      <div className="space-y-6">
        {hasProducts ? (
          <div className="rounded-2xl border border-emerald-100 bg-emerald-50/40 p-5">
            <p className="text-sm font-semibold text-emerald-800 mb-3">
              {catalog?.active_count ?? items.length} product{(catalog?.active_count ?? items.length) !== 1 ? "s" : ""} in catalog
            </p>
            <ul className="space-y-2">
              {items.slice(0, 5).map((p, i) => (
                <li
                  key={p.product_id}
                  className="flex items-center gap-3 rounded-xl bg-white border border-emerald-100 px-4 py-3 animate-fade-in-up"
                  style={{ animationDelay: `${i * 50}ms` }}
                >
                  <Package size={16} className="text-emerald-600 shrink-0" />
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-navy-900 truncate">{p.product_name}</p>
                    {p.category ? <p className="text-xs text-gray-500">{p.category}</p> : null}
                  </div>
                </li>
              ))}
            </ul>
            {items.length > 5 ? (
              <Link href="/factory-platform" className="text-sm text-brand-600 font-medium mt-3 inline-block hover:underline">
                View full catalog →
              </Link>
            ) : null}
          </div>
        ) : null}

        <form
          className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!productName.trim()) {
              toast.error("Product name is required");
              return;
            }
            createProduct.mutate();
          }}
        >
          <div className="flex items-center gap-2 text-navy-900">
            <Plus size={18} className="text-brand-600" />
            <span className="font-semibold text-sm">Add your first product</span>
          </div>
          <input
            type="text"
            value={productName}
            onChange={(e) => setProductName(e.target.value)}
            placeholder="Product name"
            className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/30"
          />
          <input
            type="text"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="Category (optional)"
            className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/30"
          />
          <button
            type="submit"
            disabled={createProduct.isPending}
            className="inline-flex items-center gap-2 rounded-xl bg-brand-600 text-white text-sm font-semibold px-5 py-2.5 hover:bg-brand-700 disabled:opacity-50"
          >
            {createProduct.isPending ? <Loader2 size={16} className="animate-spin" /> : null}
            Add product
          </button>
        </form>

        <OnboardingActionCard
          icon={Upload}
          title="Bulk import via Factory Platform"
          description="Upload a spreadsheet or manage your full catalog with MOQ, pricing, and target markets."
          href="/factory-platform"
          index={1}
        />
      </div>
    </OnboardingStepShell>
  );
}
