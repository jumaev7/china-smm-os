"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  AlertCircle,
  Check,
  History,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  ShieldCheck,
} from "lucide-react";

import { PageShell } from "@/components/ui/design-system";
import {
  BRAND_PROFILES_QUERY_KEY,
  brandProfilesApi,
  getApiErrorMessage,
  getApiErrorStatus,
  type BrandProfile,
  type BrandProfileDraftPayload,
  type BrandProfileVersion,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type DraftForm = {
  name: string;
  locale: string;
  company_name: string;
  company_description: string;
  audience_description: string;
  tone_traits: string;
  preferred_terms: string;
  forbidden_terms: string;
  approved_claims: string;
  prohibited_claims: string;
  source_references: string;
  cta_preferences: string;
  emoji_policy: string;
  formatting_preferences: string;
  platform_guidance: string;
};

type FormErrors = Partial<Record<keyof DraftForm | "form", string>>;

const EMPTY_JSON = "{}";
const SECRET_PATTERN = /\b(api[_-]?key|password|secret|token|private[_-]?key|bearer|system prompt)\b/i;

const EMPTY_FORM: DraftForm = {
  name: "Default Brand Profile",
  locale: "en",
  company_name: "",
  company_description: "",
  audience_description: "",
  tone_traits: "",
  preferred_terms: "",
  forbidden_terms: "",
  approved_claims: "",
  prohibited_claims: "",
  source_references: "",
  cta_preferences: EMPTY_JSON,
  emoji_policy: EMPTY_JSON,
  formatting_preferences: EMPTY_JSON,
  platform_guidance: EMPTY_JSON,
};

function toLines(value: unknown): string {
  return Array.isArray(value) ? value.join("\n") : "";
}

function toJsonText(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return EMPTY_JSON;
  return JSON.stringify(value, null, 2);
}

function formFromProfile(profile?: BrandProfile | null): DraftForm {
  const draft = profile?.draft_payload ?? {};
  return {
    name: profile?.name ?? EMPTY_FORM.name,
    locale: draft.locale ?? EMPTY_FORM.locale,
    company_name: draft.company_name ?? "",
    company_description: draft.company_description ?? "",
    audience_description: draft.audience_description ?? "",
    tone_traits: toLines(draft.tone_traits),
    preferred_terms: toLines(draft.preferred_terms),
    forbidden_terms: toLines(draft.forbidden_terms),
    approved_claims: toLines(draft.approved_claims),
    prohibited_claims: toLines(draft.prohibited_claims),
    source_references: toLines(draft.source_references),
    cta_preferences: toJsonText(draft.cta_preferences),
    emoji_policy: toJsonText(draft.emoji_policy),
    formatting_preferences: toJsonText(draft.formatting_preferences),
    platform_guidance: toJsonText(draft.platform_guidance),
  };
}

function linesToArray(value: string): string[] {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseJsonField(
  value: string,
  key: keyof DraftForm,
  label: string,
  errors: FormErrors,
): Record<string, unknown> {
  const trimmed = value.trim() || EMPTY_JSON;
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      errors[key] = `${label} must be a JSON object.`;
      return {};
    }
    return parsed as Record<string, unknown>;
  } catch {
    errors[key] = `${label} contains invalid JSON.`;
    return {};
  }
}

function validateForm(form: DraftForm): { errors: FormErrors; draft: BrandProfileDraftPayload | null } {
  const errors: FormErrors = {};
  if (!form.name.trim()) errors.name = "Name is required.";
  if (!form.company_description.trim()) {
    errors.company_description = "Company description is required before publishing.";
  }
  if (!form.audience_description.trim()) {
    errors.audience_description = "Target audience is required before publishing.";
  }

  for (const [key, value] of Object.entries(form)) {
    if (SECRET_PATTERN.test(value)) {
      errors[key as keyof DraftForm] = "Remove secret/provider/model/system-prompt details.";
    }
  }

  const cta_preferences = parseJsonField(
    form.cta_preferences,
    "cta_preferences",
    "CTA preferences",
    errors,
  );
  const emoji_policy = parseJsonField(form.emoji_policy, "emoji_policy", "Emoji policy", errors);
  const formatting_preferences = parseJsonField(
    form.formatting_preferences,
    "formatting_preferences",
    "Formatting preferences",
    errors,
  );
  const platform_guidance = parseJsonField(
    form.platform_guidance,
    "platform_guidance",
    "Platform guidance",
    errors,
  );

  if (Object.keys(errors).length > 0) return { errors, draft: null };

  return {
    errors,
    draft: {
      locale: form.locale,
      company_name: form.company_name.trim(),
      company_description: form.company_description.trim(),
      audience_description: form.audience_description.trim(),
      tone_traits: linesToArray(form.tone_traits),
      preferred_terms: linesToArray(form.preferred_terms),
      forbidden_terms: linesToArray(form.forbidden_terms),
      approved_claims: linesToArray(form.approved_claims),
      prohibited_claims: linesToArray(form.prohibited_claims),
      source_references: linesToArray(form.source_references),
      cta_preferences,
      emoji_policy,
      formatting_preferences,
      platform_guidance,
    },
  };
}

