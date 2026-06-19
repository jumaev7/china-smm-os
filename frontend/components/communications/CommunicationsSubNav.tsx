"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CalendarClock, FileText, Inbox, LayoutDashboard } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/lib/I18nProvider";

const TABS = [
  { href: "/communications", icon: LayoutDashboard, labelKey: "communicationsHub.nav.dashboard" },
  { href: "/communications/inbox", icon: Inbox, labelKey: "communicationsHub.nav.inbox" },
  { href: "/communications/followups", icon: CalendarClock, labelKey: "communicationsHub.nav.followups" },
  { href: "/communications/templates", icon: FileText, labelKey: "communicationsHub.nav.templates" },
] as const;

export function CommunicationsSubNav() {
  const pathname = usePathname();
  const { t } = useTranslation();

  return (
    <nav className="flex flex-wrap gap-2 border-b border-gray-100 pb-3">
      {TABS.map(({ href, icon: Icon, labelKey }) => {
        const active =
          href === "/communications"
            ? pathname === "/communications"
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
