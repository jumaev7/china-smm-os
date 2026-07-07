"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, RefreshCw } from "lucide-react";
import toast from "react-hot-toast";
import { factoryPlatformApi, type OnboardingCompanyProfile } from "@/lib/api";
import {
  AutosaveIndicator,
  OnboardingFormField,
  OnboardingSelect,
  OnboardingTextInput,
} from "@/components/onboarding/OnboardingFormField";
import { OnboardingFormSkeleton } from "@/components/onboarding/OnboardingEmptyState";
import { OnboardingWizardShell } from "@/components/onboarding/OnboardingWizardShell";
import {
  useAutosaveCompany,
  useOnboardingTenantId,
  useSaveCompanyProfile,
} from "@/lib/onboarding-hooks";
import {
  COMPANY_SIZE_OPTIONS,
  employeeCountToSize,
  readPublishingPrefs,
  sizeToEmployeeCount,
  TIMEZONE_OPTIONS,
  writePublishingPrefs,
} from "@/lib/onboarding-wizard";
import { cn } from "@/lib/utils";

const INDUSTRY_OPTIONS = [
  "Textiles & Apparel",
  "Electronics & Components",
  "Machinery & Equipment",
  "Furniture & Home Goods",
  "Food & Beverage Processing",
  "Automotive Parts",
  "Building Materials",
  "Chemicals & Plastics",
  "Medical Devices",
  "Other Manufacturing",
].map((label) => ({ label, value: label }));

const COUNTRY_OPTIONS = [
  "China",
  "Uzbekistan",
  "Kazakhstan",
  "Russia",
  "Turkey",
  "United Arab Emirates",
  "United States",
  "Germany",
  "Other",
].map((label) => ({ label, value: label }));

