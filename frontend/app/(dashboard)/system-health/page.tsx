"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, CheckCircle2, AlertTriangle, XCircle } from "lucide-react";
import { platformOpsApi } from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import { PageHeader, PageShell, StatusBadge } from "@/components/ui/design-system";
import { cn } from "@/lib/utils";

const ICON = {
  ok: CheckCircle2,
  degraded: AlertTriangle,
  warning: AlertTriangle,
  error: XCircle,
};

export default function SystemHealthPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <SystemHealthContent />
    </AdminAuthGuard>
  );
}

function SystemHealthContent() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["platform-system-health"],
    queryFn: () => platformOpsApi.systemHealth().then((r) => r.data),
    refetchInterval: 60_000,
  });

  if (isLoading) return <LoadingState />;
  if (isError) return <ErrorState error={error} onRetry={refetch} />;

  const overall = data?.overall_status ?? "unknown";

  return (
    <PageShell>
      <PageHeader
        title="System Health"
        subtitle="API, database, queue, jobs, webhooks, and integrations"
        icon={Activity}
        actions={
          <StatusBadge
            variant={overall === "ok" ? "success" : overall === "error" ? "danger" : "warning"}
          >
            {overall}
          </StatusBadge>
        }
      />
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {data?.components.map((comp) => {
          const Icon = ICON[comp.status as keyof typeof ICON] ?? Activity;
          return (
            <div
              key={comp.key}
              className={cn(
                "bg-white border rounded-xl p-4",
                comp.status === "ok" ? "border-gray-200" : "border-amber-200",
              )}
            >
              <div className="flex items-start gap-3">
                <Icon
                  className={cn(
                    "w-5 h-5 shrink-0 mt-0.5",
                    comp.status === "ok" ? "text-emerald-600" : "text-amber-600",
                  )}
                />
                <div>
                  <div className="font-medium text-gray-900">{comp.label}</div>
                  <div className="text-sm text-gray-600 mt-1">{comp.message}</div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </PageShell>
  );
}
