"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImageIcon, Loader2, Palette } from "lucide-react";
import toast from "react-hot-toast";
import { factoryPlatformApi } from "@/lib/api";
import { OnboardingStepShell } from "@/components/onboarding/OnboardingStepShell";
import { useOnboardingRefresh, useOnboardingTenantId } from "@/lib/onboarding-hooks";

export default function OnboardingBrandingPage() {
  const qc = useQueryClient();
  const tenantId = useOnboardingTenantId();
  const refresh = useOnboardingRefresh();

  const { data: profile } = useQuery({
    queryKey: ["factory-profile", tenantId],
    queryFn: () => factoryPlatformApi.profile(tenantId).then((r) => r.data),
    enabled: !!tenantId,
  });

  const [brandName, setBrandName] = useState("");
  const [logoUrl, setLogoUrl] = useState("");

  useEffect(() => {
    if (profile?.profile) {
      setBrandName(profile.profile.brand_name ?? profile.profile.company_name ?? "");
      setLogoUrl(profile.profile.logo_url ?? "");
    }
  }, [profile]);

  const save = useMutation({
    mutationFn: () =>
      factoryPlatformApi.updateProfile(tenantId, {
        brand_name: brandName.trim() || undefined,
        logo_url: logoUrl.trim() || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["factory-profile", tenantId] });
      refresh.mutate();
      toast.success("Brand identity saved");
    },
    onError: () => toast.error("Could not save branding"),
  });

  return (
    <OnboardingStepShell
      stepId="logo_branding"
      title="Logo & branding"
      subtitle="Your visual identity appears on proposals, content, and your factory profile."
      illustration="platform"
      nextHref="/onboarding/team"
      nextLabel="Continue to team"
    >
      <form
        className="space-y-6"
        onSubmit={(e) => {
          e.preventDefault();
          if (!logoUrl.trim() && !brandName.trim()) {
            toast.error("Add a brand name or logo URL");
            return;
          }
          save.mutate();
        }}
      >
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card space-y-4">
          <div className="flex items-center gap-2 text-brand-700">
            <Palette size={18} />
            <span className="font-semibold text-sm">Brand name</span>
          </div>
          <input
            type="text"
            value={brandName}
            onChange={(e) => setBrandName(e.target.value)}
            placeholder="How buyers see your factory"
            className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/30"
          />
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-card space-y-4">
          <div className="flex items-center gap-2 text-brand-700">
            <ImageIcon size={18} />
            <span className="font-semibold text-sm">Logo URL</span>
          </div>
          <input
            type="url"
            value={logoUrl}
            onChange={(e) => setLogoUrl(e.target.value)}
            placeholder="https://your-factory.com/logo.png"
            className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/30"
          />
          {logoUrl.trim() ? (
            <div className="flex items-center gap-4 p-4 rounded-xl bg-slate-50 border border-slate-100">
              <div className="w-16 h-16 rounded-xl border border-white bg-white shadow-sm flex items-center justify-center overflow-hidden">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={logoUrl} alt="Logo preview" className="max-w-full max-h-full object-contain" />
              </div>
              <p className="text-sm text-gray-600">Logo preview — appears on proposals and your factory catalog.</p>
            </div>
          ) : (
            <p className="text-xs text-gray-500">
              Paste a public image URL. You can also upload media in the Media Library and copy the link.
            </p>
          )}
        </div>

        <button
          type="submit"
          disabled={save.isPending}
          className="inline-flex items-center gap-2 rounded-xl bg-brand-600 text-white text-sm font-semibold px-5 py-2.5 hover:bg-brand-700 disabled:opacity-50"
        >
          {save.isPending ? <Loader2 size={16} className="animate-spin" /> : null}
          Save branding
        </button>
      </form>
    </OnboardingStepShell>
  );
}
