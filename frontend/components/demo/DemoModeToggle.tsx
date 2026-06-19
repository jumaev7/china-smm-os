"use client";

import { Presentation } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDemoMode } from "@/lib/demo-mode";

export function DemoModeToggle({ className }: { className?: string }) {
  const { enabled, toggle } = useDemoMode();

  return (
    <button
      type="button"
      onClick={toggle}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors",
        enabled
          ? "border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100"
          : "border-gray-200 bg-white text-gray-600 hover:bg-gray-50",
        className,
      )}
      title={enabled ? "Demo Mode ON — click to disable" : "Demo Mode OFF — click to enable"}
    >
      <Presentation size={14} />
      <span className="hidden sm:inline">Demo Mode</span>
      <span
        className={cn(
          "rounded px-1 py-0.5 text-[10px] font-bold uppercase",
          enabled ? "bg-amber-200 text-amber-900" : "bg-gray-100 text-gray-500",
        )}
      >
        {enabled ? "ON" : "OFF"}
      </span>
    </button>
  );
}

export function DemoModeBanner() {
  const { enabled } = useDemoMode();
  if (!enabled) return null;

  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-900 flex items-center gap-2">
      <Presentation size={14} className="shrink-0 text-amber-600" />
      <span>
        <strong>Demo Mode active</strong> — showing business outcomes with guided explanations.
        Technical details are simplified for presentation.
      </span>
    </div>
  );
}
