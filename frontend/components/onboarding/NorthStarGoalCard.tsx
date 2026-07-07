"use client";

import { Check, Loader2 } from "lucide-react";
import type { NorthStarGoalCardDef } from "@/lib/onboarding-wizard";
import { cn } from "@/lib/utils";

export function NorthStarGoalCard({
  goal,
  selected,
  onSelect,
  saving = false,
  index = 0,
}: {
  goal: NorthStarGoalCardDef;
  selected: boolean;
  onSelect: () => void;
  saving?: boolean;
  index?: number;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={saving}
      className={cn(
        "relative w-full text-left rounded-2xl border p-5 transition-all duration-300 animate-fade-in-up",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2",
        "dark-tenant:focus-visible:ring-violet-500 dark-tenant:focus-visible:ring-offset-surface-dark-page",
        selected
          ? "border-brand-400 bg-brand-50/80 ring-2 ring-brand-200 shadow-card dark-tenant:border-violet-500/50 dark-tenant:bg-violet-500/10 dark-tenant:ring-violet-500/30"
          : "border-slate-200 bg-white shadow-card hover:border-brand-200 hover:shadow-card-hover dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-card dark-tenant:hover:border-violet-500/30",
      )}
      style={{ animationDelay: `${index * 70}ms` }}
      aria-pressed={selected}
    >
      {selected ? (
        <div className="absolute top-0 left-5 right-5 h-0.5 rounded-full bg-gradient-to-r from-brand-400 to-violet-400" />
      ) : null}

      <div className="flex items-start gap-4">
        <span className="text-2xl shrink-0" aria-hidden>
          {goal.icon}
        </span>
        <div className="flex-1">
          <div className="flex items-center justify-between gap-2">
            <h3 className="font-semibold text-navy-900 dark-tenant:text-slate-100">{goal.title}</h3>
            {saving && selected ? (
              <Loader2 size={18} className="animate-spin text-brand-600 shrink-0 dark-tenant:text-violet-400" />
            ) : selected ? (
              <Check size={18} className="text-brand-600 shrink-0 dark-tenant:text-violet-400" />
            ) : (
              <span
                className="w-5 h-5 rounded-full border-2 border-slate-200 shrink-0 dark-tenant:border-white/20"
                aria-hidden
              />
            )}
          </div>
          <p className="text-sm text-gray-600 mt-1.5 leading-relaxed dark-tenant:text-slate-400">
            {goal.description}
          </p>
        </div>
      </div>
    </button>
  );
}
