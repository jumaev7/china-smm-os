"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Compass } from "lucide-react";
import { tenantOnboardingApi } from "@/lib/api";
import { OnboardingLayout } from "@/components/onboarding/OnboardingLayout";
import { ExecutiveWalkthroughPanels } from "@/components/onboarding/ExecutiveWalkthroughPanels";
import { OnboardingIllustration } from "@/components/onboarding/OnboardingIllustration";
import { LoadingState } from "@/components/ui/PageStates";

export default function ExecutiveWalkthroughPage() {
  const { data: readiness, isLoading } = useQuery({
    queryKey: ["tenant-onboarding-readiness"],
    queryFn: () => tenantOnboardingApi.readiness().then((r) => r.data),
  });

  if (isLoading || !readiness) {
    return (
      <OnboardingLayout title="Executive tour" contextStep="executive_walkthrough">
        <LoadingState message="Loading executive walkthrough…" />
      </OnboardingLayout>
    );
  }

  return (
    <OnboardingLayout
      title="Executive dashboard tour"
      subtitle="Five quick stops that show leadership where pipeline, publishing, content, and growth live."
      contextStep="executive_walkthrough"
    >
      <div className="space-y-8">
        <div className="rounded-2xl border border-amber-100 bg-gradient-to-br from-amber-50/80 to-white p-6 flex flex-col sm:flex-row gap-6 items-center">
          <OnboardingIllustration variant="executive" className="w-full sm:w-48 h-36 shrink-0" />
          <div className="flex-1 space-y-3">
            <div className="flex items-center gap-2 text-amber-700">
              <Compass size={18} />
              <span className="text-sm font-semibold">Built for factory leadership</span>
            </div>
            <p className="text-sm text-gray-600 leading-relaxed">
              Each panel takes about two minutes. Visit the area, skim the KPIs, and return here — we&apos;ll mark it
              complete automatically. No configuration homework, just orientation.
            </p>
            <p className="text-xs text-gray-500">
              {readiness.executive_walkthrough.completed_panels} of{" "}
              {readiness.executive_walkthrough.total_panels} areas explored
              {readiness.executive_walkthrough.completed ? " — tour complete!" : ""}
            </p>
          </div>
        </div>

        <ExecutiveWalkthroughPanels walkthrough={readiness.executive_walkthrough} compact />

        <Link
          href="/onboarding"
          className="inline-flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-navy-900"
        >
          <ArrowLeft size={14} />
          Back to setup hub
        </Link>
      </div>
    </OnboardingLayout>
  );
}
