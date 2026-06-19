"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Columns3,
  ExternalLink,
  Loader2,
  RefreshCw,
  Send,
  Check,
  Calendar,
  RotateCcw,
  ArrowLeft,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  campaignsApi,
  clientsApi,
  Client,
  Campaign,
  contentPipelineApi,
  PipelineBoardCard,
  PipelineStage,
  PIPELINE_STAGES,
  PIPELINE_STAGE_LABELS,
  normalizeList,
  type ContentStatus,
} from "@/lib/api";
import { PLATFORM_CONFIG } from "@/lib/utils";
import { formatScheduledLocal } from "@/lib/datetime";
import { ClientReviewStatusBadge } from "@/components/content/ClientReviewStatus";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

const PLATFORMS = ["instagram", "facebook", "tiktok", "telegram", "linkedin"];

function confirmAction(message: string): boolean {
  return window.confirm(message);
}

function PipelineCard({
  card,
  onTransition,
  onRetry,
  busy,
}: {
  card: PipelineBoardCard;
  onTransition: (stage: PipelineStage, extra?: { scheduled_for?: string; reason?: string }) => void;
  onRetry: () => void;
  busy: boolean;
}) {
  const thumb = card.thumbnail_url || card.media_url;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm space-y-2 text-xs">
      {thumb ? (
        <div className="rounded overflow-hidden bg-gray-100 aspect-video max-h-24">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={thumb} alt="" className="w-full h-full object-cover" />
        </div>
      ) : null}
      <p className="font-medium text-gray-900 line-clamp-2">
        {card.caption_preview || "Untitled content"}
      </p>
      <p className="text-gray-500">{card.client_name}</p>
      {card.campaign_name ? (
        <p className="text-[10px] text-violet-700">{card.campaign_name}</p>
      ) : null}
      <div className="flex flex-wrap gap-1">
        {card.platforms.map((p) => (
          <span key={p} className="text-[9px] px-1 py-0.5 rounded bg-gray-100 text-gray-600 capitalize">
            {PLATFORM_CONFIG[p as keyof typeof PLATFORM_CONFIG]?.label ?? p}
          </span>
        ))}
      </div>
      {card.scheduled_for ? (
        <p className="text-[10px] text-gray-500 flex items-center gap-1">
          <Calendar size={10} />
          {formatScheduledLocal(card.scheduled_for)}
        </p>
      ) : null}
      {card.client_review_status ? (
        <ClientReviewStatusBadge
          item={{
            client_review_status: card.client_review_status as "pending" | "approved" | "changes_requested",
            client_review_feedback: null,
            client_approved_at: null,
            client_review_preview_sent_at: null,
            client_review_preview_error: null,
            status: card.status as ContentStatus,
            approved_at: card.approved_at ?? undefined,
          }}
          compact
        />
      ) : null}

      <div className="flex flex-wrap gap-1 pt-1 border-t border-gray-100">
        <Link
          href={`/content/${card.id}`}
          className="text-[10px] px-2 py-1 rounded border border-gray-200 hover:bg-gray-50 inline-flex items-center gap-0.5"
        >
          Open
          <ExternalLink size={10} />
        </Link>
        {card.pipeline_stage === "draft" && card.allowed_transitions.includes("internal_review") ? (
          <button
            type="button"
            disabled={busy}
            className="text-[10px] px-2 py-1 rounded border border-brand-200 text-brand-800 hover:bg-brand-50"
            onClick={() => onTransition("internal_review")}
          >
            Internal review
          </button>
        ) : null}
        {card.allowed_transitions.includes("client_review") ? (
          <button
            type="button"
            disabled={busy}
            className="text-[10px] px-2 py-1 rounded border border-sky-200 text-sky-800 hover:bg-sky-50 inline-flex items-center gap-0.5"
            onClick={() => {
              if (confirmAction("Send this content to client review?")) onTransition("client_review");
            }}
          >
            <Send size={10} />
            Client review
          </button>
        ) : null}
        {card.allowed_transitions.includes("approved") ? (
          <button
            type="button"
            disabled={busy}
            className="text-[10px] px-2 py-1 rounded border border-emerald-200 text-emerald-800 hover:bg-emerald-50 inline-flex items-center gap-0.5"
            onClick={() => {
              if (confirmAction("Approve this content?")) onTransition("approved");
            }}
          >
            <Check size={10} />
            Approve
          </button>
        ) : null}
        {card.allowed_transitions.includes("scheduled") ? (
          <button
            type="button"
            disabled={busy}
            className="text-[10px] px-2 py-1 rounded border border-violet-200 text-violet-800 hover:bg-violet-50"
            onClick={() => {
              const raw = window.prompt("Schedule for (YYYY-MM-DDTHH:mm local):");
              if (!raw) return;
              const iso = new Date(raw).toISOString();
              if (confirmAction(`Schedule for ${raw}?`)) onTransition("scheduled", { scheduled_for: iso });
            }}
          >
            Schedule
          </button>
        ) : null}
        {card.pipeline_stage === "failed" ? (
          <button
            type="button"
            disabled={busy}
            className="text-[10px] px-2 py-1 rounded border border-amber-200 text-amber-800 hover:bg-amber-50 inline-flex items-center gap-0.5"
            onClick={() => {
              if (confirmAction("Retry publishing this content?")) onRetry();
            }}
          >
            <RotateCcw size={10} />
            Retry publish
          </button>
        ) : null}
        {card.allowed_transitions.includes("draft") && card.pipeline_stage !== "draft" ? (
          <button
            type="button"
            disabled={busy}
            className="text-[10px] px-2 py-1 rounded border border-gray-200 text-gray-600 hover:bg-gray-50"
            onClick={() => {
              if (confirmAction("Move back to draft?")) onTransition("draft");
            }}
          >
            <ArrowLeft size={10} />
            Draft
          </button>
        ) : null}
      </div>
    </div>
  );
}

