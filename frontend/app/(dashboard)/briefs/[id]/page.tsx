"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  ClipboardPen,
  ExternalLink,
  ListTodo,
  Loader2,
  MessageSquareWarning,
  Plus,
  Save,
  Sparkles,
  ThumbsUp,
  X,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  clientBriefApi,
  clientsApi,
  mediaApi,
  type ClientBrief,
  type ClientBriefContentPlan,
  type ClientBriefMediaType,
  type ClientBriefPlanItem,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { useDashboardAuthGates } from "@/lib/useDashboardAuthGates";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

const STATUS_STYLES: Record<string, string> = {
  new: "bg-amber-100 text-amber-800 border-amber-200",
  reviewing: "bg-sky-100 text-sky-800 border-sky-200",
  changes_requested: "bg-orange-100 text-orange-800 border-orange-200",
  approved: "bg-violet-100 text-violet-800 border-violet-200",
  converted: "bg-emerald-100 text-emerald-800 border-emerald-200",
};

const MEDIA_TYPES: ClientBriefMediaType[] = ["image", "carousel", "reel", "story", "short_video"];
const PLATFORMS = ["instagram", "facebook", "tiktok", "telegram", "linkedin"];

function statusLabel(status: string, t: (key: string) => string): string {
  const key = `clientBrief.status.${status}`;
  const translated = t(key);
  return translated === key ? status : translated;
}

function parsePlan(raw: string | null | undefined): ClientBriefContentPlan | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as ClientBriefContentPlan;
  } catch {
    return null;
  }
}

