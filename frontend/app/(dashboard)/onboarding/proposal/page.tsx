"use client";

import { FileText, Link2, Sparkles } from "lucide-react";
import { OnboardingActionCard } from "@/components/onboarding/OnboardingActionCard";
import { OnboardingStepShell } from "@/components/onboarding/OnboardingStepShell";

export default function OnboardingProposalPage() {
  return (
    <OnboardingStepShell
      stepId="first_proposal"
      title="First commercial proposal"
      subtitle="Send structured quotes linked to buyers and active deals."
      illustration="business"
      nextHref="/onboarding/executive"
      nextLabel="Continue to executive tour"
    >
      <div className="space-y-3">
        <OnboardingActionCard
          icon={FileText}
          title="Create a proposal"
          description="Open Sales CRM proposals, add line items with MOQ and pricing, then link to a buyer or deal."
          href="/proposals"
          index={0}
        />
        <OnboardingActionCard
          icon={Link2}
          title="Link to buyer / deal"
          description="Select customer and deal when creating the proposal so Growth Center and deal room stay in sync."
          href="/deals"
          index={1}
        />
        <OnboardingActionCard
          icon={Sparkles}
          title="AI-generated proposal"
          description="Generate a professional export quote from product catalog data in minutes."
          href="/proposals"
          badge="AI"
          index={2}
        />
      </div>
    </OnboardingStepShell>
  );
}
