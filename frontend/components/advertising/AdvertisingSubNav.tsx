"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const TABS = [
  { href: "/advertising", label: "Overview", exact: true },
  { href: "/advertising/accounts", label: "Accounts" },
  { href: "/advertising/campaigns", label: "Campaigns" },
  { href: "/advertising/creatives", label: "Creatives" },
  { href: "/advertising/decision-support", label: "Decision Support" },
  { href: "/advertising/simulator", label: "Budget Simulator" },
  { href: "/advertising/experiments", label: "Experiments" },
  { href: "/advertising/attribution", label: "Attribution" },
  { href: "/advertising/anomalies", label: "Anomalies" },
] as const;

export function AdvertisingSubNav() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Advertising sections"
      className="flex flex-wrap gap-2 border-b border-slate-200 pb-3 dark-tenant:border-slate-800"
    >
      {TABS.map(({ href, label, ...rest }) => {
        const exact = "exact" in rest && rest.exact;
        const active = exact
          ? pathname === href
          : pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            className={cn(
              "inline-flex items-center text-sm px-3 py-1.5 rounded-lg border transition-colors",
              active
                ? "bg-slate-900 border-slate-900 text-white font-medium dark-tenant:bg-slate-100 dark-tenant:border-slate-100 dark-tenant:text-slate-900"
                : "border-slate-200 text-slate-600 hover:border-slate-300 hover:text-slate-900 dark-tenant:border-slate-800 dark-tenant:text-slate-400 dark-tenant:hover:border-slate-700 dark-tenant:hover:text-slate-200",
            )}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