function PlanEditor({
  plan,
  onChange,
  onSave,
  saving,
}: {
  plan: ClientBriefContentPlan;
  onChange: (plan: ClientBriefContentPlan) => void;
  onSave: () => void;
  saving: boolean;
}) {
  const { t } = useTranslation();

  const updateItem = (index: number, patch: Partial<ClientBriefPlanItem>) => {
    const items = plan.items.map((item, i) => (i === index ? { ...item, ...patch } : item));
    onChange({ ...plan, items });
  };

  const updateCaption = (index: number, lang: keyof ClientBriefPlanItem["captions"], value: string) => {
    const item = plan.items[index];
    updateItem(index, { captions: { ...item.captions, [lang]: value } });
  };

  return (
    <div className="space-y-4">
      <div>
        <label className="text-xs text-gray-500">{t("clientBrief.planSummary")}</label>
        <textarea
          className="input mt-1 w-full min-h-[60px]"
          value={plan.summary}
          onChange={(e) => onChange({ ...plan, summary: e.target.value })}
        />
      </div>
      {plan.items.map((item, i) => (
        <div key={i} className="rounded-xl border border-gray-200 bg-white p-4 space-y-3">
          <p className="text-xs font-semibold text-gray-500">
            {t("clientBrief.postNumber", { n: i + 1 })}
          </p>
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500">{t("clientBrief.planTheme")}</label>
              <input
                className="input mt-1 w-full text-sm"
                value={item.theme}
                onChange={(e) => updateItem(i, { theme: e.target.value })}
              />
            </div>
            <div>
              <label className="text-xs text-gray-500">{t("clientBrief.planGoal")}</label>
              <input
                className="input mt-1 w-full text-sm"
                value={item.goal}
                onChange={(e) => updateItem(i, { goal: e.target.value })}
              />
            </div>
            <div>
              <label className="text-xs text-gray-500">{t("clientBrief.planPlatform")}</label>
              <select
                className="input mt-1 w-full text-sm capitalize"
                value={item.platform}
                onChange={(e) => updateItem(i, { platform: e.target.value })}
              >
                {PLATFORMS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-500">{t("clientBrief.planMediaType")}</label>
              <select
                className="input mt-1 w-full text-sm"
                value={item.media_type}
                onChange={(e) => updateItem(i, { media_type: e.target.value as ClientBriefMediaType })}
              >
                {MEDIA_TYPES.map((m) => (
                  <option key={m} value={m}>
                    {t(`clientBrief.mediaType.${m}`)}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            {(["ru", "uz", "en", "zh"] as const).map((lang) => (
              <div key={lang}>
                <label className="text-xs text-gray-500 uppercase">{lang}</label>
                <textarea
                  className="input mt-1 w-full min-h-[56px] text-xs"
                  value={item.captions[lang]}
                  onChange={(e) => updateCaption(i, lang, e.target.value)}
                />
              </div>
            ))}
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500">{t("clientBrief.planHashtags")}</label>
              <input
                className="input mt-1 w-full text-sm"
                value={item.hashtags}
                onChange={(e) => updateItem(i, { hashtags: e.target.value })}
              />
            </div>
            <div>
              <label className="text-xs text-gray-500">{t("clientBrief.planCta")}</label>
              <input
                className="input mt-1 w-full text-sm"
                value={item.cta}
                onChange={(e) => updateItem(i, { cta: e.target.value })}
              />
            </div>
          </div>
        </div>
      ))}
      <button type="button" className="btn-secondary text-xs" disabled={saving} onClick={onSave}>
        {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
        {t("clientBrief.savePlan")}
      </button>
    </div>
  );
}

function PlanPreview({ plan, t }: { plan: ClientBriefContentPlan; t: (key: string) => string }) {
  return (
    <div className="rounded-xl border border-gray-100 bg-slate-50/80 p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-gray-700">{t("clientBrief.aiPlan")}</p>
        <span className="text-[10px] px-2 py-0.5 rounded-full border bg-white text-gray-600">
          {t(`clientBrief.planStatus.${plan.plan_status}`)}
        </span>
      </div>
      {plan.summary && <p className="text-sm text-gray-800">{plan.summary}</p>}
      <ul className="space-y-3">
        {plan.items.map((item, i) => (
          <li key={i} className="text-xs text-gray-700 border-l-2 border-brand-200 pl-3 space-y-1">
            <p className="font-medium">{item.theme}</p>
            <p className="text-gray-500">{item.goal}</p>
            <p className="text-gray-400 capitalize">
              {item.platform} · {t(`clientBrief.mediaType.${item.media_type}`)}
            </p>
            {item.captions.en && (
              <p className="text-gray-600 line-clamp-2">{item.captions.en}</p>
            )}
            {item.hashtags && <p className="text-brand-600">{item.hashtags}</p>}
            {item.cta && <p className="text-gray-500 italic">{item.cta}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function BriefDetailPage() {
  const { t } = useTranslation();
  const params = useParams();
  const qc = useQueryClient();
  const briefId = params.id as string;
  const { adminWidgetsEnabled, tenantWidgetsEnabled, authReady } = useDashboardAuthGates();
  const isAdmin = adminWidgetsEnabled;

  const [feedback, setFeedback] = useState("");
  const [showRejectForm, setShowRejectForm] = useState(false);
  const [editingPlan, setEditingPlan] = useState(false);
  const [draftPlan, setDraftPlan] = useState<ClientBriefContentPlan | null>(null);
  const [uploading, setUploading] = useState(false);

  const { data: brief, isLoading, isError, refetch } = useQuery({
    queryKey: ["client-brief", briefId, isAdmin ? "admin" : "tenant"],
    queryFn: () =>
      (isAdmin ? clientBriefApi.getAdmin(briefId) : clientBriefApi.get(briefId)).then((r) => r.data),
    enabled: authReady && !!briefId && (isAdmin || tenantWidgetsEnabled),
  });

  const plan = useMemo(() => parsePlan(brief?.ai_content_plan), [brief?.ai_content_plan]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["client-brief", briefId] });
    qc.invalidateQueries({ queryKey: ["client-briefs"] });
  };

  const approveBriefMutation = useMutation({
    mutationFn: () => clientBriefApi.approveBrief(briefId).then((r) => r.data),
    onSuccess: () => {
      toast.success(t("clientBrief.briefApproved"));
      invalidate();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const requestChangesMutation = useMutation({
    mutationFn: (text: string) => clientBriefApi.requestChanges(briefId, text).then((r) => r.data),
    onSuccess: () => {
      toast.success(t("clientBrief.changesRequested"));
      setShowRejectForm(false);
      setFeedback("");
      invalidate();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const generateMutation = useMutation({
    mutationFn: () => clientBriefApi.generatePlan(briefId).then((r) => r.data),
    onSuccess: () => {
      toast.success(t("clientBrief.planGenerated"));
      setEditingPlan(false);
      invalidate();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const savePlanMutation = useMutation({
    mutationFn: (p: ClientBriefContentPlan) => clientBriefApi.updatePlan(briefId, p).then((r) => r.data),
    onSuccess: () => {
      toast.success(t("clientBrief.planSaved"));
      setEditingPlan(false);
      invalidate();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const approvePlanMutation = useMutation({
    mutationFn: () => clientBriefApi.approvePlan(briefId).then((r) => r.data),
    onSuccess: () => {
      toast.success(t("clientBrief.planApproved"));
      invalidate();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const convertMutation = useMutation({
    mutationFn: () => clientBriefApi.convertToTasks(briefId).then((r) => r.data),
    onSuccess: (res) => {
      toast.success(
        t("clientBrief.tasksCreated", {
          tasks: res.tasks_created,
          content: res.content_items_created,
        }),
      );
      invalidate();
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const handleTenantUpload = async (files: FileList | null) => {
    if (!files?.length || !brief) return;
    setUploading(true);
    try {
      const uploaded: string[] = [];
      for (const file of Array.from(files)) {
        const res = await mediaApi.upload(brief.client_id, file);
        if (res.data.url) uploaded.push(res.data.url);
      }
      await clientBriefApi.addMedia(briefId, uploaded);
      toast.success(t("clientBrief.mediaAdded"));
      invalidate();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("errors.generic"));
    } finally {
      setUploading(false);
    }
  };

  if (!authReady) return <LoadingState message={t("common.loading")} />;
  if (isLoading) return <LoadingState message={t("common.loading")} />;
  if (isError || !brief) return <ErrorState onRetry={() => refetch()} />;

  const canGeneratePlan = isAdmin && ["reviewing", "approved"].includes(brief.status);
  const canApprovePlan = isAdmin && !!plan && plan.plan_status === "draft" && brief.status !== "converted";
  const canConvert = isAdmin && brief.status === "approved" && plan?.plan_status === "approved";
  const canUpload = !isAdmin && brief.status === "changes_requested";

  return (
    <div className="p-4 sm:p-6 space-y-6 max-w-4xl mx-auto">
      <div className="flex items-center gap-3">
        <Link href="/briefs" className="btn-ghost p-2">
          <ArrowLeft size={18} />
        </Link>
        <div className="flex-1 min-w-0">
          <h1 className="text-xl font-semibold text-navy-900 truncate">{brief.product_name}</h1>
          <p className="text-sm text-gray-500 truncate">
            {brief.target_market}
            {brief.tenant_name || brief.company_name ? ` · ${brief.tenant_name ?? brief.company_name}` : ""}
          </p>
        </div>
        <span
          className={cn(
            "text-[10px] px-2 py-0.5 rounded-full border font-medium shrink-0",
            STATUS_STYLES[brief.status] ?? STATUS_STYLES.new,
          )}
        >
          {statusLabel(brief.status, t)}
        </span>
      </div>

      {brief.admin_feedback && (
        <div className="rounded-xl border border-orange-200 bg-orange-50 p-4 flex gap-3">
          <MessageSquareWarning size={18} className="text-orange-600 shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-semibold text-orange-800">{t("clientBrief.adminFeedback")}</p>
            <p className="text-sm text-orange-900 mt-1">{brief.admin_feedback}</p>
          </div>
        </div>
      )}

      <div className="card-premium p-6 space-y-4">
        {brief.product_description && (
          <div>
            <p className="text-xs text-gray-400">{t("clientBrief.productDescription")}</p>
            <p className="text-sm text-gray-800">{brief.product_description}</p>
          </div>
        )}
        <div className="grid sm:grid-cols-2 gap-3 text-sm">
          <div>
            <p className="text-xs text-gray-400">{t("clientBrief.campaignGoal")}</p>
            <p className="text-gray-800 capitalize">{brief.campaign_goal.replace("_", " ")}</p>
          </div>
          <div>
            <p className="text-xs text-gray-400">{t("clientBrief.languages")}</p>
            <p className="text-gray-800 uppercase">
              {(brief.languages?.length ? brief.languages : [brief.language]).join(", ")}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-400">{t("clientBrief.platforms")}</p>
            <p className="text-gray-800 capitalize">{brief.desired_platforms.join(", ") || "—"}</p>
          </div>
          <div>
            <p className="text-xs text-gray-400">{t("clientBrief.created")}</p>
            <p className="text-gray-800">{new Date(brief.created_at).toLocaleString()}</p>
          </div>
        </div>
        {brief.notes && (
          <div>
            <p className="text-xs text-gray-400">{t("clientBrief.notes")}</p>
            <p className="text-sm text-gray-800">{brief.notes}</p>
          </div>
        )}
        {brief.media_urls.length > 0 && (
          <div>
            <p className="text-xs text-gray-400 mb-1">{t("clientBrief.media")}</p>
            <ul className="space-y-1">
              {brief.media_urls.map((url) => (
                <li key={url}>
                  <a
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-brand-600 hover:underline inline-flex items-center gap-1"
                  >
                    {url.split("/").pop()}
                    <ExternalLink size={10} />
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {canUpload && (
        <div className="card-premium p-6 space-y-3">
          <p className="text-sm font-medium text-navy-900">{t("clientBrief.uploadAdditional")}</p>
          <p className="text-xs text-gray-500">{t("clientBrief.uploadAdditionalHint")}</p>
          <label className="btn-secondary text-xs cursor-pointer inline-flex items-center gap-2">
            {uploading ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            {t("clientBrief.uploadMedia")}
            <input
              type="file"
              className="hidden"
              accept="image/*,video/*"
              multiple
              disabled={uploading}
              onChange={(e) => handleTenantUpload(e.target.files)}
            />
          </label>
        </div>
      )}

      {isAdmin && brief.status !== "converted" && (
        <div className="card-premium p-4 flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-secondary text-xs"
            disabled={approveBriefMutation.isPending || !["new", "changes_requested"].includes(brief.status)}
            onClick={() => approveBriefMutation.mutate()}
          >
            {approveBriefMutation.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <CheckCircle2 size={14} />
            )}
            {t("clientBrief.approveBrief")}
          </button>
          <button
            type="button"
            className="btn-secondary text-xs"
            disabled={generateMutation.isPending || !canGeneratePlan}
            onClick={() => generateMutation.mutate()}
          >
            {generateMutation.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Sparkles size={14} />
            )}
            {t("clientBrief.generatePlan")}
          </button>
          {plan && (
            <button
              type="button"
              className="btn-secondary text-xs"
              onClick={() => {
                setDraftPlan(plan);
                setEditingPlan((v) => !v);
              }}
            >
              <ClipboardPen size={14} />
              {editingPlan ? t("clientBrief.cancelEdit") : t("clientBrief.editPlan")}
            </button>
          )}
          <button
            type="button"
            className="btn-secondary text-xs"
            disabled={approvePlanMutation.isPending || !canApprovePlan}
            onClick={() => approvePlanMutation.mutate()}
          >
            {approvePlanMutation.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <ThumbsUp size={14} />
            )}
            {t("clientBrief.approvePlan")}
          </button>
          <button
            type="button"
            className="btn-primary text-xs"
            disabled={convertMutation.isPending || !canConvert}
            onClick={() => convertMutation.mutate()}
          >
            {convertMutation.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <ListTodo size={14} />
            )}
            {t("clientBrief.convertTasks")}
          </button>
          {!showRejectForm ? (
            <button
              type="button"
              className="btn-secondary text-xs text-orange-700 border-orange-200"
              onClick={() => setShowRejectForm(true)}
            >
              <MessageSquareWarning size={14} />
              {t("clientBrief.requestChanges")}
            </button>
          ) : (
            <div className="w-full flex flex-col sm:flex-row gap-2 mt-2">
              <textarea
                className="input flex-1 min-h-[60px] text-sm"
                placeholder={t("clientBrief.feedbackPlaceholder")}
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
              />
              <div className="flex gap-2">
                <button
                  type="button"
                  className="btn-primary text-xs"
                  disabled={!feedback.trim() || requestChangesMutation.isPending}
                  onClick={() => requestChangesMutation.mutate(feedback.trim())}
                >
                  {requestChangesMutation.isPending ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    t("clientBrief.sendFeedback")
                  )}
                </button>
                <button type="button" className="btn-ghost text-xs" onClick={() => setShowRejectForm(false)}>
                  <X size={14} />
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {brief.status === "converted" && isAdmin && (
        <div className="flex gap-2">
          <Link href="/content" className="btn-secondary text-xs">
            <ExternalLink size={14} />
            {t("clientBrief.viewContent")}
          </Link>
          <Link href="/tasks" className="btn-secondary text-xs">
            <ListTodo size={14} />
            {t("clientBrief.viewTasks")}
          </Link>
        </div>
      )}

      {plan && (
        editingPlan && draftPlan ? (
          <div className="card-premium p-6">
            <PlanEditor
              plan={draftPlan}
              onChange={setDraftPlan}
              onSave={() => savePlanMutation.mutate(draftPlan)}
              saving={savePlanMutation.isPending}
            />
          </div>
        ) : (
          <PlanPreview plan={plan} t={t} />
        )
      )}
    </div>
  );
}
