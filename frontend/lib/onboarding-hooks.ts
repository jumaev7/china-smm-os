"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  clientsApi,
  customerSuccessJourneyApi,
  factoryPlatformApi,
  tenantOnboardingApi,
  type NorthStarGoalKey,
  type OnboardingCompanyProfile,
  type OnboardingReadinessResponse,
  type OnboardingStepReadiness,
} from "@/lib/api";
import { useAuth } from "@/lib/auth-store";
import {
  computeWizardProgress,
  readPublishingPrefs,
  type PublishingPrefsLocal,
  type WizardProgressState,
  writePublishingPrefs,
} from "@/lib/onboarding-wizard";

export function useOnboardingReadiness() {
  return useQuery({
    queryKey: ["tenant-onboarding-readiness"],
    queryFn: () => tenantOnboardingApi.readiness().then((r) => r.data),
  });
}

export function useOnboardingDashboard() {
  return useQuery({
    queryKey: ["tenant-onboarding"],
    queryFn: () => tenantOnboardingApi.dashboard().then((r) => r.data),
  });
}

export function useOnboardingTenantId(): string {
  const { user } = useAuth();
  const { data: readiness } = useOnboardingReadiness();
  const { data: dashboard } = useOnboardingDashboard();
  return readiness?.tenant_id ?? dashboard?.tenant_id ?? user?.tenant_id ?? "";
}

export function useOnboardingStep(stepId: string): OnboardingStepReadiness | undefined {
  const { data: readiness } = useOnboardingReadiness();
  if (!readiness) return undefined;
  return [...readiness.platform_steps, ...readiness.business_steps].find((s) => s.id === stepId);
}

export function useOnboardingRefresh() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => tenantOnboardingApi.refresh().then((r) => r.data),
    onSuccess: (res) => {
      qc.setQueryData(["tenant-onboarding"], res.progress);
      if (res.progress.readiness) {
        qc.setQueryData(["tenant-onboarding-readiness"], res.progress.readiness);
      } else {
        qc.invalidateQueries({ queryKey: ["tenant-onboarding-readiness"] });
      }
      res.progress.new_milestones.forEach((m) => toast.success(m.message, { duration: 5000 }));
    },
  });
}

export function findStepInReadiness(
  readiness: OnboardingReadinessResponse | undefined,
  stepId: string,
): OnboardingStepReadiness | undefined {
  if (!readiness) return undefined;
  return [...readiness.platform_steps, ...readiness.business_steps].find((s) => s.id === stepId);
}

export function useNorthStarOptions() {
  return useQuery({
    queryKey: ["north-star-options"],
    queryFn: () => customerSuccessJourneyApi.northStarOptions().then((r) => r.data),
    staleTime: 60_000 * 60,
  });
}

export function useSaveNorthStarGoal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (goal: NorthStarGoalKey) => tenantOnboardingApi.saveNorthStarGoal(goal).then((r) => r.data),
    onSuccess: (res) => {
      qc.setQueryData<OnboardingReadinessResponse | undefined>(
        ["tenant-onboarding-readiness"],
        (prev) => (prev ? { ...prev, north_star_goal: res.goal, north_star_label: res.label } : prev),
      );
      qc.invalidateQueries({ queryKey: ["tenant-onboarding-readiness"] });
      toast.success("Goal saved");
    },
    onError: () => toast.error("Could not save goal"),
  });
}

export function useSaveCompanyProfile() {
  const qc = useQueryClient();
  const tenantId = useOnboardingTenantId();
  return useMutation({
    mutationFn: (data: OnboardingCompanyProfile) => tenantOnboardingApi.saveCompany(data).then((r) => r.data),
    onSuccess: (res) => {
      qc.setQueryData(["tenant-onboarding"], res.progress);
      qc.invalidateQueries({ queryKey: ["tenant-onboarding-readiness"] });
      qc.invalidateQueries({ queryKey: ["factory-profile", tenantId] });
    },
  });
}

export function useAutosaveCompany(
  form: OnboardingCompanyProfile,
  opts?: { enabled?: boolean; debounceMs?: number },
) {
  const save = useSaveCompanyProfile();
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedRef = useRef<string>("");
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const enabled = opts?.enabled ?? true;
  const debounceMs = opts?.debounceMs ?? 800;

  const serialized = useMemo(() => JSON.stringify(form), [form]);

  useEffect(() => {
    if (!enabled || !form.company_name.trim()) return;
    if (serialized === lastSavedRef.current) return;

    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      setStatus("saving");
      save.mutate(form, {
        onSuccess: () => {
          lastSavedRef.current = serialized;
          setStatus("saved");
        },
        onError: () => setStatus("error"),
      });
    }, debounceMs);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serialized, enabled, debounceMs, form.company_name]);

  return { status, isSaving: save.isPending };
}

export function usePrimaryClient() {
  const tenantId = useOnboardingTenantId();
  return useQuery({
    queryKey: ["onboarding-primary-client", tenantId],
    queryFn: async () => {
      const res = await clientsApi.list({ limit: 1 });
      return res.data.items[0] ?? null;
    },
    enabled: !!tenantId,
  });
}

export function usePublishingPrefs() {
  const tenantId = useOnboardingTenantId();
  const saveCompany = useSaveCompanyProfile();
  const { data: client, refetch: refetchClient } = usePrimaryClient();
  const [localPrefs, setLocalPrefs] = useState<PublishingPrefsLocal | null>(null);
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (tenantId) setLocalPrefs(readPublishingPrefs(tenantId));
  }, [tenantId]);

  const savePrefs = useCallback(
  async (prefs: {
    preferred_languages: string[];
    timezone: string;
    posting_frequency: string;
    approval_mode: "auto" | "manual";
    company_name: string;
  }) => {
    if (!tenantId) return;
    setStatus("saving");
    try {
      writePublishingPrefs(tenantId, {
        timezone: prefs.timezone,
        posting_frequency: prefs.posting_frequency,
        prefs_saved_at: new Date().toISOString(),
      });
      setLocalPrefs(readPublishingPrefs(tenantId));

      await saveCompany.mutateAsync({
        company_name: prefs.company_name || "My Company",
        preferred_languages: prefs.preferred_languages,
      });

      if (client?.id) {
        await clientsApi.update(client.id, {
          telegram_workflow_mode:
            prefs.approval_mode === "auto" ? "auto_create_from_media" : "admin_controlled_buffer",
          operator_auto_draft_enabled: prefs.approval_mode === "auto",
        });
        await refetchClient();
      }

      setStatus("saved");
    } catch {
      setStatus("error");
      toast.error("Could not save publishing preferences");
    }
  },
  [tenantId, saveCompany, client?.id, refetchClient],
  );

  const scheduleSave = useCallback(
    (prefs: Parameters<typeof savePrefs>[0]) => {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => savePrefs(prefs), 700);
    },
    [savePrefs],
  );

  return {
    localPrefs,
    status,
    scheduleSave,
    savePrefs,
    prefsSaved: !!localPrefs?.prefs_saved_at,
  };
}

export function useWizardProgress(currentPath: string): WizardProgressState | null {
  const { data: readiness } = useOnboardingReadiness();
  const { data: dashboard } = useOnboardingDashboard();
  const tenantId = useOnboardingTenantId();
  const prefs = tenantId ? readPublishingPrefs(tenantId) : null;

  return useMemo(() => {
    if (!readiness && !dashboard) return null;
    return computeWizardProgress(
      readiness,
      dashboard,
      currentPath,
      !!prefs?.prefs_saved_at,
    );
  }, [readiness, dashboard, currentPath, prefs?.prefs_saved_at]);
}