export default function OnboardingCompanyPage() {
  const tenantId = useOnboardingTenantId();
  const save = useSaveCompanyProfile();

  const { data: profile, isLoading } = useQuery({
    queryKey: ["factory-profile", tenantId],
    queryFn: () => factoryPlatformApi.profile(tenantId).then((r) => r.data),
    enabled: !!tenantId,
  });

  const [form, setForm] = useState<OnboardingCompanyProfile & { company_size: string; timezone: string }>({
    company_name: "",
    industry: "",
    country: "",
    city: "",
    website: "",
    contact_person: "",
    email: "",
    phone: "",
    preferred_languages: ["English", "Russian"],
    company_size: "",
    timezone: typeof window !== "undefined" ? Intl.DateTimeFormat().resolvedOptions().timeZone : "Asia/Shanghai",
  });

  const [errors, setErrors] = useState<Record<string, string>>({});
  const [touched, setTouched] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (profile?.profile) {
      const p = profile.profile;
      const stored = tenantId ? readPublishingPrefs(tenantId) : null;
      setForm((prev) => ({
        ...prev,
        company_name: p.company_name || prev.company_name,
        industry: p.industry || prev.industry,
        country: p.country || prev.country,
        city: p.city || prev.city,
        website: p.website || prev.website,
        email: p.contact_email || prev.email,
        phone: p.contact_phone || prev.phone,
        company_size: employeeCountToSize(p.employee_count) || prev.company_size,
        timezone: stored?.timezone ?? prev.timezone,
      }));
    }
  }, [profile, tenantId]);

  const companyPayload = useMemo(
    (): OnboardingCompanyProfile => ({
      company_name: form.company_name,
      industry: form.industry,
      country: form.country,
      city: form.city,
      website: form.website,
      contact_person: form.contact_person,
      email: form.email,
      phone: form.phone,
      preferred_languages: form.preferred_languages,
    }),
    [form],
  );

  const autosave = useAutosaveCompany(companyPayload, {
    enabled: !!form.company_name.trim() && Object.keys(errors).length === 0,
  });

  function validate(field?: string): boolean {
    const next: Record<string, string> = {};
    if (!form.company_name.trim()) next.company_name = "Company name is required";
    if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
      next.email = "Enter a valid email address";
    }
    if (field) {
      setErrors((prev) => {
        const merged = { ...prev, ...next };
        if (!next[field]) delete merged[field];
        return merged;
      });
      return !next[field];
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function saveWithProfile() {
    if (!validate()) {
      toast.error("Please fix validation errors");
      return;
    }
    const employeeCount = sizeToEmployeeCount(form.company_size);
    try {
      await save.mutateAsync(companyPayload);
      if (employeeCount && tenantId) {
        await factoryPlatformApi.updateProfile(tenantId, { employee_count: employeeCount });
      }
      toast.success("Company profile saved");
    } catch {
      toast.error("Could not save profile");
    }
  }

  function updateField<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
    setTouched((prev) => ({ ...prev, [key]: true }));
    if (key === "timezone" && tenantId && typeof value === "string") {
      const existing = readPublishingPrefs(tenantId);
      writePublishingPrefs(tenantId, {
        timezone: value,
        posting_frequency: existing?.posting_frequency ?? "3x_week",
        prefs_saved_at: existing?.prefs_saved_at,
      });
    }
  }

  if (isLoading) {
    return (
      <OnboardingWizardShell stepId="company" title="Company information" subtitle="Tell buyers who you are.">
        <OnboardingFormSkeleton />
      </OnboardingWizardShell>
    );
  }

  return (
    <OnboardingWizardShell
      stepId="company"
      title="Company information"
      subtitle="Your factory identity powers catalog pages, proposals, and buyer outreach. Changes save automatically."
      nextLabel="Continue to goal"
    >
      <div className="card-premium p-6 sm:p-8 space-y-6 max-w-2xl">
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-gray-500 dark-tenant:text-slate-500">All fields marked * are required</p>
          <AutosaveIndicator status={autosave.status} />
        </div>

        <OnboardingFormField
          label="Company name"
          required
          error={touched.company_name ? errors.company_name : undefined}
        >
          <OnboardingTextInput
            value={form.company_name}
            onChange={(v) => updateField("company_name", v)}
            onBlur={() => validate("company_name")}
            error={!!errors.company_name}
            placeholder="e.g. Shenzhen Precision Manufacturing Co."
          />
        </OnboardingFormField>

        <div className="grid sm:grid-cols-2 gap-4">
          <OnboardingFormField label="Industry">
            <OnboardingSelect
              value={form.industry ?? ""}
              onChange={(v) => updateField("industry", v)}
              options={INDUSTRY_OPTIONS}
              placeholder="Select industry"
            />
          </OnboardingFormField>
          <OnboardingFormField label="Country">
            <OnboardingSelect
              value={form.country ?? ""}
              onChange={(v) => updateField("country", v)}
              options={COUNTRY_OPTIONS}
              placeholder="Select country"
            />
          </OnboardingFormField>
        </div>

        <OnboardingFormField label="Company size">
          <div className="flex flex-wrap gap-2">
            {COMPANY_SIZE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => updateField("company_size", opt.value)}
                className={cn(
                  "px-3 py-2 rounded-xl text-sm font-medium border transition-colors",
                  form.company_size === opt.value
                    ? "bg-brand-50 border-brand-300 text-brand-800 dark-tenant:bg-violet-500/15 dark-tenant:border-violet-500/40 dark-tenant:text-violet-200"
                    : "border-slate-200 text-gray-600 hover:border-slate-300 dark-tenant:border-white/[0.08] dark-tenant:text-slate-400",
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </OnboardingFormField>

        <OnboardingFormField label="Timezone" hint="Used for scheduling and publishing windows">
          <OnboardingSelect
            value={form.timezone}
            onChange={(v) => updateField("timezone", v)}
            options={TIMEZONE_OPTIONS.map((tz) => ({ label: tz.replace(/_/g, " "), value: tz }))}
          />
        </OnboardingFormField>

        <div className="grid sm:grid-cols-2 gap-4">
          <OnboardingFormField label="City">
            <OnboardingTextInput value={form.city ?? ""} onChange={(v) => updateField("city", v)} />
          </OnboardingFormField>
          <OnboardingFormField label="Website">
            <OnboardingTextInput
              value={form.website ?? ""}
              onChange={(v) => updateField("website", v)}
              placeholder="https://"
            />
          </OnboardingFormField>
        </div>

        <div className="grid sm:grid-cols-2 gap-4">
          <OnboardingFormField label="Email" error={touched.email ? errors.email : undefined}>
            <OnboardingTextInput
              type="email"
              value={form.email ?? ""}
              onChange={(v) => updateField("email", v)}
              onBlur={() => validate("email")}
              error={!!errors.email}
            />
          </OnboardingFormField>
          <OnboardingFormField label="Phone">
            <OnboardingTextInput value={form.phone ?? ""} onChange={(v) => updateField("phone", v)} />
          </OnboardingFormField>
        </div>

        <div className="flex flex-wrap items-center gap-3 pt-2">
          <button
            type="button"
            onClick={saveWithProfile}
            disabled={save.isPending}
            className="inline-flex items-center gap-2 rounded-xl bg-brand-600 text-white font-semibold px-5 py-2.5 hover:bg-brand-700 disabled:opacity-50 dark-tenant:bg-violet-600"
          >
            {save.isPending ? <Loader2 size={16} className="animate-spin" /> : null}
            Save now
          </button>
          {autosave.status === "error" ? (
            <button
              type="button"
              onClick={saveWithProfile}
              className="inline-flex items-center gap-1.5 text-sm text-red-600 hover:underline dark-tenant:text-red-400"
            >
              <RefreshCw size={14} />
              Retry save
            </button>
          ) : null}
        </div>
      </div>
    </OnboardingWizardShell>
  );
}
