"use client";

import Link from "next/link";
import type { JourneyFeatureAdoption } from "@/lib/api";
import { buildFeatureAdoptionCards } from "@/lib/customer-success-journey-ui";
import { cn } from "@/lib/utils";

export function JourneyFeatureAdoptionGrid({
  features,
  delay = 0,
}: {
  features: JourneyFeatureAdoption[];
  delay?: number;
}) {
  const cards = buildFeatureAdoptionCards(features);

  return (
    <section
      className="animate-fade-in-up"
      style={{ animationDelay: `${delay}ms` }}
      aria-label="Feature adoption"
    >
      <div className="flex items-center justify-between gap-3 mb-4">
        <div>
          <h2 className="section-title text-base font-semibold text-navy-900 dark-tenant:text-slate-100">
            Feature Adoption
          </h2>
          <p className="text-xs text-gray-500 dark-tenant:text-slate-400 mt-0.5">
            How deeply your team uses each platform area
          </p>
        </div>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {cards.map((card, i) => {
          const Icon = card.icon;
          return (
            <Link
              key={card.key}
              href={card.href}
              className={cn(
                "card-premium p-4 group transition-all duration-200 hover:shadow-card-hover",
                "dark-tenant:hover:border-violet-500/25 dark-tenant:hover:shadow-glow",
                "animate-fade-in-up",
              )}
              style={{ animationDelay: `${delay + i * 60}ms` }}
            >
              <div className="flex items-start justify-between gap-2 mb-3">
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className="w-9 h-9 rounded-xl bg-brand-50 flex items-center justify-center shrink-0 dark-tenant:bg-violet-500/10">
                    <Icon size={16} className="text-brand-600 dark-tenant:text-violet-400" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-navy-900 dark-tenant:text-slate-100 truncate">
                      {card.label}
                    </p>
                    <p className="text-[10px] text-gray-400 dark-tenant:text-slate-500">{card.lastActivity}</p>
                  </div>
                </div>
                <StatusChip status={card.status} label={card.statusLabel} />
              </div>

              <div className="flex items-end justify-between gap-2 mb-2">
                <span className="text-2xl font-bold tabular-nums text-navy-900 dark-tenant:text-slate-100">
                  {card.usagePercent}%
                </span>
                <span className="text-[10px] uppercase tracking-wider text-gray-400 dark-tenant:text-slate-500">
                  usage
                </span>
              </div>

              <div className="h-1.5 rounded-full bg-gray-100 dark-tenant:bg-white/[0.08] overflow-hidden">
                <div
                  className={cn(
                    "h-full rounded-full transition-all duration-700",
                    card.status === "active"
                      ? "bg-gradient-to-r from-emerald-500 to-emerald-400"
                      : card.status === "partial"
                        ? "bg-gradient-to-r from-amber-500 to-amber-400"
                        : "bg-gradient-to-r from-slate-300 to-slate-400 dark-tenant:from-slate-600 dark-tenant:to-slate-500",
                  )}
                  style={{ width: `${card.usagePercent}%` }}
                />
              </div>
            </Link>
          );
        })}
      </div>
    </section>
  );
}

function StatusChip({ status, label }: { status: "active" | "partial" | "inactive"; label: string }) {
  return (
    <span
      className={cn(
        "text-[10px] font-semibold px-2 py-0.5 rounded-full shrink-0",
        status === "active" && "bg-emerald-100 text-emerald-800 dark-tenant:bg-emerald-500/15 dark-tenant:text-emerald-400",
        status === "partial" && "bg-amber-100 text-amber-800 dark-tenant:bg-amber-500/15 dark-tenant:text-amber-400",
        status === "inactive" && "bg-gray-100 text-gray-600 dark-tenant:bg-white/[0.06] dark-tenant:text-slate-400",
      )}
    >
      {label}
    </span>
  );
}
