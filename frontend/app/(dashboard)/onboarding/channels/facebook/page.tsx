"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Facebook, Loader2, ShieldCheck } from "lucide-react";
import toast from "react-hot-toast";
import { metaPublishingApi, publishingApi } from "@/lib/api";
import { OnboardingStepShell } from "@/components/onboarding/OnboardingStepShell";
import { useOnboardingReadiness, useOnboardingTenantId } from "@/lib/onboarding-hooks";
import { cn } from "@/lib/utils";

export default function OnboardingFacebookPage() {
  const qc = useQueryClient();
  const tenantId = useOnboardingTenantId();
  const scopeParams = tenantId ? { tenant_id: tenantId } : undefined;
  const { data: readiness } = useOnboardingReadiness();

  const telegramDone = readiness?.platform_steps.find((s) => s.id === "telegram_connected")?.status === "completed";
  const facebookStep = readiness?.platform_steps.find((s) => s.id === "facebook_connected");

  const { data: meta, isLoading } = useQuery({
    queryKey: ["meta-connection", tenantId],
    queryFn: () => metaPublishingApi.getConnection(scopeParams).then((r) => r.data),
    enabled: !!tenantId,
  });

  const { data: accounts } = useQuery({
    queryKey: ["publishing-accounts", tenantId],
    queryFn: () => publishingApi.listAccounts(scopeParams).then((r) => r.data),
    enabled: !!tenantId,
  });

  const facebookAccount = accounts?.items.find((a) => a.platform === "facebook");
  const connected = facebookStep?.status === "completed" || !!meta?.connected || facebookAccount?.status === "connected";

  const connect = useMutation({
    mutationFn: async () => {
      const { data: start } = await metaPublishingApi.oauthStart(scopeParams);
      if (start.mode === "demo") {
        await metaPublishingApi.demoConnect(scopeParams);
        return;
      }
      if (start.authorize_url) {
        window.location.href = start.authorize_url;
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["meta-connection", tenantId] });
      qc.invalidateQueries({ queryKey: ["tenant-onboarding-readiness"] });
      toast.success("Facebook connected");
    },
    onError: () => toast.error("Could not connect Facebook"),
  });

  return (
    <OnboardingStepShell
      stepId="facebook_connected"
      title="Connect Facebook"
      subtitle="Facebook unlocks Meta Business integration and cross-posting to export buyers."
      illustration="platform"
      nextHref="/onboarding/channels/instagram"
      nextLabel="Continue to Instagram"
    >
      <div className="space-y-5">
        {!telegramDone ? (
          <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 flex gap-3">
            <AlertTriangle size={20} className="text-amber-600 shrink-0" />
            <div>
              <p className="font-semibold text-amber-900">Connect Telegram first</p>
              <p className="text-sm text-amber-800 mt-1">
                Telegram must be linked before Facebook — it powers content intake for your factory.
              </p>
              <Link href="/onboarding/channels" className="text-sm font-medium text-amber-900 underline mt-2 inline-block">
                Go to Telegram setup →
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
            <div className="w-14 h-14 rounded-2xl bg-[#1877F2]/10 flex items-center justify-center shrink-0">
              <Facebook size={28} className="text-[#1877F2]" />
            </div>
            <div className="flex-1">
              <h3 className="font-semibold text-navy-900">Meta Business (Facebook)</h3>
              {isLoading ? (
                <p className="text-sm text-gray-500 mt-1">Checking connection…</p>
              ) : connected ? (
                <p className="text-sm text-emerald-700 mt-1 flex items-center gap-1.5">
                  <ShieldCheck size={14} />
                  Connected{meta?.facebook?.account_name ? ` — ${meta.facebook.account_name}` : ""}
                </p>
              ) : (
                <p className="text-sm text-gray-600 mt-1">
                  OAuth links your Facebook Page for automated publishing and buyer reach.
                </p>
              )}

              {!connected && telegramDone ? (
                <button
                  type="button"
                  onClick={() => connect.mutate()}
                  disabled={connect.isPending || facebookStep?.status === "blocked"}
                  className="mt-4 inline-flex items-center gap-2 rounded-xl bg-[#1877F2] text-white text-sm font-semibold px-5 py-2.5 hover:bg-[#166fe0] disabled:opacity-50"
                >
                  {connect.isPending ? <Loader2 size={16} className="animate-spin" /> : null}
                  Connect Facebook
                </button>
              ) : null}

              <Link href="/publishing" className="block text-sm text-brand-600 font-medium mt-3 hover:underline">
                Manage in Publishing Hub →
              </Link>
            </div>
          </div>
        </div>
      </div>
    </OnboardingStepShell>
  );
}
