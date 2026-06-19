"use client";

import { useQuery } from "@tanstack/react-query";
import { ClipboardCheck, AlertTriangle } from "lucide-react";
import { platformOpsApi } from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import { PageHeader, PageShell, ScoreCard, StatusBadge } from "@/components/ui/design-system";
import { cn } from "@/lib/utils";

export default function LaunchReadinessPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <LaunchReadinessContent />
    </AdminAuthGuard>
  );
}

function LaunchReadinessContent() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["launch-readiness"],
    queryFn: () => platformOpsApi.launchReadiness().then((r) => r.data),
  });

  if (isLoading) return <LoadingState />;
  if (isError) return <ErrorState message={String(error)} onRetry={refetch} />;

  return (
    <PageShell>
      <PageHeader
        title="Launch Readiness"
        subtitle="Final pre-launch score — security, stability, integrations, monitoring"
        icon={ClipboardCheck}
      />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <ScoreCard title="Launch Readiness Score" score={data?.readiness_score ?? 0} />
        <ScoreCard title="Pilot Readiness Score" score={data?.pilot_readiness_score ?? 0} />
      </div>

      {(data?.launch_blockers?.length ?? 0) > 0 && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl">
          <div className="flex items-center gap-2 text-red-800 font-medium mb-2">
            <AlertTriangle className="w-4 h-4" />
            Launch Blockers
          </div>
          <ul className="text-sm text-red-700 space-y-1">
            {data?.launch_blockers.map((b) => (
              <li key={b}>• {b}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        {data?.components.map((c) => (
          <div key={c.key} className="bg-white border border-gray-200 rounded-xl p-4">
            <div className="flex justify-between items-center">
              <span className="font-medium">{c.label}</span>
              <StatusBadge
                variant={c.status === "ready" ? "success" : c.status === "warning" ? "warning" : "danger"}
              >
                {c.score}
              </StatusBadge>
            </div>
            {c.details && <div className="text-sm text-gray-500 mt-1">{c.details}</div>}
            <div className="mt-2 h-2 bg-gray-100 rounded-full overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full",
                  c.score >= 75 ? "bg-emerald-500" : c.score >= 50 ? "bg-amber-500" : "bg-red-500",
                )}
                style={{ width: `${c.score}%` }}
              />
            </div>
          </div>
        ))}
      </div>

      {(data?.recommendations?.length ?? 0) > 0 && (
        <div className="p-4 bg-sky-50 border border-sky-200 rounded-xl">
          <div className="font-medium text-sky-900 mb-2">Recommendations</div>
          <ul className="text-sm text-sky-800 space-y-1">
            {data?.recommendations.map((r) => (
              <li key={r}>• {r}</li>
            ))}
          </ul>
        </div>
      )}
    </PageShell>
  );
}
