"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, BarChart3, Lightbulb, TrendingUp } from "lucide-react";
import { tenantOnboardingApi } from "@/lib/api";
import { OnboardingLayout } from "@/components/onboarding/OnboardingLayout";

export default function OnboardingGrowthCenterPage() {
  const qc = useQueryClient();
  const recorded = useRef(false);
  const recordVisit = useMutation({
    mutationFn: () => tenantOnboardingApi.recordGrowthCenterVisit().then((r) => r.data),
    onSuccess: (res) => qc.setQueryData(["tenant-onboarding"], res.progress),
  });

  useEffect(() => {
    if (recorded.current) return;
    recorded.current = true;
    recordVisit.mutate();
  }, []);

  return (
    <OnboardingLayout
      title="Growth Center"
      subtitle="Your executive view of pipeline health and AI recommendations."
      contextStep="growth_center"
    >
      <div className="space-y-5 max-w-xl">
        <div className="grid sm:grid-cols-3 gap-3">
          {[
            { icon: BarChart3, label: "KPI overview" },
            { icon: TrendingUp, label: "Pipeline trends" },
            { icon: Lightbulb, label: "AI recommendations" },
          ].map(({ icon: Icon, label }) => (
            <div key={label} className="rounded-lg border border-slate-200 p-3 text-center bg-white">
              <Icon className="mx-auto text-brand-600 mb-1" size={22} />
              <p className="text-xs font-medium text-gray-700">{label}</p>
            </div>
          ))}
        </div>

        <p className="text-sm text-gray-600">
          Growth Center aggregates leads, buyers, deals, proposals, and communications into one dashboard.
          Visit it regularly to see where to focus sales effort.
        </p>

        <div className="flex flex-wrap gap-3">
          <Link
            href="/growth-center"
            className="inline-flex items-center gap-2 rounded-lg bg-brand-600 text-white font-medium px-5 py-2.5 hover:bg-brand-700"
          >
            Open Growth Center
            <ArrowRight size={18} />
          </Link>
          <Link
            href="/onboarding"
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 text-gray-700 font-medium px-5 py-2.5 hover:bg-slate-50"
          >
            Back to setup dashboard
          </Link>
        </div>
      </div>
    </OnboardingLayout>
  );
}
