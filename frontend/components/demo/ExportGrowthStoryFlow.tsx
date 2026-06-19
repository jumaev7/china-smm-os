"use client";

import Link from "next/link";
import { ArrowRight, CheckCircle2, Circle, Play } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ExportGrowthStoryStep } from "@/lib/commercial-demo-api";

const STATUS_STYLES = {
  complete: "border-emerald-200 bg-emerald-50 text-emerald-800",
  active: "border-amber-200 bg-amber-50 text-amber-800",
  pending: "border-gray-200 bg-gray-50 text-gray-500",
};

function StepIcon({ status }: { status: ExportGrowthStoryStep["status"] }) {
  if (status === "complete") return <CheckCircle2 size={16} className="text-emerald-600" />;
  if (status === "active") return <Play size={16} className="text-amber-600" />;
  return <Circle size={16} className="text-gray-300" />;
}

export function ExportGrowthStoryFlow({
  steps,
  totalPipelineUsd,
  roiImprovementPct,
}: {
  steps: ExportGrowthStoryStep[];
  totalPipelineUsd: number;
  roiImprovementPct: number;
}) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-4 text-sm">
        <div className="rounded-lg border border-brand-200 bg-brand-50 px-4 py-2">
          <span className="text-gray-500 text-xs">Total Pipeline</span>
          <p className="font-bold text-brand-800">${totalPipelineUsd.toLocaleString()}</p>
        </div>
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2">
          <span className="text-gray-500 text-xs">ROI Improvement</span>
          <p className="font-bold text-emerald-800">+{roiImprovementPct}%</p>
        </div>
      </div>

      <div className="overflow-x-auto pb-2">
        <div className="flex min-w-max items-start gap-1">
          {steps.map((step, idx) => (
            <div key={step.id} className="flex items-start">
              <Link
                href={step.route}
                className={cn(
                  "flex flex-col rounded-lg border px-3 py-2 min-w-[130px] max-w-[150px] text-center hover:shadow-sm transition-shadow",
                  STATUS_STYLES[step.status],
                )}
              >
                <StepIcon status={step.status} />
                <span className="text-[10px] font-medium mt-1 opacity-70">Step {step.order}</span>
                <span className="text-xs font-semibold leading-tight mt-0.5">{step.title}</span>
                {step.metric_label && step.metric_value && (
                  <span className="text-[10px] mt-1 opacity-80">
                    {step.metric_label}: <strong>{step.metric_value}</strong>
                  </span>
                )}
              </Link>
              {idx < steps.length - 1 && (
                <ArrowRight size={14} className="mx-1 mt-6 text-gray-400 shrink-0" />
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {steps.map((step) => (
          <Link
            key={`detail-${step.id}`}
            href={step.route}
            className={cn(
              "rounded-xl border p-4 hover:shadow-sm transition-shadow",
              STATUS_STYLES[step.status],
            )}
          >
            <div className="flex items-center gap-2 mb-1">
              <StepIcon status={step.status} />
              <span className="text-sm font-semibold">{step.title}</span>
            </div>
            <p className="text-xs opacity-80 leading-relaxed">{step.description}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
