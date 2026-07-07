"use client";

import { Package, Sparkles, UserPlus, FileText, Calendar } from "lucide-react";

const AUTO_CONFIG_ITEMS = [
  { icon: UserPlus, label: "Sample lead & buyer", detail: "See how CRM records look before your first inquiry" },
  { icon: Package, label: "Pipeline deal", detail: "A deal in your executive pipeline for orientation" },
  { icon: FileText, label: "Welcome content draft", detail: "Pre-written post ready for AI customization" },
  { icon: Calendar, label: "Scheduled publication", detail: "Example calendar entry to preview publishing flow" },
  { icon: Sparkles, label: "Starter proposal", detail: "Commercial quote template linked to sample buyer" },
] as const;

export function OnboardingAutoConfigPanel() {
  return (
    <div className="rounded-2xl border border-emerald-200 bg-gradient-to-br from-emerald-50/80 to-white p-5 shadow-card animate-fade-in-up">
      <div className="flex items-center gap-2 text-emerald-800 mb-3">
        <Sparkles size={18} />
        <span className="font-semibold text-sm">We pre-configured your workspace</span>
      </div>
      <p className="text-sm text-emerald-900/80 leading-relaxed mb-4">
        Sample data lets you explore CRM, content, and proposals immediately — nothing goes live until you publish.
      </p>
      <ul className="space-y-2">
        {AUTO_CONFIG_ITEMS.map(({ icon: Icon, label, detail }, i) => (
          <li
            key={label}
            className="flex gap-3 rounded-xl bg-white/70 border border-emerald-100 px-3 py-2.5 animate-fade-in-up"
            style={{ animationDelay: `${i * 60}ms` }}
          >
            <Icon size={16} className="text-emerald-600 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-navy-900">{label}</p>
              <p className="text-xs text-gray-500">{detail}</p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
