"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Instagram, ShieldCheck } from "lucide-react";
import { metaPublishingApi, publishingApi } from "@/lib/api";
import { OnboardingStepShell } from "@/components/onboarding/OnboardingStepShell";
import { useOnboardingReadiness, useOnboardingTenantId } from "@/lib/onboarding-hooks";
import { cn } from "@/lib/utils";

export default function OnboardingInstagramPage() {
  const tenantId = useOnboardingTenantId();
  const scopeParams = tenantId ? { tenant_id: tenantId } : undefined;
  const { data: readiness } = useOnboardingReadiness();

  const facebookDone = readiness?.platform_steps.find((s) => s.id === "facebook_connected")?.status === "completed";
  const instagramStep = readiness?.platform_steps.find((s) => s.id === "instagram_connected");

  const { data: meta } = useQuery({
    queryKey: ["meta-connection", tenantId],
    queryFn: () => metaPublishingApi.getConnection(scopeParams).then((r) => r.data),
    enabled: !!tenantId,
  });

  const { data: accounts } = useQuery({
    queryKey: ["publishing-accounts", tenantId],
    queryFn: () => publishingApi.listAccounts(scopeParams).then((r) => r.data),
    enabled: !!tenantId,
  });

  const igAccount = accounts?.items.find((a) => a.platform === "instagram");
  const connected =
    instagramStep?.status === "completed" || !!meta?.instagram?.account_id || igAccount?.status === "connected";

  return (
    <OnboardingStepShell
      stepId="instagram_connected"
      title="Connect Instagram"
      subtitle="Instagram links through your Facebook Page for visual product discovery."
      illustration="platform"
      nextHref="/onboarding/products"
      nextLabel="Continue to products"
    >
      <div className="space-y-5">
        {!facebookDone ? (
          <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 flex gap-3">
            <AlertTriangle size={20} className="text-amber-600 shrink-0" />
            <div>
              <p className="font-semibold text-amber-900">Connect Facebook first</p>
              <p className="text-sm text-amber-800 mt-1">
                Instagram publishing routes through your linked Meta Business account.
              </p>
              <Link href="/onboarding/channels/facebook" className="text-sm font-medium text-amber-900 underline mt-2 inline-block">
                Go to Facebook setup →
              </Link>
            </div>
          </div>
        ) : null}

        <div
          className={cn(
            "rounded-2xl border p-6 shadow-card",
            connected ? "border-emerald-100 bg-emerald-50/40" : "border-slate-200 bg-white",
          )}
        >
          <div className="flex items-start gap-4">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-purple-500/20 to-pink-500/20 flex items-center justify-center shrink-0">
              <Instagram size={28} className="text-pink-600" />
            </div>
            <div className="flex-1">
              <h3 className="font-semibold text-navy-900">Instagram Business</h3>
              {connected ? (
                <p className="text-sm text-emerald-700 mt-1 flex items-center gap-1.5">
                  <ShieldCheck size={14} />
                  Connected via Meta{meta?.instagram?.account_name ? ` — ${meta.instagram.account_name}` : ""}
                </p>
              ) : facebookDone ? (
                <p className="text-sm text-gray-600 mt-1">
                  Complete Meta OAuth on the Publishing page — Instagram activates automatically when your Facebook
                  Page is linked to an Instagram Business account.
                </p>
              ) : (
                <p className="text-sm text-gray-500 mt-1">Waiting for Facebook connection.</p>
              )}

              {facebookDone && !connected ? (
                <Link
                  href="/publishing"
                  className="mt-4 inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-purple-600 to-pink-600 text-white text-sm font-semibold px-5 py-2.5 hover:opacity-90"
                >
                  Complete in Publishing Hub
                </Link>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </OnboardingStepShell>
  );
}
