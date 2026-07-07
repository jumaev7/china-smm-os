"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Facebook,
  Instagram,
  Linkedin,
  MessageCircle,
  Music2,
  Send,
  Youtube,
} from "lucide-react";
import toast from "react-hot-toast";
import { metaPublishingApi, publishingApi, tenantOnboardingApi } from "@/lib/api";
import { OnboardingCardsSkeleton } from "@/components/onboarding/OnboardingEmptyState";
import { PlatformConnectionCard } from "@/components/onboarding/PlatformConnectionCard";
import { OnboardingWizardShell } from "@/components/onboarding/OnboardingWizardShell";
import { ErrorState } from "@/components/ui/PageStates";
import { useOnboardingReadiness, useOnboardingTenantId } from "@/lib/onboarding-hooks";

type PlatformKey =
  | "instagram"
  | "facebook"
  | "telegram"
  | "linkedin"
  | "youtube"
  | "tiktok"
  | "wechat";

const PLATFORMS: {
  key: PlatformKey;
  name: string;
  icon: typeof Instagram;
  description: string;
  connectHref?: string;
  comingSoon?: boolean;
}[] = [
  {
    key: "instagram",
    name: "Instagram",
    icon: Instagram,
    description: "Visual product discovery for international buyers.",
    connectHref: "/onboarding/channels/instagram",
  },
  {
    key: "facebook",
    name: "Facebook",
    icon: Facebook,
    description: "Meta Business integration for cross-posting.",
    connectHref: "/onboarding/channels/facebook",
  },
  {
    key: "telegram",
    name: "Telegram",
    icon: Send,
    description: "Content intake and buyer inquiries from your factory group.",
    connectHref: "/clients",
  },
  {
    key: "linkedin",
    name: "LinkedIn",
    icon: Linkedin,
    description: "Professional B2B reach and industry networking.",
    connectHref: "/publishing",
  },
  {
    key: "youtube",
    name: "YouTube",
    icon: Youtube,
    description: "Long-form product and factory storytelling.",
    comingSoon: true,
  },
  {
    key: "tiktok",
    name: "TikTok",
    icon: Music2,
    description: "Short-form video for product discovery.",
    connectHref: "/publishing",
  },
  {
    key: "wechat",
    name: "WeChat",
    icon: MessageCircle,
    description: "China domestic buyer networks.",
    connectHref: "/onboarding/channels/wechat",
    comingSoon: true,
  },
];

export default function OnboardingChannelsPage() {
  const qc = useQueryClient();
  const tenantId = useOnboardingTenantId();
  const scopeParams = tenantId ? { tenant_id: tenantId } : undefined;
  const { data: readiness } = useOnboardingReadiness();

  const {
    data: channels,
    isLoading: channelsLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ["onboarding-channels"],
    queryFn: () => tenantOnboardingApi.channelStatus().then((r) => r.data),
  });

  const { data: accounts, isLoading: accountsLoading } = useQuery({
    queryKey: ["publishing-accounts", tenantId],
    queryFn: () => publishingApi.listAccounts(scopeParams).then((r) => r.data),
    enabled: !!tenantId,
  });

  const { data: meta } = useQuery({
    queryKey: ["meta-connection", tenantId],
    queryFn: () => metaPublishingApi.getConnection(scopeParams).then((r) => r.data),
    enabled: !!tenantId,
  });

  const connectMeta = useMutation({
    mutationFn: async (platform: "facebook" | "instagram") => {
      const { data: start } = await metaPublishingApi.oauthStart(scopeParams);
      if (start.mode === "demo") {
        await metaPublishingApi.demoConnect(scopeParams);
        return platform;
      }
      if (start.authorize_url) {
        window.location.href = start.authorize_url;
      }
      return platform;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["meta-connection", tenantId] });
      qc.invalidateQueries({ queryKey: ["publishing-accounts", tenantId] });
      qc.invalidateQueries({ queryKey: ["tenant-onboarding-readiness"] });
      toast.success("Connection updated");
    },
    onError: () => toast.error("Could not connect account"),
  });

  const tg = channels?.telegram as {
    connected?: boolean;
    group_title?: string | null;
  } | undefined;

  const isLoading = channelsLoading || accountsLoading;

  function getConnectionState(key: PlatformKey): {
    connected: boolean;
    lastSync?: string | null;
  } {
    const account = accounts?.items.find((a) => a.platform === key);
    const accountConnected = account?.status === "connected";

    switch (key) {
      case "telegram": {
        const stepDone =
          readiness?.platform_steps.find((s) => s.id === "telegram_connected")?.status === "completed";
        return { connected: !!stepDone || !!tg?.connected, lastSync: account?.updated_at };
      }
      case "facebook": {
        const stepDone =
          readiness?.platform_steps.find((s) => s.id === "facebook_connected")?.status === "completed";
        return {
          connected: !!stepDone || !!meta?.connected || accountConnected,
          lastSync: account?.updated_at ?? meta?.facebook?.expires_at,
        };
      }
      case "instagram": {
        const stepDone =
          readiness?.platform_steps.find((s) => s.id === "instagram_connected")?.status === "completed";
        return {
          connected: !!stepDone || !!meta?.instagram?.publish_ready || accountConnected,
          lastSync: account?.updated_at,
        };
      }
      case "linkedin":
      case "tiktok":
        return { connected: accountConnected, lastSync: account?.updated_at };
      default:
        return { connected: false };
    }
  }

  if (isError) {
    return (
      <OnboardingWizardShell stepId="connections" title="Platform connections" subtitle="">
        <ErrorState
          message={error instanceof Error ? error.message : "Failed to load connections"}
          onRetry={() => refetch()}
        />
      </OnboardingWizardShell>
    );
  }

  const connectedCount = PLATFORMS.filter((p) => !p.comingSoon && getConnectionState(p.key).connected).length;

  return (
    <OnboardingWizardShell
      stepId="connections"
      title="Platform connections"
      subtitle="Connect the channels where your buyers discover products. You can add more later."
      nextLabel="Continue to publishing"
    >
      <div className="space-y-6 max-w-2xl">
        <div className="rounded-2xl border border-brand-100 bg-brand-50/40 px-4 py-3 text-sm text-brand-800 dark-tenant:border-violet-500/20 dark-tenant:bg-violet-500/10 dark-tenant:text-violet-200">
          {connectedCount > 0
            ? `${connectedCount} platform${connectedCount !== 1 ? "s" : ""} connected — great start.`
            : "Connect at least one channel to unlock publishing."}
        </div>

        {isLoading ? (
          <OnboardingCardsSkeleton count={7} />
        ) : (
          <div className="grid sm:grid-cols-2 gap-3">
            {PLATFORMS.map((platform, i) => {
              const state = getConnectionState(platform.key);

              return (
                <PlatformConnectionCard
                  key={platform.key}
                  icon={platform.icon}
                  name={platform.name}
                  description={platform.description}
                  connected={state.connected}
                  comingSoon={platform.comingSoon}
                  lastSync={state.lastSync}
                  connectHref={platform.connectHref}
                  onConnect={
                    platform.key === "facebook" || platform.key === "instagram"
                      ? () => connectMeta.mutate(platform.key as "facebook" | "instagram")
                      : undefined
                  }
                  connecting={connectMeta.isPending}
                  index={i}
                />
              );
            })}
          </div>
        )}

        {connectedCount === 0 && !isLoading ? (
          <p className="text-sm text-gray-500 text-center dark-tenant:text-slate-500">
            Start with Telegram for content intake, then connect Meta for Facebook and Instagram.
          </p>
        ) : null}
      </div>
    </OnboardingWizardShell>
  );
}
