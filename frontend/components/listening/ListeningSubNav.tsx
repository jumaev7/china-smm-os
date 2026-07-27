"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/listening", label: "Overview", exact: true },
  { href: "/listening/mentions", label: "Mentions" },
  { href: "/listening/projects", label: "Configuration" },
  { href: "/listening/runs", label: "Ingestion runs" },
];

export function ListeningSubNav() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Social Listening sections"
      className="mb-6 flex flex-wrap gap-2 border-b border-slate-200 pb-3 dark-tenant:border-slate-800"
    >
      {LINKS.map((link) => {
        const active = link.exact
          ? pathname === link.href
          : pathname === link.href || pathname.startsWith(`${link.href}/`);
        return (
          <Link
            key={link.href}
            href={link.href}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              active
                ? "bg-slate-900 text-white dark-tenant:bg-slate-100 dark-tenant:text-slate-900"
                : "text-slate-600 hover:bg-slate-100 dark-tenant:text-slate-300 dark-tenant:hover:bg-slate-800",
            )}
            aria-current={active ? "page" : undefined}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
