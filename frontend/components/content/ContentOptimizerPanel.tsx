"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Check,
  ChevronDown,
  ChevronRight,
  History,
  Layers,
  Loader2,
  Minus,
  Sparkle,
  X,
} from "lucide-react";

import {
  CONTENT_OPTIMIZER_QUERY_KEY,
  contentOptimizerApi,
  getApiErrorMessage,
  getApiErrorStatus,
  type ContentOptimizerVariant,
  type TransformationRecord,
} from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  contentId: string;
  /** Called after a variant is applied so the parent can refresh content captions. */
  onApplied?: () => void;
}

const PLATFORM_OPTIONS = ["telegram", "facebook", "instagram", "tiktok", "linkedin"] as const;
const LOCALE_OPTIONS = ["en", "ru", "uz"] as const;
const LENGTH_OPTIONS = ["short", "standard", "extended"] as const;

const DEFAULT_PLATFORMS = ["telegram", "instagram"];
const DEFAULT_LOCALES = ["en"];
const DEFAULT_LENGTHS = ["standard"];

// Deterministic transformation reason_key -> operator-friendly wording.
// Intentionally structural language only (no AI / rewrite framing).
const REASON_LABELS: Record<string, string> = {
  whitespace_normalized: "Whitespace normalized",
  line_breaks_normalized: "Line breaks normalized",
  blank_lines_removed: "Extra blank lines removed",
  edge_punctuation_trimmed: "Edge punctuation trimmed",
  bullets_normalized: "Bullet formatting normalized",
  platform_line_breaks_applied: "Platform line breaks applied",
  short_lines_joined: "Short lines joined",
  long_paragraphs_split: "Long paragraphs split",
  duplicate_sentences_removed: "Duplicate sentences removed",
  duplicate_hashtags_removed: "Duplicate hashtags removed",
  empty_sections_removed: "Empty sections removed",
  repeated_link_removed: "Repeated link removed",
  hashtags_moved_to_end: "Hashtags moved to end",
  hashtag_count_limited: "Hashtag count aligned with internal policy",
  unsupported_hashtags_removed: "Unsupported hashtags removed",
  first_paragraph_preserved: "Lead paragraph preserved",
  last_cta_preserved: "Existing CTA preserved",
  first_sentences_selected: "Caption length reduced",
  first_paragraphs_selected: "Caption length reduced",
  truncated_at_sentence: "Caption length reduced",
  truncated_at_paragraph: "Caption length reduced",
  existing_cta_selected: "Existing CTA selected",
};

function reasonLabel(t: TransformationRecord): string {
  return REASON_LABELS[t.reason_key] ?? t.reason_key.replace(/_/g, " ");
}

function variantKey(v: ContentOptimizerVariant): string {
  return (v.variant_id ?? v.id ?? `${v.platform}-${v.locale}-${v.length_profile}`) as string;
}

function scoreTone(score: number | null | undefined): string {
  if (score == null) return "text-slate-400";
  if (score >= 75) return "text-emerald-700";
  if (score >= 55) return "text-amber-700";
  return "text-rose-700";
}

function readinessLabel(value?: string | null): string {
  if (value === "ready") return "Hard checks: ready";
  if (value === "blocked") return "Hard checks: blocked";
  if (value === "warnings") return "Hard checks: warnings";
  return value ? value : "Not evaluated";
}

function readinessTone(value?: string | null): string {
  if (value === "blocked") return "bg-rose-100 text-rose-800";
  if (value === "ready") return "bg-emerald-100 text-emerald-800";
  if (value === "warnings") return "bg-amber-100 text-amber-800";
  return "bg-slate-100 text-slate-600";
}

