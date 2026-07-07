"use client";

import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  Compass,
  FileText,
  LayoutDashboard,
  Megaphone,
  Sparkles,
} from "lucide-react";
import toast from "react-hot-toast";
import type { ExecutiveWalkthroughPanel, ExecutiveWalkthroughState } from "@/lib/api";
import { tenantOnboardingApi } from "@/lib/api";
import { cn } from "@/lib/utils";

const PANEL_ICONS: Record<string, typeof LayoutDashboard> = {
  executive_dashboard: LayoutDashboard,
  crm_pipeline: BarChart3,
  publishing: Megaphone,
  content: FileText,
  growth_center: Compass,
};

export function ExecutiveWalkthroughPanels({
  walkthrough,
  compact = false,
}: {
  walkthrough: ExecutiveWalkthroughState;
  compact?: boolean;
}) {
  const qc = useQueryClient();

  const recordPanel = useMutation({
    mutationFn: (panel_id: string) => tenantOnboardingApi.recordWalkthroughPanel(panel_id).then((r) => r.data),
    onSuccess: (data) => {
      qc.setQueryData(["tenant-onboarding-readiness"], data.readiness);
      qc.invalidateQueries({ queryKey: ["tenant-onboarding"] });
    },
    onError: () => toast.error("Could not record tour progress"),
  });

  function explore(panel: ExecutiveWalkthroughPanel) {
    if (!panel.completed) {
      recordPanel.mutate(panel.id);
    }
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-amber-700">Executive walkthrough</p>
          <h2 className="text-lg font-semibold text-navy-900 mt-1">
            {walkthrough.completed
              ? "Leadership tour complete"
              : "See where your business lives in the platform"}
          </h2>
          <p className="text-sm text-gray-500 mt-1 max-w-xl">
            Visit each area once to understand pipeline KPIs, publishing, content, and growth insights — built for
            factory leadership.
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span className="font-semibold tabular-nums text-navy-900">
            {walkthrough.completed_panels}/{walkthrough.total_panels}
          </span>
          <span className="text-gray-400">panels explored</span>
        </div>
      </div>

      <div
        className={cn(
          "grid gap-3",
          compact ? "sm:grid-cols-2 lg:grid-cols-3" : "sm:grid-cols-2 xl:grid-cols-5",
        )}
      >
        {walkthrough.panels.map((panel, i) => (
          <PanelCard
            key={panel.id}
            panel={panel}
            index={i}
            onExplore={() => explore(panel)}
            pending={recordPanel.isPending && recordPanel.variables === panel.id}
          />
        ))}
      </div>

      {!walkthrough.completed ? (
        <Link
          href="/onboarding/executive"
          className="inline-flex items-center gap-2 text-sm font-medium text-amber-700 hover:text-amber-800"
        >
          Open guided executive tour
          <ArrowRight size={14} />
        </Link>
      ) : (
        <div className="flex items-center gap-2 rounded-xl bg-amber-50 border border-amber-100 px-4 py-3 text-sm text-amber-900 animate-celebrate">
          <Sparkles size={16} className="text-amber-600" />
          Executive visibility unlocked — your leadership dashboard is ready.
        </div>
      )}
    </section>
  );
}

function PanelCard({
  panel,
  index,
  onExplore,
  pending,
}: {
  panel: ExecutiveWalkthroughPanel;
  index: number;
  onExplore: () => void;
  pending: boolean;
}) {
  const Icon = PANEL_ICONS[panel.id] ?? Compass;

  return (
    <div
      className={cn(
        "relative rounded-2xl border p-4 transition-all duration-300 animate-fade-in-up",
        panel.completed
          ? "border-emerald-100 bg-emerald-50/50"
          : "border-amber-100 bg-white hover:border-amber-200 hover:shadow-card-hover",
      )}
      style={{ animationDelay: `${index * 80}ms` }}
    >
      <div className="flex items-start justify-between gap-2 mb-3">
        <div
          className={cn(
            "w-10 h-10 rounded-xl flex items-center justify-center",
            panel.completed ? "bg-emerald-100 text-emerald-700" : "bg-amber-50 text-amber-700",
          )}
        >
          <Icon size={20} />
        </div>
        {panel.completed ? (
          <CheckCircle2 size={18} className="text-emerald-500 shrink-0" />
        ) : (
          <span className="text-[10px] font-medium text-gray-400">~{panel.estimated_minutes}m</span>
        )}
      </div>
      <h3 className="font-semibold text-sm text-navy-900">{panel.label}</h3>
      <p className="text-xs text-gray-500 mt-1 mb-3">
        {panel.completed ? "Explored" : "Tap to explore this area"}
      </p>
      <Link
        href={panel.route}
        onClick={onExplore}
        className={cn(
          "inline-flex items-center gap-1.5 text-xs font-semibold rounded-lg px-3 py-1.5 transition-colors",
          panel.completed
            ? "text-emerald-700 bg-emerald-100/80 hover:bg-emerald-100"
            : "text-white bg-amber-600 hover:bg-amber-700",
          pending && "opacity-70 pointer-events-none",
        )}
      >
        {panel.completed ? "Revisit" : pending ? "Opening…" : "Explore"}
        <ArrowRight size={12} />
      </Link>
    </div>
  );
}