export default function BrandProfilePage() {
  const qc = useQueryClient();
  const [selectedProfileId, setSelectedProfileId] = useState<string | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [form, setForm] = useState<DraftForm>(EMPTY_FORM);
  const [errors, setErrors] = useState<FormErrors>({});

  const profilesQuery = useQuery({
    queryKey: BRAND_PROFILES_QUERY_KEY,
    queryFn: () => brandProfilesApi.list().then((r) => r.data),
    staleTime: 15_000,
  });

  const profiles = profilesQuery.data?.items ?? [];
  const activeProfileId = selectedProfileId ?? profiles[0]?.id ?? null;

  const profileQuery = useQuery({
    queryKey: [...BRAND_PROFILES_QUERY_KEY, activeProfileId],
    queryFn: () => brandProfilesApi.get(activeProfileId as string).then((r) => r.data),
    enabled: !!activeProfileId,
    staleTime: 15_000,
  });

  const versionsQuery = useQuery({
    queryKey: [...BRAND_PROFILES_QUERY_KEY, activeProfileId, "versions"],
    queryFn: () => brandProfilesApi.listVersions(activeProfileId as string).then((r) => r.data),
    enabled: !!activeProfileId,
    staleTime: 15_000,
  });

  const profile = profileQuery.data ?? profiles.find((p) => p.id === activeProfileId) ?? null;
  const versions = useMemo(() => versionsQuery.data?.items ?? [], [versionsQuery.data?.items]);
  const selectedVersion = useMemo(
    () =>
      versions.find((v) => v.id === selectedVersionId) ??
      versions.find((v) => v.id === profile?.current_version_id) ??
      versions[0] ??
      null,
    [profile?.current_version_id, selectedVersionId, versions],
  );

  useEffect(() => {
    if (profile) {
      setForm(formFromProfile(profile));
      setErrors({});
    }
  }, [profile]);

  const createMut = useMutation({
    mutationFn: () =>
      brandProfilesApi
        .create({ name: "Default Brand Profile", draft: { locale: "en" } })
        .then((r) => r.data),
    onSuccess: (created) => {
      setSelectedProfileId(created.id);
      qc.setQueryData([...BRAND_PROFILES_QUERY_KEY, created.id], created);
      void qc.invalidateQueries({ queryKey: BRAND_PROFILES_QUERY_KEY });
      toast.success("Brand profile created");
    },
  });

  const saveMut = useMutation({
    mutationFn: () => {
      const { errors: validationErrors, draft } = validateForm(form);
      setErrors(validationErrors);
      if (!draft || !activeProfileId) throw new Error("Fix validation errors before saving.");
      return brandProfilesApi
        .updateDraft(activeProfileId, {
          name: form.name.trim(),
          draft,
          expected_draft_version: profile?.draft_version ?? null,
        })
        .then((r) => r.data);
    },
    onSuccess: (updated) => {
      qc.setQueryData([...BRAND_PROFILES_QUERY_KEY, updated.id], updated);
      void qc.invalidateQueries({ queryKey: BRAND_PROFILES_QUERY_KEY });
      toast.success("Draft saved");
    },
  });

  const publishMut = useMutation({
    mutationFn: async () => {
      if (!activeProfileId) throw new Error("Create a profile before publishing.");
      if (hasUnsavedChanges) {
        await saveMut.mutateAsync();
      }
      return brandProfilesApi.publish(activeProfileId).then((r) => r.data);
    },
    onSuccess: (version) => {
      setSelectedVersionId(version.id);
      void qc.invalidateQueries({ queryKey: BRAND_PROFILES_QUERY_KEY });
      void qc.invalidateQueries({ queryKey: [...BRAND_PROFILES_QUERY_KEY, activeProfileId] });
      void qc.invalidateQueries({ queryKey: [...BRAND_PROFILES_QUERY_KEY, activeProfileId, "versions"] });
      toast.success(`Published version ${version.version}`);
    },
  });

  const hasUnsavedChanges = useMemo(() => {
    if (!profile) return false;
    return JSON.stringify(form) !== JSON.stringify(formFromProfile(profile));
  }, [form, profile]);

  const conflict =
    (saveMut.isError && getApiErrorStatus(saveMut.error) === 409) ||
    (publishMut.isError && getApiErrorStatus(publishMut.error) === 409);

  const actionError =
    saveMut.isError
      ? getApiErrorMessage(saveMut.error)
      : publishMut.isError
        ? getApiErrorMessage(publishMut.error)
        : createMut.isError
          ? getApiErrorMessage(createMut.error)
          : null;

  return (
    <PageShell wide>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-600">
            Governed AI settings
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-gray-900">Brand Profile</h1>
          <p className="mt-2 max-w-3xl text-sm text-gray-600">
            Manage the draft brand context used for AI-assisted adaptation. Published versions are
            immutable and selectable in content workflows.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => profilesQuery.refetch()}
            disabled={profilesQuery.isFetching}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:border-brand-200 disabled:opacity-60"
          >
            <RefreshCw size={14} className={cn(profilesQuery.isFetching && "animate-spin")} />
            Refresh
          </button>
          {profiles.length === 0 ? (
            <button
              type="button"
              onClick={() => createMut.mutate()}
              disabled={createMut.isPending}
              className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
            >
              {createMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              Create profile
            </button>
          ) : null}
        </div>
      </div>

      {profilesQuery.isLoading ? (
        <div className="card p-6 text-sm text-gray-500">Loading brand profile...</div>
      ) : profiles.length === 0 ? (
        <div className="card p-8 text-center">
          <ShieldCheck className="mx-auto text-brand-600" size={28} />
          <h2 className="mt-3 text-lg font-semibold text-gray-900">No Brand Profile yet</h2>
          <p className="mx-auto mt-2 max-w-xl text-sm text-gray-600">
            Create a draft profile to define company description, claims, tone, formatting, and
            platform guidance for governed AI adaptation.
          </p>
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
          <section className="card p-5">
            <div className="flex flex-col gap-3 border-b border-slate-100 pb-4 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h2 className="text-lg font-semibold text-gray-900">Draft profile</h2>
                <p className="mt-1 text-xs text-gray-500">
                  Draft version {profile?.draft_version ?? "—"} ·{" "}
                  {profile?.status === "published" ? "Published profile with editable draft" : "Draft only"}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => saveMut.mutate()}
                  disabled={saveMut.isPending || !hasUnsavedChanges}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700 hover:border-brand-200 disabled:opacity-50"
                >
                  {saveMut.isPending ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                  Save draft
                </button>
                <button
                  type="button"
                  onClick={() => publishMut.mutate()}
                  disabled={publishMut.isPending || saveMut.isPending}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold text-white disabled:opacity-60"
                >
                  {publishMut.isPending ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <ShieldCheck size={13} />
                  )}
                  Publish immutable version
                </button>
              </div>
            </div>

            {actionError ? (
              <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
                {conflict
                  ? "Draft changed elsewhere. Refresh, review the latest draft, then save again."
                  : actionError}
              </div>
            ) : null}

            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <Field label="Profile name" error={errors.name}>
                <input
                  value={form.name}
                  onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
                  className="input"
                />
              </Field>
              <Field label="Locale">
                <select
                  value={form.locale}
                  onChange={(e) => setForm((p) => ({ ...p, locale: e.target.value }))}
                  className="input"
                >
                  <option value="en">English</option>
                  <option value="ru">Russian</option>
                  <option value="uz">Uzbek</option>
                  <option value="zh">Chinese</option>
                </select>
              </Field>
              <Field label="Company name" error={errors.company_name}>
                <input
                  value={form.company_name}
                  onChange={(e) => setForm((p) => ({ ...p, company_name: e.target.value }))}
                  className="input"
                />
              </Field>
              <Field label="Tone traits" hint="One per line" error={errors.tone_traits}>
                <textarea
                  value={form.tone_traits}
                  onChange={(e) => setForm((p) => ({ ...p, tone_traits: e.target.value }))}
                  rows={4}
                  className="input min-h-24"
                />
              </Field>
              <Field
                label="Company description"
                hint="What the company does, where it operates, and what makes it credible."
                error={errors.company_description}
                wide
              >
                <textarea
                  value={form.company_description}
                  onChange={(e) => setForm((p) => ({ ...p, company_description: e.target.value }))}
                  rows={5}
                  className="input min-h-32"
                />
              </Field>
              <Field label="Target audience" error={errors.audience_description} wide>
                <textarea
                  value={form.audience_description}
                  onChange={(e) => setForm((p) => ({ ...p, audience_description: e.target.value }))}
                  rows={4}
                  className="input min-h-28"
                />
              </Field>
              <Field label="Preferred terms" hint="One per line" error={errors.preferred_terms}>
                <textarea
                  value={form.preferred_terms}
                  onChange={(e) => setForm((p) => ({ ...p, preferred_terms: e.target.value }))}
                  rows={4}
                  className="input min-h-24"
                />
              </Field>
              <Field label="Forbidden terms" hint="One per line" error={errors.forbidden_terms}>
                <textarea
                  value={form.forbidden_terms}
                  onChange={(e) => setForm((p) => ({ ...p, forbidden_terms: e.target.value }))}
                  rows={4}
                  className="input min-h-24"
                />
              </Field>
              <Field label="Approved claims" hint="One per line" error={errors.approved_claims}>
                <textarea
                  value={form.approved_claims}
                  onChange={(e) => setForm((p) => ({ ...p, approved_claims: e.target.value }))}
                  rows={5}
                  className="input min-h-28"
                />
              </Field>
              <Field label="Prohibited claims" hint="One per line" error={errors.prohibited_claims}>
                <textarea
                  value={form.prohibited_claims}
                  onChange={(e) => setForm((p) => ({ ...p, prohibited_claims: e.target.value }))}
                  rows={5}
                  className="input min-h-28"
                />
              </Field>
              <JsonField
                label="CTA preferences"
                value={form.cta_preferences}
                error={errors.cta_preferences}
                onChange={(value) => setForm((p) => ({ ...p, cta_preferences: value }))}
              />
              <JsonField
                label="Emoji policy"
                value={form.emoji_policy}
                error={errors.emoji_policy}
                onChange={(value) => setForm((p) => ({ ...p, emoji_policy: value }))}
              />
              <JsonField
                label="Formatting preferences"
                value={form.formatting_preferences}
                error={errors.formatting_preferences}
                onChange={(value) => setForm((p) => ({ ...p, formatting_preferences: value }))}
              />
              <JsonField
                label="Platform guidance"
                value={form.platform_guidance}
                error={errors.platform_guidance}
                onChange={(value) => setForm((p) => ({ ...p, platform_guidance: value }))}
              />
              <Field label="Source references" hint="One per line" error={errors.source_references} wide>
                <textarea
                  value={form.source_references}
                  onChange={(e) => setForm((p) => ({ ...p, source_references: e.target.value }))}
                  rows={3}
                  className="input min-h-20"
                />
              </Field>
            </div>
          </section>

          <aside className="space-y-4">
            <section className="card p-4">
              <div className="flex items-start gap-2">
                <ShieldCheck size={16} className="mt-0.5 text-brand-600" />
                <div>
                  <h2 className="text-sm font-semibold text-gray-900">Published state</h2>
                  <p className="mt-1 text-xs text-gray-500">
                    Current version:{" "}
                    <span className="font-medium text-gray-800">
                      {versions.find((v) => v.id === profile?.current_version_id)?.version ?? "none"}
                    </span>
                  </p>
                  {hasUnsavedChanges ? (
                    <p className="mt-2 rounded-md bg-amber-50 px-2 py-1 text-[11px] text-amber-700">
                      Draft has unsaved changes.
                    </p>
                  ) : null}
                </div>
              </div>
            </section>

            <section className="card p-4">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-900">
                <History size={15} /> Version history
              </h2>
              {versionsQuery.isLoading ? (
                <p className="mt-3 text-xs text-gray-500">Loading versions...</p>
              ) : versions.length === 0 ? (
                <p className="mt-3 text-xs text-gray-500">
                  No published versions yet. Save the draft, then publish an immutable version.
                </p>
              ) : (
                <div className="mt-3 space-y-2">
                  {versions.map((version) => (
                    <button
                      key={version.id}
                      type="button"
                      onClick={() => setSelectedVersionId(version.id)}
                      className={cn(
                        "w-full rounded-lg border px-3 py-2 text-left transition-colors",
                        selectedVersion?.id === version.id
                          ? "border-brand-300 bg-brand-50"
                          : "border-slate-100 bg-white hover:border-slate-200",
                      )}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-gray-800">
                          Version {version.version}
                        </span>
                        {version.id === profile?.current_version_id ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-800">
                            <Check size={10} /> Current
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-1 text-[11px] text-gray-500">
                        {version.locale} · {version.published_at ? new Date(version.published_at).toLocaleString() : "Published"}
                      </p>
                    </button>
                  ))}
                </div>
              )}
            </section>

            {selectedVersion ? <VersionPreview version={selectedVersion} /> : null}
          </aside>
        </div>
      )}
    </PageShell>
  );
}

