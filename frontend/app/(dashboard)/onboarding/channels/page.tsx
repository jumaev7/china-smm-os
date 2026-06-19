"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, Clock, MessageCircle } from "lucide-react";
import { tenantOnboardingApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { LoadingState } from "@/components/ui/PageStates";
import { OnboardingLayout } from "@/components/onboarding/OnboardingLayout";

export default function OnboardingChannelsPage() {
  const { data: channels, isLoading } = useQuery({
    queryKey: ["onboarding-channels"],
    queryFn: () => tenantOnboardingApi.channelStatus().then((r) => r.data),
  });

  const tg = channels?.telegram as {
    connected?: boolean;
    verification_status?: string;
    group_title?: string | null;
    guide_steps?: string[];
  } | undefined;

  return (
    <OnboardingLayout
      title="Communication channels"
      subtitle="Connect Telegram to ingest content and receive buyer messages."
      contextStep="channels"
    >
      {isLoading ? <LoadingState message="Checking channel status…" /> : null}

      <div className="space-y-4 max-w-xl">
        <ChannelCard
          name="Telegram"
          available
          connected={!!tg?.connected}
          status={tg?.verification_status === "verified" ? "Connected" : "Setup required"}
          description={
            tg?.group_title
              ? `Linked group: ${tg.group_title}`
              : "Add the bot to your factory Telegram group for content and inquiries."
          }
        >
          <ol className="list-decimal list-inside text-sm text-gray-600 space-y-1 mt-3">
            {(tg?.guide_steps ?? []).map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          <div className="mt-4 flex flex-wrap gap-3">
            <Link href="/content" className="text-sm font-medium text-brand-600 hover:underline">
              Test content upload →
            </Link>
            <Link href="/clients" className="text-sm text-gray-600 hover:underline">
              Client Telegram settings
            </Link>
          </div>
        </ChannelCard>

        <ChannelCard
          name="WeChat"
          available={false}
          connected={false}
          status="Coming soon"
          description="WeChat Business integration is on the roadmap."
        />

        <ChannelCard
          name="WhatsApp"
          available={false}
          connected={false}
          status="Coming soon"
          description="WhatsApp Business integration is on the roadmap."
        />

        <Link
          href="/onboarding/content"
          className="inline-flex items-center gap-2 rounded-lg bg-brand-600 text-white font-medium px-5 py-2.5 hover:bg-brand-700 mt-4"
        >
          Continue to content
          <ArrowRight size={18} />
        </Link>
      </div>
    </OnboardingLayout>
  );
}

function ChannelCard({
  name,
  available,
  connected,
  status,
  description,
  children,
}: {
  name: string;
  available: boolean;
  connected: boolean;
  status: string;
  children?: React.ReactNode;
  description: string;
}) {
  return (
    <div className={cn("rounded-xl border p-5", connected ? "border-emerald-200 bg-emerald-50/50" : "border-slate-200 bg-white")}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <MessageCircle size={20} className={connected ? "text-emerald-600" : "text-gray-400"} />
          <h3 className="font-semibold text-gray-900">{name}</h3>
        </div>
        {connected ? (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700">
            <CheckCircle2 size={12} /> {status}
          </span>
        ) : available ? (
          <span className="text-xs font-medium text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full">{status}</span>
        ) : (
          <span className="inline-flex items-center gap-1 text-xs text-gray-500">
            <Clock size={12} /> {status}
          </span>
        )}
      </div>
      <p className="text-sm text-gray-600 mt-2">{description}</p>
      {children}
    </div>
  );
}
