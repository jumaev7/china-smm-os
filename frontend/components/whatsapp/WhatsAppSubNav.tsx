"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, MessageSquare, Settings2, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/lib/I18nProvider";

const TABS = [
  { href: "/whatsapp", icon: LayoutDashboard, labelKey: "whatsapp.nav.dashboard" },
  { href: "/whatsapp/messages", icon: MessageSquare, labelKey: "whatsapp.nav.messages" },
  { href: "/whatsapp/contacts", icon: Users, labelKey: "whatsapp.nav.contacts" },
  { href: "/whatsapp/accounts", icon: Settings2, labelKey: "whatsapp.nav.accounts" },
] as const;

export function WhatsAppSubNav() {
  const pathname = usePathname();
  const { t } = useTranslation();

  return (
    <nav className="flex flex-wrap gap-2 border-b border-gray-100 pb-3">
      {TABS.map(({ href, icon: Icon, labelKey }) => {
        const active =
          href === "/whatsapp"
            ? pathname === "/whatsapp"
            : pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            className={cn(
              "inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border transition-colors",
              active
                ? "bg-green-50 border-green-200 text-green-800 font-medium"
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
