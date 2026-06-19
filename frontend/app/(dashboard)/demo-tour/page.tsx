"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import {
  ArrowRight,
  Building2,
  CheckCircle2,
  Circle,
  Factory,
  Loader2,
  Play,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  commercialDemoApi,
  type DemoFactoryPackageId,
  type DemoFactoryPackageSummary,
  type DemoTourStep,
} from "@/lib/commercial-demo-api";
import { useDemoMode } from "@/lib/demo-mode";
import { DemoModeBanner } from "@/components/demo/DemoModeToggle";
import { ExportGrowthStoryFlow } from "@/components/demo/ExportGrowthStoryFlow";
import { ProductPositioningPanel } from "@/components/demo/ProductPositioningPanel";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import { PageHeader, PageShell, ScoreCard, StatusBadge } from "@/components/ui/design-system";
import { cn } from "@/lib/utils";

const PACKAGE_ICONS: Record<DemoFactoryPackageId, typeof Factory> = {
  haocheng: Factory,
  toy_manufacturer: Sparkles,
  textile_factory: Building2,
};

function TourStepCard({
  step,
  active,
  complete,
  onSelect,
}: {
  step: DemoTourStep;
  active: boolean;
  complete: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "w-full text-left rounded-xl border p-4 transition-all",
        active && "border-brand-300 bg-brand-50 ring-2 ring-brand-200",
        complete && !active && "border-emerald-200 bg-emerald-50/50",
        !active && !complete && "border-gray-200 bg-white hover:border-gray-300",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5">
          {complete ? (
            <CheckCircle2 size={18} className="text-emerald-600" />
          ) : active ? (
            <Play size={18} className="text-brand-600" />
          ) : (
            <Circle size={18} className="text-gray-300" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-medium text-gray-400 uppercase">Step {step.order}</span>
            <span className="text-[10px] text-gray-400">· {step.minutes} min</span>
          </div>
          <p className="font-semibold text-sm text-navy-900 mt-0.5">{step.title}</p>
          <p className="text-xs text-gray-500 mt-1 line-clamp-2">{step.description}</p>
        </div>
      </div>
    </button>
  );
}

export default function DemoTourPage() {
  const queryClient = useQueryClient();
  const { enable, setPackage } = useDemoMode();
  const [activeStep, setActiveStep] = useState(0);
  const [visitedSteps, setVisitedSteps] = useState<Set<number>>(new Set([0]));
  const [loadingPackage, setLoadingPackage] = useState<DemoFactoryPackageId | null>(null);

  const tourQuery = useQuery({
    queryKey: ["commercial-demo", "tour"],
    queryFn: () => commercialDemoApi.getTour().then((r) => r.data),
  });

  const packagesQuery = useQuery({
    queryKey: ["commercial-demo", "packages"],
    queryFn: () => commercialDemoApi.listPackages().then((r) => r.data),
  });

  const storyQuery = useQuery({
    queryKey: ["commercial-demo", "export-growth-story"],
    queryFn: () => commercialDemoApi.getExportGrowthStory().then((r) => r.data),
  });

  const positioningQuery = useQuery({
    queryKey: ["commercial-demo", "positioning"],
    queryFn: () => commercialDemoApi.getPositioning().then((r) => r.data),
  });

  const readinessQuery = useQuery({
    queryKey: ["commercial-demo", "readiness"],
    queryFn: () => commercialDemoApi.getReadiness().then((r) => r.data),
  });

  const loadPackageMutation = useMutation({
    mutationFn: (packageId: DemoFactoryPackageId) =>
      commercialDemoApi.loadPackage(packageId).then((r) => r.data),
    onSuccess: (data, packageId) => {
      toast.success(data.message);
      enable(packageId);
      setPackage(packageId);
      setLoadingPackage(null);
      queryClient.invalidateQueries({ queryKey: ["commercial-demo"] });
    },
    onError: (err: Error) => {
      toast.error(err.message || "Failed to load demo package");
      setLoadingPackage(null);
    },
  });

  const handleLoadPackage = (pkg: DemoFactoryPackageSummary) => {
    setLoadingPackage(pkg.id);
    loadPackageMutation.mutate(pkg.id);
  };

  const steps = tourQuery.data?.steps ?? [];
  const current = steps[activeStep];

  const markVisited = (idx: number) => {
    setActiveStep(idx);
    setVisitedSteps((prev) => new Set([...prev, idx]));
  };

  if (tourQuery.isLoading) {
    return (
      <PageShell>
        <LoadingState message="Loading demo tour…" />
      </PageShell>
    );
  }

  if (tourQuery.isError) {
    return (
      <PageShell>
        <ErrorState error={tourQuery.error} onRetry={() => tourQuery.refetch()} />
      </PageShell>
    );
  }

  return (
    <PageShell>
      <PageHeader
        title="Platform Demo Tour"
        subtitle="Guide prospects through the platform in 5–10 minutes. Load a demo factory, then walk through each step."
      />

      <DemoModeBanner />

      {readinessQuery.data && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <ScoreCard
            title="Demo Readiness"
            score={readinessQuery.data.score}
            subtitle={`Grade ${readinessQuery.data.grade}`}
            className="max-w-xs"
          />
          <Link href="/value-demo" className="btn-secondary text-xs">
            Value Demo
          </Link>
          <Link href="/executive-demo" className="btn-secondary text-xs">
            Executive Demo
          </Link>
        </div>
      )}

      {/* Demo Factory Packages */}
      <section className="mt-8">
        <h2 className="text-base font-semibold text-navy-900 mb-1">Demo Factory Packages</h2>
        <p className="text-sm text-gray-500 mb-4">
          Load a complete demo environment with buyers, leads, deals, proposals, and communications.
        </p>
        <div className="grid gap-4 md:grid-cols-3">
          {(packagesQuery.data?.packages ?? []).map((pkg) => {
            const Icon = PACKAGE_ICONS[pkg.id];
            const isLoading = loadingPackage === pkg.id;
            return (
              <div key={pkg.id} className="card-premium p-5 flex flex-col">
                <div className="flex items-center gap-2 mb-2">
                  <Icon size={18} className="text-brand-600" />
                  <h3 className="font-semibold text-sm text-navy-900">{pkg.company_name}</h3>
                </div>
                <StatusBadge variant="neutral">{pkg.industry}</StatusBadge>
                <p className="text-xs text-gray-500 mt-2">{pkg.country}</p>
                <p className="text-xs text-gray-600 mt-2 flex-1 leading-relaxed">{pkg.description}</p>
                <ul className="mt-3 space-y-1">
                  {pkg.highlights.map((h) => (
                    <li key={h} className="text-[11px] text-gray-500 flex items-start gap-1">
                      <CheckCircle2 size={10} className="text-emerald-500 shrink-0 mt-0.5" />
                      {h}
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  disabled={isLoading}
                  onClick={() => handleLoadPackage(pkg)}
                  className="btn-primary text-xs mt-4 w-full"
                >
                  {isLoading ? (
                    <>
                      <Loader2 size={14} className="animate-spin" /> Loading…
                    </>
                  ) : (
                    <>Load Demo Environment</>
                  )}
                </button>
              </div>
            );
          })}
        </div>
      </section>

      {/* Interactive Tour */}
      <section className="mt-10">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-base font-semibold text-navy-900">Interactive Walkthrough</h2>
            <p className="text-sm text-gray-500">
              {tourQuery.data?.estimated_minutes ?? 10} minutes · {steps.length} steps
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setActiveStep(0);
              setVisitedSteps(new Set([0]));
            }}
            className="btn-secondary text-xs"
          >
            <RefreshCw size={14} /> Reset Tour
          </button>
        </div>

        <div className="grid gap-6 lg:grid-cols-5">
          <div className="lg:col-span-2 space-y-2">
            {steps.map((step, idx) => (
              <TourStepCard
                key={step.id}
                step={step}
                active={idx === activeStep}
                complete={visitedSteps.has(idx) && idx !== activeStep}
                onSelect={() => markVisited(idx)}
              />
            ))}
          </div>

          {current && (
            <div className="lg:col-span-3 card-premium p-6">
              <span className="text-xs font-medium text-brand-600 uppercase">
                Step {current.order} of {steps.length}
              </span>
              <h3 className="text-xl font-bold text-navy-900 mt-1">{current.title}</h3>
              <p className="text-sm text-gray-600 mt-2 leading-relaxed">{current.description}</p>

              <div className="mt-4 rounded-lg bg-emerald-50 border border-emerald-200 p-3">
                <p className="text-xs font-semibold text-emerald-800">Business Value</p>
                <p className="text-sm text-emerald-900 mt-1">{current.business_value}</p>
              </div>

              <div className="mt-4">
                <p className="text-xs font-semibold text-gray-500 uppercase mb-2">Talking Points</p>
                <ul className="space-y-1">
                  {current.talking_points.map((pt) => (
                    <li key={pt} className="text-sm text-gray-700 flex items-start gap-2">
                      <ArrowRight size={14} className="text-brand-500 shrink-0 mt-0.5" />
                      {pt}
                    </li>
                  ))}
                </ul>
              </div>

              <div className="mt-6 flex flex-wrap gap-2">
                <Link href={current.route} className="btn-primary text-sm">
                  Open {current.title} <ArrowRight size={14} />
                </Link>
                {activeStep < steps.length - 1 && (
                  <button
                    type="button"
                    onClick={() => markVisited(activeStep + 1)}
                    className="btn-secondary text-sm"
                  >
                    Next Step
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Export Growth Story */}
      <section className="mt-10">
        <h2 className="text-base font-semibold text-navy-900 mb-1">Export Growth Story</h2>
        <p className="text-sm text-gray-500 mb-4">
          Visual flow from content upload to revenue — the complete export growth loop.
        </p>
        {storyQuery.isLoading ? (
          <LoadingState message="Loading growth story…" variant="card" />
        ) : storyQuery.data ? (
          <ExportGrowthStoryFlow
            steps={storyQuery.data.steps}
            totalPipelineUsd={storyQuery.data.total_pipeline_usd}
            roiImprovementPct={storyQuery.data.roi_improvement_pct}
          />
        ) : null}
      </section>

      {/* Product Positioning */}
      <section className="mt-10">
        <h2 className="text-base font-semibold text-navy-900 mb-4">Product Positioning</h2>
        {positioningQuery.isLoading ? (
          <LoadingState message="Loading positioning…" variant="card" />
        ) : positioningQuery.data ? (
          <ProductPositioningPanel data={positioningQuery.data} />
        ) : null}
      </section>

      {/* Readiness Gaps */}
      {readinessQuery.data && readinessQuery.data.gaps.length > 0 && (
        <section className="mt-10 card-premium p-5">
          <h2 className="text-sm font-semibold text-navy-900 mb-3">Improve Demo Readiness</h2>
          <ul className="space-y-2">
            {readinessQuery.data.recommended_next_steps.map((step) => (
              <li key={step} className="text-sm text-gray-600 flex items-start gap-2">
                <ArrowRight size={14} className="text-brand-500 shrink-0 mt-0.5" />
                {step}
              </li>
            ))}
          </ul>
        </section>
      )}
    </PageShell>
  );
}
