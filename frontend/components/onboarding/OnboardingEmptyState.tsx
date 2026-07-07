"use client";

import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { OnboardingIllustration } from "./OnboardingIllustration";
import { cn } from "@/lib/utils";

export function OnboardingEmptyState({
  title,
  description,
  actionLabel,
  actionHref,
  onAction,
  icon: Icon,
  illustration = "platform",
}: {
  title: string;
  description: string;
  actionLabel: string;
  actionHref?: string;
  onAction?: () => void;
  icon?: LucideIcon;
  illustration?: "platform" | "business" | "success" | "executive";
}) {
  const ctaClass = cn(
    "inline-flex items-center gap-2 rounded-xl bg-brand-600 text-white font-semibold text-sm px-5 py-2.5",
    "hover:bg-brand-700 shadow-sm transition-colors mt-5",
    "dark-tenant:bg-violet-600 dark-tenant:hover:bg-violet-500",
  );

  return (
    <div className="card-premium p-8 sm:p-10 text-center animate-fade-in-up">
      <OnboardingIllustration variant={illustration} className="w-full max-w-[200px] h-36 mx-auto mb-6" />
      {Icon ? (
        <div className="w-12 h-12 rounded-xl bg-brand-50 flex items-center justify-center mx-auto mb-4 dark-tenant:bg-violet-500/10">
          <Icon size={22} className="text-brand-600 dark-tenant:text-violet-400" />
        </div>
      ) : null}
      <h3 className="text-lg font-semibold text-navy-900 dark-tenant:text-slate-100">{title}</h3>
      <p className="text-sm text-gray-600 mt-2 max-w-md mx-auto leading-relaxed dark-tenant:text-slate-400">
        {description}
      </p>
      {actionHref ? (
        <Link href={actionHref} className={ctaClass}>
          {actionLabel}
        </Link>
      ) : onAction ? (
        <button type="button" onClick={onAction} className={ctaClass}>
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}

export function OnboardingFormSkeleton() {
  return (
    <div className="space-y-5 animate-pulse">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="space-y-2">
          <div className="h-4 w-28 bg-slate-100 rounded dark-tenant:bg-white/[0.06]" />
          <div className="h-11 w-full bg-slate-100 rounded-xl dark-tenant:bg-white/[0.06]" />
        </div>
      ))}
    </div>
  );
}

export function OnboardingCardsSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="grid sm:grid-cols-2 gap-3 animate-pulse">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="h-24 rounded-2xl bg-slate-100 dark-tenant:bg-white/[0.06]"
          style={{ animationDelay: `${i * 80}ms` }}
        />
      ))}
    </div>
  );
}
