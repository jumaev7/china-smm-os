"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, BarChart3, DollarSign, LayoutDashboard, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/lib/I18nProvider";

const TABS = [
  { href: "/customer-success", icon: LayoutDashboard, labelKey: "customerSuccess.nav.overview" },
  { href: "/customer-success/roi", icon: DollarSign, labelKey: "customerSuccess.nav.roi" },
  { href: "/customer-success/adoption", icon: Activity, labelKey: "customerSuccess.nav.adoption" },
  { href: "/customer-success/business-impact", icon: TrendingUp, labelKey: "customerSuccess.nav.businessImpact" },
] as const;

export function CustomerSuccessSubNav() {
  const pathname = usePathname();
  const { t } = useTranslation();

  return (
    <nav className="flex flex-wrap gap-2 border-b border-gray-100 pb-3">
      {TABS.map(({ href, icon: Icon, labelKey }) => {
        const active =
          href === "/customer-success"
            ? pathname === "/customer-success"
            : pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            className={cn(
              "inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border transition-colors",
              active
                ? "bg-brand-50 border-brand-200 text-brand-800 font-medium"
                : "border-gray-200 text-gray-600 hover:border-gray-300 hover:text-gray-900",
            )}
          >
            <Icon size={14} />
            {t(labelKey)}
          </Link>
        );
      })}
    </nav>
  );
}

export function CustomerSuccessPageHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="page-title flex items-center gap-2">
          <BarChart3 size={22} className="text-brand-600" />
          {title}
        </h1>
        {subtitle && <p className="text-sm text-gray-500 mt-1">{subtitle}</p>}
      </div>
      <CustomerSuccessSubNav />
    </div>
  );
}
