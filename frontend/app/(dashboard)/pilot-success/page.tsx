"use client";

import { useQuery } from "@tanstack/react-query";
import { TrendingUp } from "lucide-react";
import { platformOpsApi } from "@/lib/api";
import { AdminAuthGuard } from "@/components/auth/AdminAuthGuard";
import { ErrorState, LoadingState } from "@/components/ui/PageStates";
import { PageHeader, PageShell, ScoreCard } from "@/components/ui/design-system";
import { cn } from "@/lib/utils";

export default function PilotSuccessPage() {
  return (
    <AdminAuthGuard requireAdmin>
      <PilotSuccessContent />
    </AdminAuthGuard>
  );
}

function PilotSuccessContent() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["pilot-success"],
    queryFn: () => platformOpsApi.pilotSuccess().then((r) => r.data),
    refetchInterval: 60_000,
  });

  if (isLoading) return <LoadingState />;
  if (isError) return <ErrorState message={String(error)} onRetry={refetch} />;

  return (
    <PageShell>
      <PageHeader
        title="Pilot Success Dashboard"
        subtitle="Onboarding, usage, adoption, and customer success metrics"
        icon={TrendingUp}
      />
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <ScoreCard title="Overall Score" score={data?.overall_score ?? 0} />
        <ScoreCard title="Active Pilots" score={data?.pilot_factories_active ?? 0} />
        <ScoreCard title="Total Pilots" score={data?.pilot_factories_total ?? 0} />
        <ScoreCard title="Open Feedback" score={data?.feedback_open_count ?? 0} />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {data?.metrics.map((m) => (
          <div
            key={m.key}
            className={cn(
              "bg-white border rounded-xl p-4",
              m.status === "ok" ? "border-gray-200" : "border-amber-200",
            )}
          >
            <div className="text-sm text-gray-500">{m.label}</div>
            <div className="text-2xl font-bold tabular-nums mt-1">{m.value}</div>
          </div>
        ))}
      </div>
    </PageShell>
  );
}
