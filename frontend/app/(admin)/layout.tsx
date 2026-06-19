"use client";

import Link from "next/link";
import { Suspense } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import {
  Activity,
  ArrowLeft,
  ClipboardCheck,
  CreditCard,
  FileText,
  LogOut,
  Presentation,
  Settings,
  Shield,
  ShieldAlert,
  Users,
} from "lucide-react";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { useAdminAuth } from "@/lib/admin-auth-store";
import { useDocumentInteractionCleanup } from "@/lib/useDocumentInteractionCleanup";

const NAV = [
  { href: "/tenants", label: "Tenants", icon: Users },
  { href: "/billing", label: "Billing", icon: CreditCard },
  { href: "/billing?tab=plans", label: "Plans", icon: FileText },
  { href: "/billing?tab=licenses", label: "Licenses", icon: Shield },
  { href: "/pilot-program", label: "Pilot Program", icon: ClipboardCheck },
  { href: "/system-health", label: "System Health", icon: Activity },
  { href: "/audit-logs", label: "Audit Logs", icon: FileText },
  { href: "/error-tracking", label: "Error Tracking", icon: ShieldAlert },
  { href: "/pilot-demo-mode", label: "Demo Management", icon: Presentation },
  { href: "/admin-settings", label: "Platform Settings", icon: Settings },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center text-sm text-slate-400">
          Loading platform admin…
        </div>
      }
    >
      <AdminLayoutContent>{children}</AdminLayoutContent>
    </Suspense>
  );
}

function AdminLayoutContent({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { user, logout } = useAdminAuth();

  useDocumentInteractionCleanup(pathname);

  return (
    <AdminAuthGuard>
      <div className="min-h-screen bg-slate-950 text-slate-100">
        <header className="border-b border-slate-800 bg-slate-900">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
            <div className="flex items-center gap-2">
              <Shield className="text-indigo-400" size={20} />
              <span className="font-semibold">Platform Admin</span>
              {user ? (
                <span className="rounded-full bg-slate-800 px-2 py-0.5 text-xs text-slate-400">
                  {user.email} · {user.role}
                </span>
              ) : null}
            </div>
            <div className="flex items-center gap-2">
              <Link
                href="/dashboard"
                className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
              >
                <ArrowLeft size={14} />
                Product workspace
              </Link>
              <button
              type="button"
              onClick={() => logout()}
              className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800"
            >
              <LogOut size={14} />
              Logout
            </button>
            </div>
          </div>
          <nav className="mx-auto flex max-w-6xl gap-1 px-4 pb-2">
            {NAV.map(({ href, label, icon: Icon }) => {
              const [path, queryString] = href.split("?");
              const pathMatches = pathname === path || pathname.startsWith(`${path}/`);
              let active = pathMatches;
              if (active && queryString) {
                const expected = new URLSearchParams(queryString);
                for (const [key, value] of expected.entries()) {
                  if (searchParams.get(key) !== value) active = false;
                }
              } else if (active && path === "/billing" && searchParams.get("tab")) {
                active = false;
              }
              return (
                <Link
                  key={`${href}-${label}`}
                  href={href}
                  className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm ${
                    active ? "bg-indigo-600 text-white" : "text-slate-400 hover:bg-slate-800 hover:text-white"
                  }`}
                >
                  <Icon size={14} />
                  {label}
                </Link>
              );
            })}
          </nav>
        </header>
        <main>{children}</main>
      </div>
    </AdminAuthGuard>
  );
}