function CheckGroup({
  label,
  values,
  selected,
  onToggle,
}: {
  label: string;
  values: readonly string[];
  selected: string[];
  onToggle: (v: string) => void;
}) {
  return (
    <div>
      <p className="text-[11px] font-medium text-gray-600 mb-1.5">{label}</p>
      <div className="flex flex-wrap gap-1.5">
        {values.map((v) => {
          const active = selected.includes(v);
          return (
            <button
              key={v}
              type="button"
              onClick={() => onToggle(v)}
              className={cn(
                "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium capitalize transition-colors",
                active
                  ? "border-brand-500 bg-brand-50 text-brand-700"
                  : "border-slate-200 bg-white text-slate-600 hover:border-slate-300",
              )}
            >
              {active ? <Check size={11} /> : null}
              {v}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function ContentOptimizerPanel({ contentId, onApplied }: Props) {
  const qc = useQueryClient();

  const [platforms, setPlatforms] = useState<string[]>(DEFAULT_PLATFORMS);
  const [locales, setLocales] = useState<string[]>(DEFAULT_LOCALES);
  const [lengthProfiles, setLengthProfiles] = useState<string[]>(DEFAULT_LENGTHS);
  const [includeCta, setIncludeCta] = useState(true);
  const [includeHashtags, setIncludeHashtags] = useState(true);

  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [activeVariantKey, setActiveVariantKey] = useState<string | null>(null);
  const [confirmApply, setConfirmApply] = useState<ContentOptimizerVariant | null>(null);

  const historyQuery = useQuery({
    queryKey: [...CONTENT_OPTIMIZER_QUERY_KEY, "runs", contentId],
    queryFn: () => contentOptimizerApi.listRuns(contentId, { page_size: 8 }).then((r) => r.data),
    staleTime: 15_000,
    refetchOnWindowFocus: false,
  });

  const runs = historyQuery.data?.items ?? [];
  const selectedRunId = activeRunId ?? (runs.length > 0 ? (runs[0].run_id ?? runs[0].id ?? null) : null);

  const runDetailQuery = useQuery({
    queryKey: [...CONTENT_OPTIMIZER_QUERY_KEY, "run", selectedRunId],
    queryFn: () => contentOptimizerApi.getRun(selectedRunId as string).then((r) => r.data),
    enabled: !!selectedRunId,
    staleTime: 15_000,
    refetchOnWindowFocus: false,
  });

  const optimize = useMutation({
    mutationFn: () =>
      contentOptimizerApi
        .optimize(contentId, {
          platforms,
          locales,
          length_profiles: lengthProfiles,
          include_existing_cta: includeCta,
          include_existing_hashtags: includeHashtags,
        })
        .then((r) => r.data),
    onSuccess: (data) => {
      const rid = (data.run.run_id ?? data.run.id) as string | undefined;
      if (rid) {
        setActiveRunId(rid);
        qc.setQueryData([...CONTENT_OPTIMIZER_QUERY_KEY, "run", rid], data);
      }
      setActiveVariantKey(null);
      void qc.invalidateQueries({ queryKey: [...CONTENT_OPTIMIZER_QUERY_KEY, "runs", contentId] });
    },
  });

  const acceptMut = useMutation({
    mutationFn: (variantId: string) => contentOptimizerApi.acceptVariant(variantId).then((r) => r.data),
    onSuccess: () => refreshRun(),
  });

  const rejectMut = useMutation({
    mutationFn: (variantId: string) => contentOptimizerApi.rejectVariant(variantId).then((r) => r.data),
    onSuccess: () => refreshRun(),
  });

  const applyMut = useMutation({
    mutationFn: (variant: ContentOptimizerVariant) =>
      contentOptimizerApi
        .applyVariant((variant.variant_id ?? variant.id) as string, {
          expected_source_fingerprint: variant.source_fingerprint,
        })
        .then((r) => r.data),
    onSuccess: () => {
      setConfirmApply(null);
      refreshRun();
      void qc.invalidateQueries({ queryKey: ["content", contentId] });
      void qc.invalidateQueries({ queryKey: ["publishing-intelligence"] });
      void qc.invalidateQueries({ queryKey: CONTENT_OPTIMIZER_QUERY_KEY });
      onApplied?.();
    },
  });

  function refreshRun() {
    if (selectedRunId) {
      void qc.invalidateQueries({ queryKey: [...CONTENT_OPTIMIZER_QUERY_KEY, "run", selectedRunId] });
    }
    void qc.invalidateQueries({ queryKey: [...CONTENT_OPTIMIZER_QUERY_KEY, "runs", contentId] });
  }

  const detail = runDetailQuery.data;
  const run = detail?.run;
  const variants = useMemo<ContentOptimizerVariant[]>(
    () => detail?.variants ?? detail?.run.variants ?? [],
    [detail],
  );

  const activeVariant = useMemo(() => {
    if (variants.length === 0) return null;
    if (activeVariantKey) {
      const found = variants.find((v) => variantKey(v) === activeVariantKey);
      if (found) return found;
    }
    return variants[0];
  }, [variants, activeVariantKey]);

  const applyConflict =
    applyMut.isError && getApiErrorStatus(applyMut.error) === 409;

  return (
    <div className="card p-4 space-y-4">
      <div className="flex items-start gap-2">
        <Layers size={15} className="text-brand-600 shrink-0 mt-0.5" />
        <div>
          <h3 className="text-sm font-semibold text-gray-900">Platform content adaptation</h3>
          <p className="text-[11px] text-gray-500 mt-0.5">
            Deterministic structural adaptation of your existing caption per platform — no AI
            rewrite. Produces policy-aligned variants (length, hashtags, CTA placement) you can
            review and apply.
          </p>
        </div>
      </div>

      {/* Selection controls */}
      <div className="space-y-3 rounded-lg border border-slate-100 bg-slate-50/60 p-3">
        <CheckGroup
          label="Platforms"
          values={PLATFORM_OPTIONS}
          selected={platforms}
          onToggle={(v) =>
            setPlatforms((prev) => (prev.includes(v) ? prev.filter((p) => p !== v) : [...prev, v]))
          }
        />
        <CheckGroup
          label="Locales"
          values={LOCALE_OPTIONS}
          selected={locales}
          onToggle={(v) =>
            setLocales((prev) => (prev.includes(v) ? prev.filter((p) => p !== v) : [...prev, v]))
          }
        />
        <CheckGroup
          label="Length profiles"
          values={LENGTH_OPTIONS}
          selected={lengthProfiles}
          onToggle={(v) =>
            setLengthProfiles((prev) =>
              prev.includes(v) ? prev.filter((p) => p !== v) : [...prev, v],
            )
          }
        />
        <div className="flex flex-wrap gap-x-4 gap-y-1.5 pt-1">
          <label className="inline-flex items-center gap-1.5 text-[11px] text-gray-600">
            <input
              type="checkbox"
              checked={includeCta}
              onChange={(e) => setIncludeCta(e.target.checked)}
              className="rounded border-slate-300"
            />
            Keep existing CTA
          </label>
          <label className="inline-flex items-center gap-1.5 text-[11px] text-gray-600">
            <input
              type="checkbox"
              checked={includeHashtags}
              onChange={(e) => setIncludeHashtags(e.target.checked)}
              className="rounded border-slate-300"
            />
            Keep existing hashtags
          </label>
        </div>

        <button
          type="button"
          onClick={() => optimize.mutate()}
          disabled={
            optimize.isPending ||
            platforms.length === 0 ||
            locales.length === 0 ||
            lengthProfiles.length === 0
          }
          className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60"
        >
          {optimize.isPending ? (
            <Loader2 size={13} className="animate-spin" />
          ) : (
            <Sparkle size={13} />
          )}
          Generate variants
        </button>
        {platforms.length === 0 || locales.length === 0 || lengthProfiles.length === 0 ? (
          <p className="text-[11px] text-amber-600">
            Select at least one platform, locale, and length profile.
          </p>
        ) : null}
      </div>

      {optimize.isError ? (
        <p className="text-xs text-rose-600">{getApiErrorMessage(optimize.error)}</p>
      ) : null}

      {/* Partial success notice */}
      {run && (run.failed_count ?? 0) > 0 ? (
        <div className="flex items-start gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2 text-[11px] text-amber-800">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          <span>
            Partial success — {run.generated_count ?? variants.length} variant(s) generated,{" "}
            {run.failed_count} could not be adapted
            {run.failure_code ? ` (${run.failure_code})` : ""}.
          </span>
        </div>
      ) : null}

      {/* Loading */}
      {optimize.isPending || runDetailQuery.isLoading ? (
        <div className="animate-pulse space-y-2">
          <div className="h-6 bg-gray-100 rounded w-32" />
          <div className="h-24 bg-gray-100 rounded w-full" />
        </div>
      ) : null}

      {/* Empty */}
      {!optimize.isPending && !runDetailQuery.isLoading && !selectedRunId ? (
        <p className="text-xs text-gray-500">
          No adaptations yet. Choose targets above and generate structural, policy-aligned variants
          from the current caption.
        </p>
      ) : null}

      {/* Failed run with no usable variants */}
      {run && run.status === "failed" && variants.length === 0 ? (
        <div className="flex items-start gap-1.5 rounded-md border border-rose-200 bg-rose-50 px-2.5 py-2 text-[11px] text-rose-700">
          <AlertCircle size={12} className="mt-0.5 shrink-0" />
          <span>
            Adaptation failed{run.failure_code ? ` (${run.failure_code})` : ""}. Try adjusting the
            selected targets and generate again.
          </span>
        </div>
      ) : null}

      {/* Variant tabs + detail */}
      {variants.length > 0 ? (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-1.5">
            {variants.map((v) => {
              const key = variantKey(v);
              const isActive = activeVariant && variantKey(activeVariant) === key;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => setActiveVariantKey(key)}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium capitalize",
                    isActive
                      ? "border-brand-500 bg-brand-50 text-brand-700"
                      : "border-slate-200 bg-white text-slate-600 hover:border-slate-300",
                  )}
                >
                  {v.platform}
                  <span className="text-slate-400">· {v.locale}</span>
                  <span className="text-slate-400">· {v.length_profile}</span>
                  {v.status === "stale" ? (
                    <span className="ml-0.5 rounded-full bg-amber-100 px-1 py-0.5 text-[9px] text-amber-800">
                      stale
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>

          {activeVariant ? (
            <VariantDetail
              variant={activeVariant}
              onAccept={() => acceptMut.mutate((activeVariant.variant_id ?? activeVariant.id) as string)}
              onReject={() => rejectMut.mutate((activeVariant.variant_id ?? activeVariant.id) as string)}
              onApply={() => setConfirmApply(activeVariant)}
              accepting={acceptMut.isPending}
              rejecting={rejectMut.isPending}
              applying={applyMut.isPending}
              actionError={
                acceptMut.isError
                  ? getApiErrorMessage(acceptMut.error)
                  : rejectMut.isError
                    ? getApiErrorMessage(rejectMut.error)
                    : applyConflict
                      ? "Source content changed since this variant was generated. Regenerate variants before applying."
                      : applyMut.isError
                        ? getApiErrorMessage(applyMut.error)
                        : null
              }
            />
          ) : null}
        </div>
      ) : null}

      {/* History */}
      {runs.length > 0 ? (
        <div>
          <h4 className="text-xs font-semibold text-gray-800 mb-2 flex items-center gap-1">
            <History size={12} /> Optimization history
          </h4>
          <ul className="space-y-1">
            {runs.slice(0, 6).map((r) => {
              const rid = (r.run_id ?? r.id) as string;
              return (
                <li key={rid}>
                  <button
                    type="button"
                    onClick={() => {
                      setActiveRunId(rid);
                      setActiveVariantKey(null);
                    }}
                    className={cn(
                      "flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-[11px]",
                      rid === selectedRunId ? "bg-slate-100" : "hover:bg-slate-50",
                    )}
                  >
                    <span className="text-gray-600 truncate">
                      {r.requested_platforms.join(", ") || "—"}
                      {r.status === "partial" ? " · partial" : ""}
                      {r.status === "failed" ? " · failed" : ""}
                    </span>
                    <span className="text-slate-400 tabular-nums shrink-0">
                      {(r.generated_count ?? r.variants.length) || 0} variants
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      {confirmApply ? (
        <ApplyConfirmDialog
          variant={confirmApply}
          onCancel={() => setConfirmApply(null)}
          onConfirm={() => applyMut.mutate(confirmApply)}
          applying={applyMut.isPending}
        />
      ) : null}
    </div>
  );
}

function ScoreDelta({ delta }: { delta: number | null | undefined }) {
  if (delta == null || delta === 0) {
    return (
      <span className="inline-flex items-center gap-0.5 text-[11px] font-medium text-slate-500">
        <Minus size={11} /> 0
      </span>
    );
  }
  const positive = delta > 0;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-[11px] font-medium",
        positive ? "text-emerald-700" : "text-rose-700",
      )}
    >
      {positive ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
      {positive ? `+${delta}` : delta}
    </span>
  );
}

function VariantDetail({
  variant,
  onAccept,
  onReject,
  onApply,
  accepting,
  rejecting,
  applying,
  actionError,
}: {
  variant: ContentOptimizerVariant;
  onAccept: () => void;
  onReject: () => void;
  onApply: () => void;
  accepting: boolean;
  rejecting: boolean;
  applying: boolean;
  actionError: string | null;
}) {
  const [showTransforms, setShowTransforms] = useState(false);

  const captionLength = (variant.caption ?? "").length;
  const hashtagCount = variant.hashtags?.length ?? 0;
  const hasCta = !!variant.cta;
  const lowerScore =
    variant.score_delta != null && variant.score_delta < 0;
  const isStale = variant.status === "stale" || variant.is_stale;
  const isUnsupported = !!variant.unsupported_reason;
  const isApplied = variant.status === "applied" || !!variant.applied_at;
  const isAccepted = variant.status === "accepted" || !!variant.accepted_at;
  const isRejected = variant.status === "rejected" || !!variant.rejected_at;

  return (
    <div className="rounded-lg border border-slate-100 p-3 space-y-3">
      {/* Badges */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium capitalize text-slate-600">
          {variant.platform} · {variant.locale} · {variant.length_profile}
        </span>
        {isStale ? (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-800">
            Stale — source changed
          </span>
        ) : null}
        {isApplied ? (
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-800">
            Applied
          </span>
        ) : isAccepted ? (
          <span className="rounded-full bg-brand-100 px-2 py-0.5 text-[10px] font-medium text-brand-700">
            Accepted
          </span>
        ) : isRejected ? (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">
            Rejected
          </span>
        ) : null}
        {variant.publish_readiness ? (
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-[10px] font-medium",
              readinessTone(variant.publish_readiness),
            )}
          >
            {readinessLabel(variant.publish_readiness)}
          </span>
        ) : null}
      </div>

      {isUnsupported ? (
        <p className="flex items-start gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-2 text-[11px] text-slate-600">
          <AlertCircle size={12} className="mt-0.5 shrink-0" />
          This target could not be adapted: {variant.unsupported_reason}
        </p>
      ) : null}

      {/* Source vs variant metrics */}
      <div className="grid grid-cols-2 gap-3 text-[11px]">
        <div className="space-y-1">
          <p className="font-medium text-gray-700">Adapted variant</p>
          <div className="flex justify-between text-gray-600">
            <span>Caption length</span>
            <span className="tabular-nums">{captionLength}</span>
          </div>
          <div className="flex justify-between text-gray-600">
            <span>Hashtags</span>
            <span className="tabular-nums">{hashtagCount}</span>
          </div>
          <div className="flex justify-between text-gray-600">
            <span>CTA</span>
            <span>{hasCta ? "present" : "none"}</span>
          </div>
        </div>
        <div className="space-y-1">
          <p className="font-medium text-gray-700">Publishing Score</p>
          <div className="flex items-baseline gap-2">
            <span className={cn("text-2xl font-semibold tabular-nums", scoreTone(variant.variant_score))}>
              {variant.variant_score ?? "—"}
            </span>
            <ScoreDelta delta={variant.score_delta} />
          </div>
          {variant.source_score != null ? (
            <p className="text-[10px] text-gray-400">
              Source score {variant.source_score}
            </p>
          ) : null}
          {lowerScore ? (
            <p className="flex items-start gap-1 text-[10px] text-rose-600">
              <AlertTriangle size={10} className="mt-0.5 shrink-0" />
              Lower Publishing Score than source
            </p>
          ) : null}
        </div>
      </div>

      {/* Caption preview */}
      {variant.caption != null ? (
        <div>
          <p className="text-[11px] font-medium text-gray-700 mb-1">Adapted caption</p>
          <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-slate-50 p-2 text-[11px] text-gray-700 font-sans">
            {variant.caption || "(empty)"}
          </pre>
          {variant.hashtags?.length ? (
            <p className="mt-1 text-[11px] text-brand-600 break-words">
              {variant.hashtags.map((h) => (h.startsWith("#") ? h : `#${h}`)).join(" ")}
            </p>
          ) : null}
          {variant.cta ? (
            <p className="mt-1 text-[11px] text-gray-500">CTA: {variant.cta}</p>
          ) : null}
        </div>
      ) : null}

      {/* Transformations */}
      {variant.transformations?.length ? (
        <div>
          <button
            type="button"
            onClick={() => setShowTransforms((s) => !s)}
            className="flex items-center gap-1 text-[11px] font-medium text-gray-700"
          >
            {showTransforms ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            Structural adaptations ({variant.transformations.length})
          </button>
          {showTransforms ? (
            <ul className="mt-2 space-y-1.5">
              {[...variant.transformations]
                .sort((a, b) => a.sequence - b.sequence)
                .map((t) => (
                  <li
                    key={`${t.sequence}-${t.operation_key}`}
                    className="rounded-md border border-slate-100 bg-slate-50 px-2.5 py-1.5"
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] uppercase tracking-wide text-slate-400">
                        {t.category}
                      </span>
                      <span className="text-[11px] font-medium text-gray-800">
                        {reasonLabel(t)}
                      </span>
                    </div>
                    {t.result_summary ? (
                      <p className="text-[10px] text-gray-500 mt-0.5">{t.result_summary}</p>
                    ) : null}
                  </li>
                ))}
              {variant.score_delta != null && variant.score_delta !== 0 ? (
                <li className="rounded-md border border-slate-100 bg-slate-50 px-2.5 py-1.5">
                  <span className="text-[11px] font-medium text-gray-800">
                    Publishing Score changed by{" "}
                    {variant.score_delta > 0 ? `+${variant.score_delta}` : variant.score_delta}
                  </span>
                  {variant.score_delta > 0 ? (
                    <p className="text-[10px] text-gray-500 mt-0.5">Policy fit improved</p>
                  ) : null}
                </li>
              ) : null}
            </ul>
          ) : null}
        </div>
      ) : null}

      {actionError ? <p className="text-[11px] text-rose-600">{actionError}</p> : null}

      {/* Actions */}
      <div className="flex flex-wrap gap-2 pt-1">
        <button
          type="button"
          onClick={onAccept}
          disabled={accepting || isApplied || isAccepted || isUnsupported}
          className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[11px] font-medium text-gray-700 hover:border-slate-300 disabled:opacity-50"
        >
          {accepting ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
          Accept
        </button>
        <button
          type="button"
          onClick={onReject}
          disabled={rejecting || isRejected || isApplied || isUnsupported}
          className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[11px] font-medium text-gray-700 hover:border-slate-300 disabled:opacity-50"
        >
          {rejecting ? <Loader2 size={12} className="animate-spin" /> : <X size={12} />}
          Reject
        </button>
        <button
          type="button"
          onClick={onApply}
          disabled={applying || isApplied || isStale || isUnsupported}
          className="inline-flex items-center gap-1 rounded-md bg-slate-900 px-2.5 py-1.5 text-[11px] font-medium text-white disabled:opacity-50"
          title={isStale ? "Regenerate — source changed" : "Apply this variant to content captions"}
        >
          {applying ? <Loader2 size={12} className="animate-spin" /> : null}
          Apply to content
        </button>
      </div>
    </div>
  );
}

function ApplyConfirmDialog({
  variant,
  onCancel,
  onConfirm,
  applying,
}: {
  variant: ContentOptimizerVariant;
  onCancel: () => void;
  onConfirm: () => void;
  applying: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl">
        <h4 className="text-sm font-semibold text-gray-900">Apply platform-adapted variant?</h4>
        <p className="mt-2 text-xs text-gray-600">
          This applies the deterministic, policy-aligned variant for{" "}
          <span className="font-medium capitalize">
            {variant.platform} · {variant.locale} · {variant.length_profile}
          </span>{" "}
          and updates the content caption for that platform.
        </p>
        <p className="mt-2 text-xs text-gray-600">
          It does <span className="font-semibold">not</span> publish, schedule, or approve the
          content — you retain full control over those steps.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={applying}
            className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:border-slate-300 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={applying}
            className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60"
          >
            {applying ? <Loader2 size={12} className="animate-spin" /> : null}
            Apply to content
          </button>
        </div>
      </div>
    </div>
  );
}
