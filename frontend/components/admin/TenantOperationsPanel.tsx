"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { AlertTriangle, CheckCircle2, Circle, MessageCircle, Radio } from "lucide-react";
import { adminAuthApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { LoadingState } from "@/components/ui/PageStates";

type Props = {
  tenantId: string;
};

export function TenantOperationsPanel({ tenantId }: Props) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin-tenant-operations", tenantId],
    queryFn: () => adminAuthApi.tenantOperations(tenantId).then((r) => r.data),
    enabled: Boolean(tenantId),
  });

  if (isLoading) return <LoadingState message="Loading operations status…" />;
  if (isError || !data) {
    return (
      <p className="text-xs text-red-600">Could not load tenant operations status.</p>
    );
  }

  const readinessStyle =
    data.readiness === "ready"
      ? "bg-emerald-50 border-emerald-200 text-emerald-900"
      : "bg-amber-50 border-amber-200 text-amber-900";

  return (
    <div className="space-y-4 pt-3 border-t border-gray-100">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-gray-800">Operations readiness</p>
        <span className={cn("text-[10px] px-2 py-0.5 rounded-full border font-medium capitalize", readinessStyle)}>
          {data.readiness.replace("_", " ")}
        </span>
      </div>

      <ul className="space-y-1.5">
        {data.checks.map((check) => (
          <li key={check.id} className="flex items-start gap-2 text-xs">
            {check.ok ? (
              <CheckCircle2 size={14} className="text-emerald-600 shrink-0 mt-0.5" />
            ) : check.critical ? (
              <AlertTriangle size={14} className="text-amber-600 shrink-0 mt-0.5" />
            ) : (
              <Circle size={14} className="text-gray-300 shrink-0 mt-0.5" />
            )}
            <div className="min-w-0">
              <span className={cn("font-medium", check.ok ? "text-gray-700" : "text-gray-900")}>
                {check.label}
              </span>
              {check.detail && (
                <p className="text-gray-500 truncate" title={check.detail}>{check.detail}</p>
              )}
            </div>
          </li>
        ))}
      </ul>

      {data.publishing_readiness && (
        <div className="rounded-lg border border-gray-100 bg-gray-50/80 p-3 space-y-2">
          <p className="text-[10px] font-semibold text-gray-600 uppercase tracking-wide flex items-center gap-1">
            <Radio size={12} /> Publishing readiness
          </p>
          <p className="text-[10px] text-gray-500">
            Worker: {data.publishing_readiness.scheduled_worker_enabled ? "enabled" : "disabled"}
            {" · "}
            Accounts: {data.publishing_readiness.accounts_scope}
            {" · "}
            Telegram publish chat:{" "}
            {data.publishing_readiness.telegram_publish_chat_configured ? "configured" : "missing"}
          </p>
          <div className="flex flex-wrap gap-1">
            {data.publishing_readiness.destinations.map((d) => (
              <span
                key={d.platform}
                className={cn(
                  "text-[10px] px-1.5 py-0.5 rounded border capitalize",
                  d.status === "live" && "bg-emerald-50 border-emerald-200 text-emerald-800",
                  d.status === "mock" && "bg-slate-50 border-slate-200 text-slate-700",
                  d.status === "partial" && "bg-amber-50 border-amber-200 text-amber-800",
                  d.status === "blocked" && "bg-red-50 border-red-200 text-red-800",
                  d.status === "not_configured" && "bg-gray-50 border-gray-200 text-gray-600",
                )}
                title={[d.implementation, ...(d.blockers || [])].filter(Boolean).join("; ") || undefined}
              >
                {d.platform}: {d.implementation || d.status}
              </span>
            ))}
          </div>
          {data.publishing_readiness.blockers.length > 0 && (
            <ul className="text-[10px] text-amber-800 space-y-0.5 list-disc list-inside">
              {data.publishing_readiness.blockers.slice(0, 4).map((b) => (
                <li key={b}>{b}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {data.clients_telegram.length > 0 && (
        <div className="rounded-lg border border-gray-100 bg-gray-50/80 p-3 space-y-2">
          <p className="text-[10px] font-semibold text-gray-600 uppercase tracking-wide flex items-center gap-1">
            <MessageCircle size={12} /> Telegram intake
          </p>
          {data.clients_telegram.map((c) => (
            <div key={c.client_id} className="text-xs space-y-0.5">
              <div className="flex items-center gap-2 flex-wrap">
                <Link href={`/clients/${c.client_id}`} className="font-medium text-brand-700 hover:underline">
                  {c.company_name}
                </Link>
                {c.is_placeholder && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">placeholder</span>
                )}
                {c.duplicate_group_warning && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-100 text-red-800">duplicate group</span>
                )}
              </div>
              <p className="text-gray-500 font-mono text-[10px]">
                {c.telegram_group_id
                  ? `Group ${c.telegram_group_id}${c.telegram_group_title ? ` · ${c.telegram_group_title}` : ""}`
                  : "No group linked"}
                {c.telegram_workflow_mode ? ` · ${c.telegram_workflow_mode}` : ""}
              </p>
              {c.last_intake_at && (
                <p className="text-gray-400 text-[10px]">
                  Last intake: {format(parseISO(c.last_intake_at), "dd MMM yyyy HH:mm")}
                </p>
              )}
            </div>
          ))}
          <p className="text-[10px] text-gray-500">
            Bot: {data.telegram_health.bot_configured ? "configured" : "missing token"}
            {data.telegram_health.webhook_url ? ` · webhook set` : ""}
            {data.telegram_health.webhook_last_error
              ? ` · error: ${data.telegram_health.webhook_last_error}`
              : ""}
          </p>
        </div>
      )}

      {data.next_steps.length > 0 && (
        <div>
          <p className="text-[10px] font-semibold text-gray-600 uppercase tracking-wide mb-1">Next steps</p>
          <ol className="list-decimal list-inside text-xs text-gray-600 space-y-0.5">
            {data.next_steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
