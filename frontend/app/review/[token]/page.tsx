"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useMutation } from "@tanstack/react-query";
import { publicReviewApi } from "@/lib/api";
import { MediaPreview } from "@/components/ui/MediaPreview";
import { CheckCheck, MessageSquare, Loader2, RefreshCw } from "lucide-react";
import { PLATFORM_CONFIG } from "@/lib/utils";
import { formatScheduledLocal, LOCAL_TIMEZONE_NOTE } from "@/lib/datetime";
import { format, parseISO } from "date-fns";
import toast from "react-hot-toast";

export default function ClientReviewPage() {
  const { token } = useParams<{ token: string }>();
  const [feedback, setFeedback] = useState("");
  const [showFeedbackForm, setShowFeedbackForm] = useState(false);
  const [submitted, setSubmitted] = useState<"approved" | "changes" | "regenerate" | null>(null);

  const { data: review, isLoading, error, refetch } = useQuery({
    queryKey: ["public-review", token],
    queryFn: () => publicReviewApi.get(token!).then((r) => r.data),
    enabled: !!token,
  });

  const approveMutation = useMutation({
    mutationFn: () => publicReviewApi.approve(token),
    onSuccess: (res) => {
      setSubmitted("approved");
      toast.success(res.data.message);
      refetch();
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || "Could not submit approval");
    },
  });

  const changesMutation = useMutation({
    mutationFn: () => publicReviewApi.requestChanges(token, feedback),
    onSuccess: (res) => {
      setSubmitted("changes");
      setShowFeedbackForm(false);
      toast.success(res.data.message);
      refetch();
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || "Could not send feedback");
    },
  });

  const regenerateMutation = useMutation({
    mutationFn: () => publicReviewApi.regenerate(token),
    onSuccess: (res) => {
      setSubmitted("regenerate");
      toast.success(res.data.message);
      refetch();
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || "Could not request regeneration");
    },
  });

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <Loader2 className="animate-spin text-brand-600" size={28} />
      </div>
    );
  }

  if (error || !review) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 p-6">
        <div className="card p-8 max-w-md text-center">
          <p className="text-gray-700 font-medium">Review link not found</p>
          <p className="text-sm text-gray-500 mt-2">This link may be invalid or expired.</p>
        </div>
      </div>
    );
  }

  const isVideo = review.media_file_type === "video";
  const previewUrl = review.media_url;
  const gallery = review.selected_media && review.selected_media.length > 0
    ? review.selected_media
    : previewUrl
      ? [{ ordinal: 1, media_file_id: "", media_type: review.media_file_type || "image", url: previewUrl, text: "" }]
      : [];

  const alreadyApproved =
    review.client_review_status === "approved"
    || !!review.client_approved_at
    || submitted === "approved";
  const responded =
    alreadyApproved
    || submitted === "changes"
    || submitted === "regenerate"
    || review.client_review_status === "changes_requested";

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4">
      <div className="max-w-lg mx-auto space-y-5">
        <header className="text-center">
          <p className="text-xs uppercase tracking-wide text-gray-400 font-medium">Content review</p>
          <h1 className="text-xl font-semibold text-gray-900 mt-1">{review.company_name}</h1>
        </header>

        {previewUrl && (
          <div className="card overflow-hidden">
            <MediaPreview
              url={previewUrl}
              fileType={isVideo ? "video" : "image"}
              controls={isVideo}
              alt="Preview"
              className="bg-black max-h-80"
              mediaClassName="w-full max-h-80"
            />
            {gallery.length > 1 && (
              <div className="flex gap-2 p-2 overflow-x-auto border-t border-gray-100">
                {gallery.map((m, i) => (
                  <div key={i} className="w-14 h-14 shrink-0 rounded overflow-hidden border border-gray-200">
                    <MediaPreview
                      url={m.url}
                      fileType={m.media_type === "video" ? "video" : "image"}
                      alt={`Media ${i + 1}`}
                      className="w-full h-full"
                      mediaClassName="w-full h-full object-cover"
                    />
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {review.final_video_url && (
          <div className="card p-4">
            <p className="text-xs font-medium text-gray-500 mb-2">Final video</p>
            <MediaPreview
              url={review.final_video_url}
              fileType="video"
              controls
              alt="Final video"
              className="bg-black rounded-lg overflow-hidden"
              mediaClassName="w-full max-h-64"
            />
          </div>
        )}

        <div className="card p-4 space-y-4">
          {review.captions.map((cap) => (
            <div key={cap.lang}>
              <p className="text-[10px] font-semibold text-gray-400 uppercase">{cap.lang}</p>
              {cap.short && <p className="text-sm font-medium text-gray-900 mt-1">{cap.short}</p>}
              {cap.long && <p className="text-sm text-gray-600 mt-1 whitespace-pre-wrap">{cap.long}</p>}
            </div>
          ))}

          {review.hashtags && (
            <div>
              <p className="text-[10px] font-semibold text-gray-400 uppercase">Hashtags</p>
              <p className="text-sm text-brand-700 mt-1">{review.hashtags}</p>
            </div>
          )}

          {review.platforms && review.platforms.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-gray-400 uppercase">Platforms</p>
              <div className="flex flex-wrap gap-1.5 mt-1">
                {review.platforms.map((p) => (
                  <span
                    key={p}
                    className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-gray-100 text-gray-700"
                  >
                    {PLATFORM_CONFIG[p as keyof typeof PLATFORM_CONFIG]?.label ?? p}
                  </span>
                ))}
              </div>
            </div>
          )}

          {review.scheduled_for && (
            <p className="text-sm text-purple-700 font-medium">
              📅 Scheduled: {formatScheduledLocal(review.scheduled_for)}
            </p>
          )}
          {review.scheduled_for && (
            <p className="text-[10px] text-gray-400">{LOCAL_TIMEZONE_NOTE}</p>
          )}
        </div>

        {alreadyApproved && (
          <div className="card p-4 bg-emerald-50 border-emerald-100 text-emerald-800 text-sm">
            ✅ You approved this content
            {review.client_approved_at && (
              <span className="block text-xs mt-1 text-emerald-700">
                {format(parseISO(review.client_approved_at), "PPp")}
              </span>
            )}
          </div>
        )}

        {review.client_review_feedback && review.status === "changes_requested" && !alreadyApproved && (
          <div className="card p-4 bg-orange-50 border-orange-100 text-orange-800 text-sm">
            ✏️ Your feedback was sent: “{review.client_review_feedback}”
          </div>
        )}

        {!responded && (review.can_approve || review.can_request_changes) && (
          <div className="card p-4 space-y-3">
            {!showFeedbackForm ? (
              <div className="flex flex-col gap-2">
                <div className="flex flex-col sm:flex-row gap-2">
                  <button
                    type="button"
                    className="btn-primary flex-1 justify-center"
                    onClick={() => approveMutation.mutate()}
                    disabled={approveMutation.isPending || !review.can_approve}
                  >
                    <CheckCheck size={16} />
                    {approveMutation.isPending ? "Submitting…" : "✅ Approve"}
                  </button>
                  <button
                    type="button"
                    className="btn-secondary flex-1 justify-center"
                    onClick={() => setShowFeedbackForm(true)}
                    disabled={!review.can_request_changes}
                  >
                    <MessageSquare size={16} />
                    ✏️ Request changes
                  </button>
                </div>
                {review.can_regenerate !== false && (
                  <button
                    type="button"
                    className="btn-secondary w-full justify-center text-red-700 border-red-100 hover:bg-red-50"
                    onClick={() => regenerateMutation.mutate()}
                    disabled={regenerateMutation.isPending}
                  >
                    <RefreshCw size={16} />
                    {regenerateMutation.isPending ? "Requesting…" : "❌ Regenerate"}
                  </button>
                )}
              </div>
            ) : (
              <div className="space-y-3">
                <label className="label">What should we change?</label>
                <textarea
                  className="input text-sm min-h-[100px]"
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  placeholder="Describe the changes you need…"
                />
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="btn-secondary flex-1"
                    onClick={() => setShowFeedbackForm(false)}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="btn-primary flex-1"
                    onClick={() => changesMutation.mutate()}
                    disabled={!feedback.trim() || changesMutation.isPending}
                  >
                    {changesMutation.isPending ? "Sending…" : "Send feedback"}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {submitted === "changes" && !alreadyApproved && (
          <div className="card p-4 bg-orange-50 border-orange-100 text-orange-800 text-sm text-center">
            Thank you — your feedback has been sent to the team.
          </div>
        )}

        {submitted === "regenerate" && (
          <div className="card p-4 bg-amber-50 border-amber-100 text-amber-900 text-sm text-center">
            Regeneration requested — the team will send an updated preview.
          </div>
        )}

        <p className="text-center text-[10px] text-gray-400">
          Secure client review · no login required
        </p>
      </div>
    </div>
  );
}
