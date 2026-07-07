"use client";

import { Clock, MessageCircle } from "lucide-react";
import { OnboardingStepShell } from "@/components/onboarding/OnboardingStepShell";

export default function OnboardingWeChatPage() {
  return (
    <OnboardingStepShell
      stepId="wechat_placeholder"
      title="WeChat integration"
      subtitle="Connect to China's largest B2B buyer network — coming soon."
      illustration="platform"
      nextHref="/onboarding/products"
      nextLabel="Continue to products"
    >
      <div className="rounded-3xl border border-emerald-100 bg-gradient-to-br from-emerald-50/60 to-white p-8 text-center shadow-card animate-fade-in-up">
        <div className="w-16 h-16 rounded-2xl bg-emerald-100 flex items-center justify-center mx-auto mb-5">
          <MessageCircle size={32} className="text-emerald-600" />
        </div>
        <div className="inline-flex items-center gap-1.5 rounded-full bg-white border border-emerald-200 px-3 py-1 text-xs font-semibold text-emerald-700 mb-4">
          <Clock size={12} />
          Coming soon
        </div>
        <h3 className="text-lg font-semibold text-navy-900">WeChat Business is on our roadmap</h3>
        <p className="text-sm text-gray-600 mt-3 max-w-md mx-auto leading-relaxed">
          We&apos;re building native WeChat integration for domestic buyer networks. No action is required today —
          this optional step won&apos;t block your platform readiness.
        </p>
        <p className="text-xs text-gray-500 mt-4">
          You&apos;ll be notified when WeChat channels are available for your workspace.
        </p>
      </div>
    </OnboardingStepShell>
  );
}
