"use client";

import { useMutation } from "@tanstack/react-query";
import { ContentItem, contentApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { format, parseISO } from "date-fns";
import { Send } from "lucide-react";
import toast from "react-hot-toast";

const STATUS_STYLES: Record<string, { label: string; className: string }> = {
  pending: {
    label: "Client review pending",
    className: "bg-amber-100 text-amber-800 border-amber-200",
  },
  approved: {
    label: "Client approved",
    className: "bg-teal-100 text-teal-800 border-teal-200",
  },
  changes_requested: {
    label: "Changes requested",
    className: "bg-orange-100 text-orange-800 border-orange-200",
  },
};

interface Props {
  item: Pick<
    ContentItem,
    | "client_review_status"
    | "client_review_feedback"
    | "client_approved_at"
    | "client_review_preview_sent_at"
    | "client_review_preview_error"
    | "status"
    | "approved_at"
  >;
  contentId?: string;
  onPreviewSent?: () => void;
  compact?: boolean;
}

export function ClientReviewStatusBadge({ item, compact }: Pick<Props, "item" | "compact">) {
  const status = item.client_review_status;
  if (!status) return null;
  const cfg = STATUS_STYLES[status] ?? {
    label: status,
    className: "bg-gray-100 text-gray-700 border-gray-200",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border font-medium",
        compact ? "text-[10px] px-1.5 py-0.5" : "text-xs px-2 py-0.5",
        cfg.className,
      )}
    >
      {cfg.label}
    </span>
  );
}

export function ClientReviewStatusPanel({ item, contentId, onPreviewSent }: Props) {
  const canSendPreview =
    !!contentId
    && (item.approved_at || item.status === "scheduled" || item.status === "approved")
    && item.client_review_status !== "approved";

  const previewMutation = useMutation({
    mutationFn: () => contentApi.sendClientReviewPreview(contentId!),
    onSuccess: (res) => {
      if (res.data.sent) {
        toast.success("Client review preview sent to Telegram group");
      } else if (res.data.skipped) {
        toast(res.data.reason || "Preview not sent", { icon: "ℹ️" });
      } else {
        toast.error(res.data.error || "Failed to send preview");
      }
      onPreviewSent?.();
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      const detail = err.response?.data?.detail;
      toast.error(
        typeof detail === "string" ? detail : "Failed to send client review preview",
      );
    },
  });

  if (
    !item.client_review_status
    && !item.client_approved_at
    && !item.client_review_feedback
    && !item.client_review_preview_error
  ) {
    return null;
  }

  return (
    <div className="card p-4 space-y-2">
      <h3 className="text-sm font-semibold text-gray-900">Client review</h3>
      <div className="flex flex-wrap items-center gap-2">
        <ClientReviewStatusBadge item={item} />
        {item.client_approved_at && (
          <span className="text-[11px] text-teal-700">
            Approved {format(parseISO(item.client_approved_at), "MMM d, yyyy HH:mm")}
          </span>
        )}
        {item.client_review_preview_sent_at && (
          <span className="text-[11px] text-gray-500">
            Preview sent {format(parseISO(item.client_review_preview_sent_at), "MMM d, HH:mm")}
          </span>
        )}
      </div>

      {item.client_review_preview_error && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
          <p className="text-[10px] font-medium text-amber-900 uppercase tracking-wide">
            Telegram preview not delivered
          </p>
          <p className="text-xs text-amber-800 mt-0.5">{item.client_review_preview_error}</p>
          <p className="text-[11px] text-amber-700 mt-1">
            Check that the bot is in the client intake group and telegram_group_id is correct.
          </p>
        </div>
      )}

      {item.client_review_feedback && (
        <div className="rounded-lg border border-orange-100 bg-orange-50/60 px-3 py-2">
          <p className="text-[10px] font-medium text-orange-900 uppercase tracking-wide">
            Client feedback
          </p>
          <p className="text-xs text-orange-800 mt-0.5 whitespace-pre-wrap">
            {item.client_review_feedback}
          </p>
        </div>
      )}

      {item.client_review_status === "pending" && (
        <p className="text-[11px] text-gray-500">
          Waiting for client action via Telegram buttons (intake group) or web review link.
        </p>
      )}

      {canSendPreview && (
        <button
          type="button"
          className="btn-secondary text-xs w-full mt-1"
          disabled={previewMutation.isPending}
          onClick={() => previewMutation.mutate()}
        >
          <Send size={13} />
          {previewMutation.isPending ? "Sending…" : "Send client review preview"}
        </button>
      )}
    </div>
  );
}
