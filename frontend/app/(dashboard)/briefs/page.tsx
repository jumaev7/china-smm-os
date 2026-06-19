"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ClipboardPen,
  Loader2,
  Plus,
  X,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  clientBriefApi,
  clientsApi,
  mediaApi,
  normalizeList,
  type ClientBriefCampaignGoal,
  type ClientBriefLanguage,
  type Platform,
} from "@/lib/api";
import { useTranslation } from "@/lib/I18nProvider";
import { useDashboardAuthGates } from "@/lib/useDashboardAuthGates";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/PageStates";

const PLATFORMS: Platform[] = ["instagram", "facebook", "tiktok", "telegram", "linkedin"];
const LANGUAGES: { value: ClientBriefLanguage; label: string }[] = [
  { value: "ru", label: "Русский" },
  { value: "uz", label: "O'zbek" },
  { value: "en", label: "English" },
  { value: "zh", label: "中文" },
];
const CAMPAIGN_GOALS: { value: ClientBriefCampaignGoal; labelKey: string }[] = [
  { value: "awareness", labelKey: "clientBrief.goalAwareness" },
  { value: "leads", labelKey: "clientBrief.goalLeads" },
  { value: "sales", labelKey: "clientBrief.goalSales" },
  { value: "brand_trust", labelKey: "clientBrief.goalBrandTrust" },
];

const STATUS_STYLES: Record<string, string> = {
  new: "bg-amber-100 text-amber-800 border-amber-200",
  reviewing: "bg-sky-100 text-sky-800 border-sky-200",
  changes_requested: "bg-orange-100 text-orange-800 border-orange-200",
  approved: "bg-violet-100 text-violet-800 border-violet-200",
  converted: "bg-emerald-100 text-emerald-800 border-emerald-200",
};

function statusLabel(status: string, t: (key: string) => string): string {
  const key = `clientBrief.status.${status}`;
  const translated = t(key);
  return translated === key ? status : translated;
}

