"use client";

import Link from "next/link";
import { ArrowRight, X } from "lucide-react";
import type { JourneyRecommendation } from "@/lib/api";
import { recommendationImpact } from "@/lib/customer-success-journey-ui";
import { cn } from "@/lib/utils";

const PRIORITY_STYLES: Record<JourneyRecommendation["priority"], string> = {
  urgent: "bg-red-500/10 text-red-700 border-red-200 dark-tenant:bg-red-500/10 dark-tenant:text-red-400 dark-tenant:border-red-500/20",
  high: "bg-orange-500/10 text-orange-800 border-orange-200 dark-tenant:bg-orange-500/10 dark-tenant:text-orange-400 dark-tenant:border-orange-500/20",
  medium: "bg-sky-500/10 text-sky-800 border-sky-200 dark-tenant:bg-sky-500/10 dark-tenant:text-sky-400 dark-tenant:border-sky-500/20",
  low: "bg-slate-100 text-slate-600 border-slate-200 dark-tenant:bg-white/[0.04] dark-tenant:text-slate-400 dark-tenant:border-white/[0.08]",
};

export function JourneyRecommendationsPanel({
  recommendations,
  onDismiss,
  dismissingId,
  delay = 0,
}: {
  recommendations: JourneyRecommendation[];
  onDismiss: (id: string) => void;
  dismissingId?: string | null;
  delay?: number;
}) {
  const active = recommendations.filter((r) => !r.dismissed);

  return (
    <section
      className="card-premium p-6 animate-fade-in-up"
      style={{ animationDelay: `${delay}ms` }}
      aria-label="Recommendations"
    >
      <div className="mb-5">
        <h2 className="section-title text-base font-semibold text-navy-900 dark-tenant:text-slate-100">
          Recommendations
        </h2>
        <p className="text-xs text-gray-500 dark-tenant:text-slate-400 mt-0.5">
          Rule-based actions to improve customer health
        </p>
      </div>

      {active.length === 0 ? (
        <div className="text-center py-8">
          <p className="text-sm font-medium text-navy-900 dark-tenant:text-slate-200">You&apos;re on track</p>
          <p className="text-xs text-gray-500 dark-tenant:text-slate-400 mt-1">
            No open recommendations right now. Keep up the momentum.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {active.map((rec, i) => (
            <article
              key={rec.id}
              className={cn(
                "rounded-xl border border-gray-100 p-4 transition-all animate-fade-in-up",
                "dark-tenant:border-white/[0.08] dark-tenant:bg-white/[0.02]",
                "hover:border-brand-200/60 dark-tenant:hover:border-violet-500/25",
              )}
              style={{ animationDelay: `${delay + i * 50}ms` }}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2 mb-1.5">
                    <span
                      className={cn(
                        "text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border",
                        PRIORITY_STYLES[rec.priority],
                      )}
                    >
                      {rec.priority}
                    </span>
                    <span className="text-[10px] text-gray-400 dark-tenant:text-slate-500">
                      Est. impact: {recommendationImpact(rec)}
                    </span>
                  </div>
                  <h3 className="text-sm font-semibold text-navy-900 dark-tenant:text-slate-100">{rec.title}</h3>
                  <p className="text-xs text-gray-600 dark-tenant:text-slate-400 mt-1 leading-relaxed">{rec.detail}</p>
                </div>
                <button
                  type="button"
                  onClick={() => onDismiss(rec.id)}
                  disabled={dismissingId === rec.id}
                  className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors dark-tenant:hover:bg-white/[0.06] dark-tenant:hover:text-slate-300 shrink-0"
                  aria-label={`Dismiss ${rec.title}`}
                >
                  <X size={14} />
                </button>
              </div>

              {rec.href && (
                <Link
                  href={rec.href}
                  className="mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-brand-600 hover:text-brand-700 dark-tenant:text-violet-400 dark-tenant:hover:text-violet-300 transition-colors"
                >
                  Take action
                  <ArrowRight size={12} />
                </Link>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
