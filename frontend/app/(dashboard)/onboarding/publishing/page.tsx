"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { factoryPlatformApi } from "@/lib/api";
import {
  AutosaveIndicator,
  OnboardingFormField,
  OnboardingSelect,
} from "@/components/onboarding/OnboardingFormField";
import { OnboardingFormSkeleton } from "@/components/onboarding/OnboardingEmptyState";
import { OnboardingWizardShell } from "@/components/onboarding/OnboardingWizardShell";
import {
  useOnboardingTenantId,
  usePrimaryClient,
  usePublishingPrefs,
} from "@/lib/onboarding-hooks";
import {
  APPROVAL_MODE_OPTIONS,
  LANGUAGE_OPTIONS,
  POSTING_FREQUENCY_OPTIONS,
  TIMEZONE_OPTIONS,
} from "@/lib/onboarding-wizard";
import { cn } from "@/lib/utils";

export default function OnboardingPublishingPage() {
  const tenantId = useOnboardingTenantId();
  const { data: profile, isLoading } = useQuery({
    queryKey: ["factory-profile", tenantId],
    queryFn: () => factoryPlatformApi.profile(tenantId).then((r) => r.data),
    enabled: !!tenantId,
  });
  const { data: client } = usePrimaryClient();
  const { localPrefs, status, savePrefs } = usePublishingPrefs();

  const [preferredLanguages, setPreferredLanguages] = useState<string[]>(["English", "Russian"]);
  const [timezone, setTimezone] = useState(
    () => localPrefs?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone,
  );
  const [postingFrequency, setPostingFrequency] = useState(localPrefs?.posting_frequency ?? "3x_week");
  const [approvalMode, setApprovalMode] = useState<"auto" | "manual">("manual");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const initializedRef = useRef(false);

  useEffect(() => {
    if (client && !initializedRef.current) {
      const isAuto =
        client.telegram_workflow_mode === "auto_create_from_media" || client.operator_auto_draft_enabled;
      setApprovalMode(isAuto ? "auto" : "manual");
    }
  }, [client]);

  useEffect(() => {
    if (localPrefs?.timezone) setTimezone(localPrefs.timezone);
    if (localPrefs?.posting_frequency) setPostingFrequency(localPrefs.posting_frequency);
  }, [localPrefs]);

  const triggerSave = useCallback(
    (langs: string[], tz: string, freq: string, approval: "auto" | "manual") => {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        savePrefs({
          preferred_languages: langs,
          timezone: tz,
          posting_frequency: freq,
          approval_mode: approval,
          company_name: profile?.profile.company_name ?? "My Company",
        });
      }, 700);
    },
    [savePrefs, profile?.profile.company_name],
  );

  useEffect(() => {
    if (!initializedRef.current) {
      initializedRef.current = true;
      return;
    }
    triggerSave(preferredLanguages, timezone, postingFrequency, approvalMode);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [preferredLanguages, timezone, postingFrequency, approvalMode, triggerSave]);

  function toggleLanguage(lang: string) {
    setPreferredLanguages((prev) =>
      prev.includes(lang) ? prev.filter((l) => l !== lang) : [...prev, lang],
    );
  }

  if (isLoading) {
    return (
      <OnboardingWizardShell stepId="publishing" title="Publishing preferences" subtitle="">
        <OnboardingFormSkeleton />
      </OnboardingWizardShell>
    );
  }

  return (
    <OnboardingWizardShell
      stepId="publishing"
      title="Publishing preferences"
      subtitle="Set defaults for content language, schedule, and approval workflow. Changes save automatically."
      nextLabel="Finish setup"
    >
      <div className="card-premium p-6 sm:p-8 space-y-7 max-w-2xl">
        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-gray-500 dark-tenant:text-slate-500">Preferences apply across connected channels</p>
          <AutosaveIndicator status={status} />
        </div>

        <OnboardingFormField label="Preferred languages" hint="Content will be generated and published in these languages">
          <div className="flex flex-wrap gap-2">
            {LANGUAGE_OPTIONS.map((lang) => (
              <button
                key={lang}
                type="button"
                onClick={() => toggleLanguage(lang)}
                className={cn(
                  "px-3 py-2 rounded-xl text-sm font-medium border transition-colors",
                  preferredLanguages.includes(lang)
                    ? "bg-brand-50 border-brand-300 text-brand-800 dark-tenant:bg-violet-500/15 dark-tenant:border-violet-500/40 dark-tenant:text-violet-200"
                    : "border-slate-200 text-gray-600 hover:border-slate-300 dark-tenant:border-white/[0.08] dark-tenant:text-slate-400",
                )}
              >
                {lang}
              </button>
            ))}
          </div>
        </OnboardingFormField>

        <OnboardingFormField label="Posting frequency">
          <OnboardingSelect
            value={postingFrequency}
            onChange={setPostingFrequency}
            options={POSTING_FREQUENCY_OPTIONS.map((o) => ({ label: o.label, value: o.value }))}
          />
        </OnboardingFormField>

        <OnboardingFormField label="Timezone" hint="Posts are scheduled in this timezone">
          <OnboardingSelect
            value={timezone}
            onChange={setTimezone}
            options={TIMEZONE_OPTIONS.map((tz) => ({ label: tz.replace(/_/g, " "), value: tz }))}
          />
        </OnboardingFormField>

        <OnboardingFormField label="Default approval mode">
          <div className="space-y-2">
            {APPROVAL_MODE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setApprovalMode(opt.value)}
                className={cn(
                  "w-full text-left rounded-2xl border p-4 transition-all",
                  approvalMode === opt.value
                    ? "border-brand-300 bg-brand-50/60 ring-1 ring-brand-200 dark-tenant:border-violet-500/40 dark-tenant:bg-violet-500/10"
                    : "border-slate-200 bg-white hover:border-slate-300 dark-tenant:border-white/[0.08] dark-tenant:bg-surface-dark-elevated",
                )}
              >
                <p className="font-semibold text-sm text-navy-900 dark-tenant:text-slate-100">{opt.label}</p>
                <p className="text-xs text-gray-500 mt-1 dark-tenant:text-slate-500">{opt.description}</p>
              </button>
            ))}
          </div>
        </OnboardingFormField>

        {status === "error" ? (
          <button
            type="button"
            onClick={() =>
              savePrefs({
                preferred_languages: preferredLanguages,
                timezone,
                posting_frequency: postingFrequency,
                approval_mode: approvalMode,
                company_name: profile?.profile.company_name ?? "My Company",
              })
            }
            className="inline-flex items-center gap-1.5 text-sm text-red-600 hover:underline dark-tenant:text-red-400"
          >
            <RefreshCw size={14} />
            Retry save
          </button>
        ) : null}
      </div>
    </OnboardingWizardShell>
  );
}