function TenantBriefForm() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [clientId, setClientId] = useState("");
  const [productName, setProductName] = useState("");
  const [productDescription, setProductDescription] = useState("");
  const [targetMarket, setTargetMarket] = useState("");
  const [campaignGoal, setCampaignGoal] = useState<ClientBriefCampaignGoal>("awareness");
  const [languages, setLanguages] = useState<ClientBriefLanguage[]>(["en"]);
  const [platforms, setPlatforms] = useState<string[]>(["instagram"]);
  const [notes, setNotes] = useState("");
  const [mediaUrls, setMediaUrls] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);

  const { data: clients, isLoading: clientsLoading } = useQuery({
    queryKey: ["clients"],
    queryFn: () => clientsApi.list().then((r) => normalizeList(r.data.items ?? r.data)),
  });

  const { data: myBriefs, isLoading: briefsLoading } = useQuery({
    queryKey: ["client-briefs", "mine"],
    queryFn: () => clientBriefApi.listMine({ limit: 20 }).then((r) => r.data),
  });

  const submitMutation = useMutation({
    mutationFn: () =>
      clientBriefApi.submit({
        client_id: clientId || undefined,
        product_name: productName.trim(),
        product_description: productDescription.trim() || undefined,
        target_market: targetMarket.trim(),
        campaign_goal: campaignGoal,
        language: languages[0],
        languages,
        desired_platforms: platforms,
        media_urls: mediaUrls,
        notes: notes.trim() || undefined,
      }),
    onSuccess: () => {
      toast.success(t("clientBrief.submitted"));
      setProductName("");
      setProductDescription("");
      setTargetMarket("");
      setNotes("");
      setMediaUrls([]);
      qc.invalidateQueries({ queryKey: ["client-briefs"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const togglePlatform = (p: string) => {
    setPlatforms((prev) =>
      prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p],
    );
  };

  const toggleLanguage = (lang: ClientBriefLanguage) => {
    setLanguages((prev) => {
      if (prev.includes(lang)) {
        const next = prev.filter((x) => x !== lang);
        return next.length ? next : prev;
      }
      return [...prev, lang];
    });
  };

  const handleFileUpload = async (files: FileList | null) => {
    if (!files?.length) return;
    const resolvedClientId = clientId || clients?.[0]?.id;
    if (!resolvedClientId) {
      toast.error(t("clientBrief.noClient"));
      return;
    }
    setUploading(true);
    try {
      const uploaded: string[] = [];
      for (const file of Array.from(files)) {
        const res = await mediaApi.upload(resolvedClientId, file);
        if (res.data.url) uploaded.push(res.data.url);
      }
      setMediaUrls((prev) => [...prev, ...uploaded]);
      toast.success(t("clientBrief.mediaAdded"));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("errors.generic"));
    } finally {
      setUploading(false);
    }
  };

  if (clientsLoading) return <LoadingState message={t("common.loading")} />;

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <form
        className="card-premium p-6 space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (!productName.trim() || !targetMarket.trim()) {
            toast.error(t("clientBrief.fillRequired"));
            return;
          }
          if (platforms.length === 0) {
            toast.error(t("clientBrief.pickPlatform"));
            return;
          }
          submitMutation.mutate();
        }}
      >
        {clients && clients.length > 1 && (
          <div>
            <label className="text-xs font-medium text-gray-600">{t("clientBrief.client")}</label>
            <select
              className="input mt-1 w-full"
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
            >
              <option value="">{t("clientBrief.defaultClient")}</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.company_name}
                </option>
              ))}
            </select>
          </div>
        )}

        <div>
          <label className="text-xs font-medium text-gray-600">{t("clientBrief.productName")} *</label>
          <input
            className="input mt-1 w-full"
            value={productName}
            onChange={(e) => setProductName(e.target.value)}
            placeholder={t("clientBrief.productNamePlaceholder")}
            required
          />
        </div>

        <div>
          <label className="text-xs font-medium text-gray-600">{t("clientBrief.productDescription")}</label>
          <textarea
            className="input mt-1 w-full min-h-[72px]"
            value={productDescription}
            onChange={(e) => setProductDescription(e.target.value)}
            placeholder={t("clientBrief.productDescriptionPlaceholder")}
          />
        </div>

        <div>
          <label className="text-xs font-medium text-gray-600">{t("clientBrief.targetMarket")} *</label>
          <input
            className="input mt-1 w-full"
            value={targetMarket}
            onChange={(e) => setTargetMarket(e.target.value)}
            placeholder={t("clientBrief.targetMarketPlaceholder")}
            required
          />
        </div>

        <div>
          <label className="text-xs font-medium text-gray-600">{t("clientBrief.campaignGoal")} *</label>
          <select
            className="input mt-1 w-full"
            value={campaignGoal}
            onChange={(e) => setCampaignGoal(e.target.value as ClientBriefCampaignGoal)}
          >
            {CAMPAIGN_GOALS.map((g) => (
              <option key={g.value} value={g.value}>
                {t(g.labelKey)}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-xs font-medium text-gray-600">{t("clientBrief.languages")}</label>
          <div className="mt-2 flex flex-wrap gap-2">
            {LANGUAGES.map((l) => (
              <button
                key={l.value}
                type="button"
                onClick={() => toggleLanguage(l.value)}
                className={`text-xs px-3 py-1.5 rounded-full border ${
                  languages.includes(l.value)
                    ? "bg-brand-50 border-brand-300 text-brand-800"
                    : "bg-white border-gray-200 text-gray-600"
                }`}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="text-xs font-medium text-gray-600">{t("clientBrief.platforms")}</label>
          <div className="mt-2 flex flex-wrap gap-2">
            {PLATFORMS.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => togglePlatform(p)}
                className={`text-xs px-3 py-1.5 rounded-full border capitalize ${
                  platforms.includes(p)
                    ? "bg-brand-50 border-brand-300 text-brand-800"
                    : "bg-white border-gray-200 text-gray-600"
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="text-xs font-medium text-gray-600">{t("clientBrief.notes")}</label>
          <textarea
            className="input mt-1 w-full min-h-[72px]"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder={t("clientBrief.notesPlaceholder")}
          />
        </div>

        <div>
          <label className="text-xs font-medium text-gray-600">{t("clientBrief.media")}</label>
          <div className="mt-2 flex items-center gap-3">
            <label className="btn-secondary text-xs cursor-pointer">
              {uploading ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              {t("clientBrief.uploadMedia")}
              <input
                type="file"
                className="hidden"
                accept="image/*,video/*"
                multiple
                disabled={uploading}
                onChange={(e) => handleFileUpload(e.target.files)}
              />
            </label>
            <span className="text-xs text-gray-400">{t("clientBrief.mediaHint")}</span>
          </div>
          {mediaUrls.length > 0 && (
            <ul className="mt-2 space-y-1">
              {mediaUrls.map((url, i) => (
                <li key={url} className="flex items-center gap-2 text-xs text-gray-600">
                  <span className="truncate flex-1">{url.split("/").pop()}</span>
                  <button
                    type="button"
                    onClick={() => setMediaUrls((prev) => prev.filter((_, j) => j !== i))}
                    className="text-gray-400 hover:text-red-600"
                  >
                    <X size={12} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <button type="submit" className="btn-primary w-full sm:w-auto" disabled={submitMutation.isPending}>
          {submitMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <ClipboardPen size={16} />}
          {t("clientBrief.submit")}
        </button>
      </form>

      <div className="card-premium p-6">
        <h2 className="text-sm font-semibold text-navy-900 mb-3">{t("clientBrief.myBriefs")}</h2>
        {briefsLoading ? (
          <LoadingState variant="inline" />
        ) : !myBriefs?.items.length ? (
          <EmptyState title={t("clientBrief.noBriefs")} />
        ) : (
          <ul className="space-y-2">
            {myBriefs.items.map((b) => (
              <li key={b.id}>
                <Link
                  href={`/briefs/${b.id}`}
                  className="flex items-center justify-between gap-3 rounded-lg border border-gray-100 px-3 py-2 text-sm hover:bg-slate-50 transition-colors"
                >
                  <div className="min-w-0">
                    <p className="font-medium text-gray-900 truncate">{b.product_name}</p>
                    <p className="text-xs text-gray-500 truncate">
                      {b.target_market} · {statusLabel(b.status, t)}
                    </p>
                  </div>
                  <span className="text-[10px] uppercase tracking-wide text-gray-400 shrink-0">
                    {new Date(b.created_at).toLocaleDateString()}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function AdminBriefPanel() {
  const { t } = useTranslation();
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["client-briefs", "admin"],
    queryFn: () => clientBriefApi.listAll({ limit: 100 }).then((r) => r.data),
  });

  if (isLoading) return <LoadingState message={t("common.loading")} />;
  if (isError) return <ErrorState onRetry={() => refetch()} />;

  if (!data?.items.length) {
    return (
      <EmptyState title={t("clientBrief.noBriefs")} description={t("clientBrief.adminEmpty")} />
    );
  }

  return (
    <div className="card-premium divide-y divide-gray-100">
      {data.items.map((b) => (
        <Link
          key={b.id}
          href={`/briefs/${b.id}`}
          className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-slate-50 transition-colors"
        >
          <div className="min-w-0">
            <p className="font-medium text-gray-900 truncate">{b.product_name}</p>
            <p className="text-xs text-gray-500 truncate">
              {b.tenant_name ?? b.company_name} · {b.target_market}
            </p>
          </div>
          <span
            className={cn(
              "text-[10px] px-2 py-0.5 rounded-full border font-medium shrink-0",
              STATUS_STYLES[b.status] ?? STATUS_STYLES.new,
            )}
          >
            {statusLabel(b.status, t)}
          </span>
        </Link>
      ))}
    </div>
  );
}

export default function BriefsPage() {
  const { t } = useTranslation();
  const { adminWidgetsEnabled, tenantWidgetsEnabled, authReady } = useDashboardAuthGates();

  if (!authReady) return <LoadingState message={t("common.loading")} />;

  const isAdminView = adminWidgetsEnabled;

  return (
    <div className="p-4 sm:p-6 space-y-6">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-brand-50 flex items-center justify-center">
          <ClipboardPen size={20} className="text-brand-600" />
        </div>
        <div>
          <h1 className="text-xl font-semibold text-navy-900">
            {isAdminView ? t("clientBrief.adminTitle") : t("clientBrief.title")}
          </h1>
          <p className="text-sm text-gray-500">
            {isAdminView ? t("clientBrief.adminSubtitle") : t("clientBrief.subtitle")}
          </p>
        </div>
      </div>

      {isAdminView ? <AdminBriefPanel /> : tenantWidgetsEnabled ? <TenantBriefForm /> : null}
    </div>
  );
}
