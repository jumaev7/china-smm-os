"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ClipboardCheck, Factory, LayoutDashboard, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

const TABS = [
  { href: "/content-factory", icon: LayoutDashboard, label: "Dashboard" },
  { href: "/content-factory/generate", icon: Sparkles, label: "Generate" },
  { href: "/content-factory/review", icon: ClipboardCheck, label: "Review" },
] as const;

export function ContentFactorySubNav() {
  const pathname = usePathname();

  return (
    <nav className="flex flex-wrap gap-2 border-b border-gray-100 pb-3 mb-6">
      {TABS.map(({ href, icon: Icon, label }) => {
        const active =
          href === "/content-factory"
            ? pathname === "/content-factory"
            : pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            className={cn(
              "inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border transition-colors",
              active
                ? "bg-teal-50 border-teal-200 text-teal-800 font-medium"
                : "border-gray-200 text-gray-600 hover:border-gray-300 hover:text-gray-900",
            )}
          >
            <Icon size={14} />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

export function ContentFactoryHeader({ title, description }: { title: string; description?: string }) {
  return (
    <div className="mb-2">
      <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
        <Factory size={20} className="text-teal-600" />
        {title}
      </h1>
      {description && <p className="text-sm text-gray-500 mt-1">{description}</p>}
    </div>
  );
}
