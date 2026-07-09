"use client";

import { cn } from "@/lib/utils";

export function JourneyDashboardSkeleton() {
  return (
    <div className="space-y-6 animate-pulse" aria-busy aria-label="Loading customer success dashboard">
      <div className="h-20 rounded-2xl bg-slate-100 dark-tenant:bg-white/[0.06]" />
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-24 rounded-2xl bg-slate-100 dark-tenant:bg-white/[0.06]" />
        ))}
      </div>
      <div className="grid lg:grid-cols-2 gap-6">
        <div className="h-80 rounded-2xl bg-slate-100 dark-tenant:bg-white/[0.06]" />
        <div className="h-80 rounded-2xl bg-slate-100 dark-tenant:bg-white/[0.06]" />
      </div>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-36 rounded-2xl bg-slate-100 dark-tenant:bg-white/[0.06]" />
        ))}
      </div>
      <div className="grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 h-96 rounded-2xl bg-slate-100 dark-tenant:bg-white/[0.06]" />
        <div className="h-96 rounded-2xl bg-slate-100 dark-tenant:bg-white/[0.06]" />
      </div>
    </div>
  );
}

export function JourneySectionSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn("rounded-2xl bg-slate-100 dark-tenant:bg-white/[0.06] animate-pulse", className)} />
  );
}
