"use client";

import { useEffect, useState } from "react";
import { PartyPopper, X } from "lucide-react";
import type { OnboardingMilestoneMessage } from "@/lib/api";
import { cn } from "@/lib/utils";

export function OnboardingCelebration({
  milestones,
}: {
  milestones: OnboardingMilestoneMessage[];
}) {
  const [visible, setVisible] = useState(false);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  const fresh = milestones.filter((m) => !dismissed.has(m.step_id));

  useEffect(() => {
    if (fresh.length > 0) {
      setVisible(true);
      const timer = setTimeout(() => setVisible(false), 8000);
      return () => clearTimeout(timer);
    }
  }, [fresh.length, milestones]);

  if (!visible || fresh.length === 0) return null;

  return (
    <div
      className="fixed bottom-6 right-6 z-50 max-w-sm animate-scale-in"
      role="status"
      aria-live="polite"
    >
      <div className="relative rounded-2xl border border-emerald-200 bg-white shadow-elevated overflow-hidden">
        <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-emerald-400 via-brand-400 to-violet-400" />
        <ConfettiDots />
        <div className="p-5 pr-10">
          <div className="flex items-center gap-2 text-emerald-700 mb-2">
            <PartyPopper size={20} />
            <span className="text-sm font-bold uppercase tracking-wide">Milestone reached</span>
          </div>
          {fresh.map((m) => (
            <p key={m.step_id} className="text-sm text-navy-900 leading-relaxed">
              {m.message}
            </p>
          ))}
        </div>
        <button
          type="button"
          onClick={() => {
            setVisible(false);
            setDismissed((prev) => new Set([...prev, ...fresh.map((m) => m.step_id)]));
          }}
          className="absolute top-3 right-3 p-1 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-slate-100"
          aria-label="Dismiss"
        >
          <X size={16} />
        </button>
      </div>
    </div>
  );
}

function ConfettiDots() {
  const dots = [
    { top: "12%", left: "8%", color: "bg-emerald-400", delay: "0ms" },
    { top: "20%", left: "85%", color: "bg-brand-400", delay: "100ms" },
    { top: "70%", left: "12%", color: "bg-violet-400", delay: "200ms" },
    { top: "60%", left: "90%", color: "bg-amber-400", delay: "150ms" },
    { top: "40%", left: "95%", color: "bg-rose-400", delay: "50ms" },
  ];

  return (
    <>
      {dots.map((d, i) => (
        <span
          key={i}
          className={cn("absolute w-2 h-2 rounded-full animate-celebrate opacity-80", d.color)}
          style={{ top: d.top, left: d.left, animationDelay: d.delay }}
        />
      ))}
    </>
  );
}
