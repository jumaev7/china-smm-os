"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Factory, Loader2 } from "lucide-react";
import toast from "react-hot-toast";
import { factoryPlatformApi, tenantOnboardingApi } from "@/lib/api";
import { OnboardingStepShell } from "@/components/onboarding/OnboardingStepShell";
import { useOnboardingTenantId } from "@/lib/onboarding-hooks";
import { cn } from "@/lib/utils";

const INDUSTRIES = [
  { id: "textiles", label: "Textiles & Apparel", emoji: "🧵" },
  { id: "electronics", label: "Electronics & Components", emoji: "⚡" },
  { id: "machinery", label: "Machinery & Equipment", emoji: "⚙️" },
  { id: "furniture", label: "Furniture & Home Goods", emoji: "🪑" },
  { id: "food", label: "Food & Beverage Processing", emoji: "🍜" },
  { id: "automotive", label: "Automotive Parts", emoji: "🚗" },
  { id: "building", label: "Building Materials", emoji: "🏗️" },
  { id: "chemicals", label: "Chemicals & Plastics", emoji: "🧪" },
  { id: "medical", label: "Medical Devices", emoji: "🏥" },
  { id: "other", label: "Other Manufacturing", emoji: "🏭" },
] as const;

export default function OnboardingIndustryPage() {
  const qc = useQueryClient();
  const tenantId = useOnboardingTenantId();
  const [selected, setSelected] = useState<string | null>(null);

  const { data: profile } = useQuery({
    queryKey: ["factory-profile", tenantId],
    queryFn: () => factoryPlatformApi.profile(tenantId).then((r) => r.data),
    enabled: !!tenantId,
  });

  const current = profile?.profile.industry ?? "";

  const save = useMutation({
    mutationFn: async (industry: string) => {
      await tenantOnboardingApi.saveCompany({ company_name: profile?.profile.company_name || "My Factory", industry }).then((r) => r.data);
      return industry;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenant-onboarding-readiness"] });
      qc.invalidateQueries({ queryKey: ["tenant-onboarding"] });
      qc.invalidateQueries({ queryKey: ["factory-profile", tenantId] });
      toast.success("Industry saved — AI templates will adapt to your category");
    },
    onError: () => toast.error("Could not save industry"),
  });

  const activeSelection = selected ?? current;

  return (
    <OnboardingStepShell
      stepId="industry_selection"
      title="Choose your industry"
      subtitle="This shapes content templates, buyer matching, and KPI benchmarks for your factory."
      illustration="platform"
      nextHref="/onboarding/branding"
      nextLabel="Continue to branding"
    >
      <div className="grid sm:grid-cols-2 gap-3">
        {INDUSTRIES.map((ind, i) => {
          const isActive =
            activeSelection.toLowerCase().includes(ind.id) ||
            activeSelection.toLowerCase() === ind.label.toLowerCase() ||
            selected === ind.label;
          const isCurrent = !selected && current.toLowerCase().includes(ind.id);

          return (
            <button
              key={ind.id}
              type="button"
              onClick={() => {
                setSelected(ind.label);
                save.mutate(ind.label);
              }}
              disabled={save.isPending}
              className={cn(
                "relative flex items-center gap-3 rounded-2xl border p-4 text-left transition-all duration-300 animate-fade-in-up",
                isActive || isCurrent
                  ? "border-brand-300 bg-brand-50 ring-2 ring-brand-200 shadow-sm"
                  : "border-slate-200 bg-white hover:border-brand-200 hover:shadow-card",
              )}
              style={{ animationDelay: `${i * 50}ms` }}
            >
              <span className="text-2xl" aria-hidden>
                {ind.emoji}
              </span>
              <div className="flex-1">
                <p className="font-semibold text-sm text-navy-900">{ind.label}</p>
              </div>
              {(isActive || isCurrent) && !save.isPending ? (
                <Check size={18} className="text-brand-600 shrink-0" />
              ) : save.isPending && selected === ind.label ? (
                <Loader2 size={18} className="animate-spin text-brand-600 shrink-0" />
              ) : (
                <Factory size={16} className="text-gray-300 shrink-0" />
              )}
            </button>
          );
        })}
      </div>
    </OnboardingStepShell>
  );
}
