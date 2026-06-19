"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  CheckCircle2,
  Clock,
  Globe,
  Lightbulb,
  Send,
  Sparkles,
} from "lucide-react";
import {
  clientsApi,
  contentFactoryApi,
  Client,
  normalizeList,
} from "@/lib/api";
import { cn, PLATFORM_CONFIG } from "@/lib/utils";
import { ContentFactoryHeader, ContentFactorySubNav } from "@/components/content-factory/ContentFactorySubNav";
import { KpiCard } from "@/components/ui/design-system/KpiCard";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";
import { useState } from "react";

const STATUS_STYLE: Record<string, string> = {
  draft: "bg-gray-100 text-gray-700",
  generated: "bg-indigo-50 text-indigo-800",
  needs_review: "bg-amber-50 text-amber-800",
  approved: "bg-emerald-50 text-emerald-800",
  scheduled: "bg-sky-50 text-sky-800",
  published: "bg-teal-50 text-teal-800",
  rejected: "bg-red-50 text-red-800",
};

function QueueSection({
  title,
  items,
  emptyLabel,
}: {
  title: string;
  items: Array<{ id: string; title: string; review_status: string; company_name?: string | null; overall_score?: number | null }>;
  emptyLabel: string;
}) {
  return (
    <div className="card p-4">
      <h3 className="text-sm font-semibold text-gray-800 mb-3">{title}</h3>
      {items.length === 0 ? (
        <p className="text-xs text-gray-400 py-4 text-center">{emptyLabel}</p>
      ) : (
        <ul className="space-y-2">
          {items.slice(0, 8).map((item) => (
            <li key={item.id} className="flex items-center justify-between gap-2 text-sm border-b border-gray-50 pb-2">
              <div className="min-w-0">
                <p className="font-medium text-gray-900 truncate">{item.title}</p>
                <p className="text-[11px] text-gray-500 truncate">{item.company_name}</p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {item.overall_score != null && (
                  <span className="text-[10px] font-semibold text-teal-700">{item.overall_score}</span>
                )}
                <span className={cn("text-[10px] px-2 py-0.5 rounded-full font-medium", STATUS_STYLE[item.review_status] ?? STATUS_STYLE.generated)}>
                  {item.review_status.replace("_", " ")}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function ContentFactoryDashboardPage() {
  const [clientId, setClientId] = useState("");

  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list().then((r) => r.data),
  });

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["content-factory-dashboard", clientId],
    queryFn: () => contentFactoryApi.dashboard(clientId || undefined).then((r) => r.data),
  });

  const { data: recommendations } = useQuery({
    queryKey: ["content-factory-recommendations", clientId],
    queryFn: () => contentFactoryApi.recommendations(clientId).then((r) => r.data),
    enabled: !!clientId,
  });

  const clientOptions = normalizeList<Client>(clients);

  if (isLoading) return <LoadingState label="Loading content factory…" />;
  if (isError) return <ErrorState error={error} onRetry={() => refetch()} />;

  const kpis = data?.kpis;

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <ContentFactoryHeader
        title="AI Content Factory"
        description="Multilingual content production for manufacturers and exporters — queue, review, schedule, publish"
      />
      <ContentFactorySubNav />

      <div className="flex flex-wrap items-center gap-3 mb-6">
        <select
          className="input text-sm max-w-xs"
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
        >
          <option value="">All factories</option>
          {clientOptions.map((c) => (
            <option key={c.id} value={c.id}>{c.company_name}</option>
          ))}
        </select>
        <Link href="/content-factory/generate" className="btn-primary text-sm flex items-center gap-1.5">
          <Sparkles size={14} /> Generate content
        </Link>
        <Link href="/content-factory/review" className="btn-secondary text-sm flex items-center gap-1.5">
          <CheckCircle2 size={14} /> Review center
        </Link>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <KpiCard label="Content created" value={kpis?.content_created ?? 0} icon={BarChart3} />
        <KpiCard label="Published" value={kpis?.content_published ?? 0} icon={Send} />
        <KpiCard label="Approval rate" value={`${kpis?.approval_rate ?? 0}%`} icon={CheckCircle2} />
        <KpiCard label="Publishing rate" value={`${kpis?.publishing_rate ?? 0}%`} icon={Clock} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <QueueSection title="Content queue" items={data?.content_queue ?? []} emptyLabel="No items in queue" />
        <QueueSection title="Approval queue" items={data?.approval_queue ?? []} emptyLabel="Nothing pending approval" />
        <QueueSection title="Generated content" items={data?.generated_content ?? []} emptyLabel="Generate your first batch" />
        <QueueSection title="Publishing queue" items={data?.publishing_queue ?? []} emptyLabel="No scheduled publications" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card p-4">
          <h3 className="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-1.5">
            <Globe size={14} /> Languages used
          </h3>
          <div className="flex flex-wrap gap-2">
            {Object.entries(kpis?.languages_used ?? {}).map(([lang, count]) => (
              <span key={lang} className="text-xs px-2 py-1 rounded-lg bg-gray-50 border border-gray-100">
                {lang.toUpperCase()}: <strong>{count}</strong>
              </span>
            ))}
          </div>
          <h4 className="text-xs font-medium text-gray-500 mt-4 mb-2">Top content types</h4>
          {(kpis?.top_content_types ?? []).length === 0 ? (
            <EmptyState
              title="No Content Yet"
              description="Upload product photos from Telegram or load demo content to see type breakdown."
              action={
                <Link href="/demo-tour" className="btn-primary text-xs">
                  Load demo content
                </Link>
              }
              className="py-6"
            />
          ) : (
            <ul className="space-y-1">
              {kpis?.top_content_types.map((t) => (
                <li key={t.type} className="flex justify-between text-sm">
                  <span className="text-gray-700">{t.type}</span>
                  <span className="font-semibold tabular-nums">{t.count}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card p-4">
          <h3 className="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-1.5">
            <Lightbulb size={14} /> AI recommendations
          </h3>
          {!clientId ? (
            <p className="text-xs text-gray-500">Select a factory to see recommendations</p>
          ) : recommendations ? (
            <div className="space-y-3 text-sm">
              <div>
                <p className="text-xs text-gray-500 mb-1">Best posting times</p>
                <p>{recommendations.best_posting_times.join(", ")}</p>
              </div>
              {recommendations.missing_content_categories.length > 0 && (
                <div>
                  <p className="text-xs text-gray-500 mb-1">Missing categories</p>
                  <ul className="list-disc pl-4 text-gray-700">
                    {recommendations.missing_content_categories.map((c) => (
                      <li key={c.category}>{c.label}</li>
                    ))}
                  </ul>
                </div>
              )}
              {recommendations.suggested_buyer_content.slice(0, 3).map((tip) => (
                <p key={tip} className="text-xs text-gray-600 border-l-2 border-teal-200 pl-2">{tip}</p>
              ))}
            </div>
          ) : (
            <p className="text-xs text-gray-400">Loading recommendations…</p>
          )}
        </div>
      </div>
    </div>
  );
}