export default function PipelinePage() {
  const searchParams = useSearchParams();
  const qc = useQueryClient();
  const [clientId, setClientId] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [platform, setPlatform] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    const c = searchParams.get("client");
    const camp = searchParams.get("campaign");
    if (c) setClientId(c);
    if (camp) setCampaignId(camp);
  }, [searchParams]);

  const { data: clients } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list({ limit: 200 }).then((r) => r.data),
  });
  const clientOptions = normalizeList<Client>(clients);

  const { data: campaigns } = useQuery({
    queryKey: ["campaigns-pipeline", clientId],
    queryFn: () => campaignsApi.list({ client_id: clientId, limit: 200 }).then((r) => r.data),
    enabled: !!clientId,
  });
  const campaignOptions = normalizeList<Campaign>(campaigns);

  const { data: board, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["content-pipeline", clientId, campaignId, platform],
    queryFn: () =>
      contentPipelineApi
        .board({
          client_id: clientId || undefined,
          campaign_id: campaignId || undefined,
          platform: platform || undefined,
        })
        .then((r) => r.data),
    refetchInterval: 60000,
  });

  const transitionMutation = useMutation({
    mutationFn: ({
      id,
      stage,
      scheduled_for,
      reason,
    }: {
      id: string;
      stage: PipelineStage;
      scheduled_for?: string;
      reason?: string;
    }) => contentPipelineApi.transition(id, { stage, scheduled_for, reason }),
    onMutate: ({ id }) => setBusyId(id),
    onSettled: () => setBusyId(null),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["content-pipeline"] });
      toast.success(res.data.message || "Stage updated");
    },
    onError: (err: Error) => toast.error(err.message || "Transition failed"),
  });

  const retryMutation = useMutation({
    mutationFn: (id: string) => contentPipelineApi.retryPublish(id),
    onMutate: (id) => setBusyId(id),
    onSettled: () => setBusyId(null),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["content-pipeline"] });
      toast.success(res.data.message || "Retry completed");
    },
    onError: (err: Error) => toast.error(err.message || "Retry failed"),
  });

  const handleTransition = (
    card: PipelineBoardCard,
    stage: PipelineStage,
    extra?: { scheduled_for?: string; reason?: string },
  ) => {
    transitionMutation.mutate({ id: card.id, stage, ...extra });
  };

  let body: React.ReactNode = null;
  if (isLoading) {
    body = <LoadingState message="Loading pipeline…" className="py-16" />;
  } else if (isError) {
    body = (
      <ErrorState
        message={error instanceof Error ? error.message : "Failed to load pipeline"}
        onRetry={() => refetch()}
      />
    );
  } else if (board && board.total === 0) {
    body = <EmptyState title="Pipeline is empty" description="Create content or adjust filters." />;
  } else if (board) {
    body = (
      <div className="overflow-x-auto pb-4">
        <div className="flex gap-3 min-w-max">
          {PIPELINE_STAGES.map((stage) => {
            const cards = board.stages[stage] ?? [];
            return (
              <div key={stage} className="w-72 shrink-0">
                <div className="flex items-center justify-between mb-2 px-1">
                  <p className="text-xs font-semibold text-gray-800">
                    {PIPELINE_STAGE_LABELS[stage]}
                  </p>
                  <span className="text-[10px] text-gray-400 tabular-nums bg-gray-100 px-1.5 py-0.5 rounded-full">
                    {board.counts[stage] ?? cards.length}
                  </span>
                </div>
                <div className="space-y-2 min-h-[120px] rounded-lg bg-gray-50/80 p-2 border border-gray-100">
                  {cards.length === 0 ? (
                    <p className="text-[10px] text-gray-400 text-center py-6">Empty</p>
                  ) : (
                    cards.map((card) => (
                      <PipelineCard
                        key={card.id}
                        card={card}
                        busy={busyId === card.id}
                        onTransition={(s, extra) => handleTransition(card, s, extra)}
                        onRetry={() => retryMutation.mutate(card.id)}
                      />
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Columns3 size={22} className="text-teal-600" />
            Pipeline
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Content production & approval board — no auto-publish on move
          </p>
        </div>
        <button
          type="button"
          className="btn-secondary text-sm flex items-center gap-1.5"
          onClick={() => refetch()}
          disabled={isFetching}
        >
          {isFetching ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          Refresh
        </button>
      </div>

      <div className="flex flex-wrap gap-3">
        <select
          className="input text-sm min-w-[160px]"
          value={clientId}
          onChange={(e) => {
            setClientId(e.target.value);
            setCampaignId("");
          }}
        >
          <option value="">All clients</option>
          {clientOptions.map((c) => (
            <option key={c.id} value={c.id}>
              {c.company_name}
            </option>
          ))}
        </select>
        <select
          className="input text-sm min-w-[160px]"
          value={campaignId}
          onChange={(e) => setCampaignId(e.target.value)}
          disabled={!clientId}
        >
          <option value="">All campaigns</option>
          {campaignOptions.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <select
          className="input text-sm min-w-[130px]"
          value={platform}
          onChange={(e) => setPlatform(e.target.value)}
        >
          <option value="">All platforms</option>
          {PLATFORMS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        {board ? (
          <span className="text-sm text-gray-500 self-center tabular-nums">{board.total} items</span>
        ) : null}
      </div>

      {body}
    </div>
  );
}
