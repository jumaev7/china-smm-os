"use client";

import Link from "next/link";
import { CheckCircle2, Palette, ExternalLink } from "lucide-react";
import {
  DESIGN_SYSTEM_REGISTRY,
  DESIGN_SYSTEM_VERSION,
  UPGRADED_PAGES,
} from "@/lib/design-system";
import { StatusBadge } from "@/components/ui/design-system";

export function UiHealthSection() {
  return (
    <div className="card-premium p-5 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="section-title flex items-center gap-2">
            <Palette size={16} className="text-brand-600" />
            UI / Design System Health
          </h2>
          <p className="text-xs text-gray-500 mt-1">
            Premium Enterprise SaaS visual layer — {DESIGN_SYSTEM_REGISTRY.id} v
            {DESIGN_SYSTEM_VERSION}
          </p>
        </div>
        <StatusBadge variant="success" dot>
          Active
        </StatusBadge>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
        <div className="rounded-xl border border-gray-100 bg-slate-50/50 px-3 py-2.5">
          <p className="text-[10px] uppercase tracking-wide text-gray-400">Theme</p>
          <p className="font-medium text-navy-900 mt-0.5">Navy · White · Blue</p>
          <p className="text-gray-500 mt-0.5">Accent: Gold / Cyan</p>
        </div>
        <div className="rounded-xl border border-gray-100 bg-slate-50/50 px-3 py-2.5">
          <p className="text-[10px] uppercase tracking-wide text-gray-400">Components</p>
          <p className="font-medium text-navy-900 mt-0.5 tabular-nums">
            {DESIGN_SYSTEM_REGISTRY.components.length} registered
          </p>
        </div>
        <div className="rounded-xl border border-gray-100 bg-slate-50/50 px-3 py-2.5">
          <p className="text-[10px] uppercase tracking-wide text-gray-400">Priority pages</p>
          <p className="font-medium text-navy-900 mt-0.5 tabular-nums">
            {UPGRADED_PAGES.length} upgraded
          </p>
        </div>
        <div className="rounded-xl border border-gray-100 bg-slate-50/50 px-3 py-2.5">
          <p className="text-[10px] uppercase tracking-wide text-gray-400">Registry</p>
          <p className="font-mono text-[10px] text-gray-600 mt-0.5 break-all">
            frontend/lib/design-system.ts
          </p>
        </div>
      </div>

      <div>
        <p className="text-xs font-semibold text-gray-700 mb-2">Upgraded routes (v1)</p>
        <ul className="grid sm:grid-cols-2 gap-2">
          {UPGRADED_PAGES.map((page) => (
            <li key={page.route}>
              <Link
                href={page.route}
                className="flex items-center justify-between gap-2 rounded-lg border border-gray-100 px-3 py-2 text-sm hover:border-brand-200 hover:bg-brand-50/30 transition-colors group"
              >
                <span className="flex items-center gap-2 min-w-0">
                  <CheckCircle2 size={14} className="text-success-600 shrink-0" />
                  <span className="font-medium text-navy-900 truncate">{page.name}</span>
                </span>
                <ExternalLink
                  size={12}
                  className="text-gray-300 group-hover:text-brand-500 shrink-0"
                />
              </Link>
            </li>
          ))}
        </ul>
      </div>

      <p className="text-[10px] text-gray-400">
        Tokens: spacing, typography, colors, shadows, radius, cards, tables, badges, empty &
        loading states. Visual-only — no API or schema changes.
      </p>
    </div>
  );
}
