import { Suspense } from "react";
import { I18nClientProvider } from "@/components/I18nClientProvider";
import { DashboardShell } from "@/components/layout/DashboardShell";
import { DashboardRouteGuard } from "@/components/auth/DashboardRouteGuard";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <I18nClientProvider>
      <Suspense fallback={null}>
        <DashboardShell>
          <DashboardRouteGuard>{children}</DashboardRouteGuard>
        </DashboardShell>
      </Suspense>
    </I18nClientProvider>
  );
}