function Field({
  label,
  hint,
  error,
  wide,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  wide?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className={cn("block", wide && "md:col-span-2")}>
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-gray-700">{label}</span>
        {hint ? <span className="text-[11px] text-gray-400">{hint}</span> : null}
      </div>
      {children}
      {error ? (
        <p className="mt-1 flex items-start gap-1 text-[11px] text-rose-600">
          <AlertCircle size={11} className="mt-0.5 shrink-0" />
          {error}
        </p>
      ) : null}
    </label>
  );
}

function JsonField({
  label,
  value,
  error,
  onChange,
}: {
  label: string;
  value: string;
  error?: string;
  onChange: (value: string) => void;
}) {
  return (
    <Field label={label} hint="JSON object" error={error}>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={5}
        spellCheck={false}
        className="input min-h-28 font-mono text-[12px]"
      />
    </Field>
  );
}

function VersionPreview({ version }: { version: BrandProfileVersion }) {
  return (
    <section className="card p-4">
      <h2 className="text-sm font-semibold text-gray-900">Version {version.version} snapshot</h2>
      <div className="mt-3 space-y-3 text-xs">
        <PreviewRow label="Company" value={version.company_name || "Not set"} />
        <PreviewRow label="Description" value={version.company_description || "Not set"} />
        <PreviewRow label="Audience" value={version.audience_description || "Not set"} />
        <PreviewList label="Tone traits" values={version.tone_traits} />
        <PreviewList label="Preferred terms" values={version.preferred_terms} />
        <PreviewList label="Forbidden terms" values={version.forbidden_terms} />
        <PreviewList label="Approved claims" values={version.approved_claims} />
        <PreviewList label="Prohibited claims" values={version.prohibited_claims} />
        <PreviewObject label="CTA preferences" value={version.cta_preferences} />
        <PreviewObject label="Emoji policy" value={version.emoji_policy} />
        <PreviewObject label="Formatting preferences" value={version.formatting_preferences} />
        <PreviewObject label="Platform guidance" value={version.platform_guidance} />
      </div>
    </section>
  );
}

function PreviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="font-semibold text-gray-700">{label}</p>
      <p className="mt-1 whitespace-pre-wrap text-gray-600">{value}</p>
    </div>
  );
}

function PreviewList({ label, values }: { label: string; values: string[] }) {
  return <PreviewRow label={label} value={values.length ? values.join(", ") : "Not set"} />;
}

function PreviewObject({ label, value }: { label: string; value: Record<string, unknown> }) {
  const text = Object.keys(value || {}).length ? JSON.stringify(value, null, 2) : "Not set";
  return <PreviewRow label={label} value={text} />;
}
