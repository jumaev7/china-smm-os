"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, Rocket } from "lucide-react";
import { tenantOnboardingApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { LoadingState } from "@/components/ui/PageStates";
import { OnboardingAssistant } from "./OnboardingAssistant";

const WIZARD_STEPS = [
  { href: "/onboarding/welcome", label: "Welcome" },
  { href: "/onboarding/company", label: "Company" },
  { href: "/onboarding/channels", label: "Channels" },
  { href: "/onboarding/content", label: "Content" },
  { href: "/onboarding/crm", label: "CRM" },
  { href: "/onboarding/proposal", label: "Proposal" },
  { href: "/onboarding/growth-center", label: "Growth" },
] as const;

export function OnboardingLayout({
  title,
  subtitle,
  children,
  contextStep,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  contextStep?: string;
}) {
  const pathname = usePathname();
  const { data, isLoading } = useQuery({
    queryKey: ["tenant-onboarding"],
    queryFn: () => tenantOnboardingApi.dashboard().then((r) => r.data),
  });

  if (isLoading && !data) {
    return <LoadingState message="Loading onboarding…" />;
  }

  const progress = data?.progress_percent ?? 0;

  return (
    <div className="min-h-full bg-gradient-to-b from-slate-50 to-white">
      <div className="border-b border-slate-200 bg-white/90 backdrop-blur sticky top-0 z-20">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-4 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div className="flex items-center gap-2">
              <Rocket className="text-brand-600" size={22} />
              <div>
                <Link href="/onboarding" className="text-sm font-medium text-brand-600 hover:underline">
                  Factory Setup
                </Link>
                <p className="text-xs text-gray-500">
                  {data?.completed_steps ?? 0}/{data?.total_steps ?? 8} steps · ~{data?.estimated_minutes_remaining ?? 49} min left
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3 min-w-[200px]">
              <div className="flex-1 h-2 rounded-full bg-slate-100 overflow-hidden">
                <div
                  className="h-full rounded-full bg-brand-500 transition-all duration-500"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <span className="text-sm font-semibold tabular-nums text-gray-700 w-10">{progress}%</span>
            </div>
          </div>

          <nav className="flex gap-1 overflow-x-auto pb-1 -mx-1 px-1 scrollbar-thin">
            {WIZARD_STEPS.map((step) => {
              const active = pathname === step.href || pathname.startsWith(`${step.href}/`);
              const checklist = data?.steps.find((s) => s.route === step.href);
              const done = checklist?.completed;
              return (
                <Link
                  key={step.href}
                  href={step.href}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors",
                    active
                      ? "bg-brand-600 text-white"
                      : done
                        ? "bg-emerald-50 text-emerald-800 hover:bg-emerald-100"
                        : "bg-slate-100 text-gray-600 hover:bg-slate-200",
                  )}
                >
                  {done ? <CheckCircle2 size={12} /> : <Circle size={12} />}
                  {step.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        <div className="grid lg:grid-cols-[1fr_320px] gap-8">
          <div>
            <header className="mb-6">
              <h1 className="page-title">{title}</h1>
              {subtitle ? <p className="text-sm text-gray-500 mt-1">{subtitle}</p> : null}
            </header>
            {children}
          </div>
          <aside className="space-y-4">
            <OnboardingAssistant contextStep={contextStep} />
            {data?.new_milestones?.length ? (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-emerald-800">Success</p>
                {data.new_milestones.map((m) => (
                  <p key={m.step_id} className="text-sm text-emerald-900">{m.message}</p>
                ))}
              </div>
            ) : null}
          </aside>
        </div>
      </div>
    </div>
  );
}
